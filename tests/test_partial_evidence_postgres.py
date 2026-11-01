"""Real isolated PG17/MCP/BGE; existing public Dev sources, new nonpaid Runs only."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from datapilot.ingestion.common import digest
from datapilot.persistence.backend import Backend, DurableArtifacts, execute
from datapilot.persistence.session import run_async
from datapilot.rag.contracts import RagScope
from datapilot.rag.mcp import rag_session
from datapilot.reporting.contracts import ReportScope, confirm_finite_scope
from datapilot.reporting.service import report_session

ROOT = Path(__file__).resolve().parents[1]
OUT = None  # Bound by the module reporting_output fixture.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("reporting_output"),
    pytest.mark.skipif(
        os.getenv("DATAPILOT_RUN_DB_TESTS") != "1", reason="Explicit isolated PostgreSQL opt-in"
    ),
]


@pytest.fixture(scope="session")
def dev_environment(reporting_dev):
    return reporting_dev


def config_for(dev, case_id, *, policy="partial-facts-v1"):
    case = next(c for c in dev.cases() if c["id"] == case_id)
    binding = json.loads((dev.OUT / "bindings.json").read_bytes())["bindings"][case_id]
    rag, scope = dev.host_scope(case, binding)
    scope.partial_evidence_policy = policy
    return {"report_scope": scope.model_dump(mode="json"), "rag_scope": rag.model_dump(mode="json")}


def probe(config, action, run_id, *args, expected=0):
    folder = OUT / run_id
    folder.mkdir(exist_ok=True)
    path = folder / ("config-" + digest(config) + ".json")
    if not path.exists():
        path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/partial_evidence_probe.py"),
            action,
            run_id,
            str(path),
            *args,
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=110,
    )
    name = action + "-" + uuid4().hex
    (folder / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == expected, f"Probe failed; private log: {folder / (name + '.log')}"
    return json.loads(result.stdout) if result.stdout.strip() else None


def snapshot(settings, run_id, owner):
    backend = Backend(settings.runtime_database_url.get_secret_value(), run_id, owner)
    try:
        artifacts = {
            k: v.model_dump(mode="json") for k, v in DurableArtifacts(backend).export().items()
        }
        with backend.transaction() as conn:
            calls = [
                dict(r)
                for r in execute(
                    conn,
                    "SELECT call_key,kind,status,payload_hash FROM execution.calls "
                    "WHERE run_id=:r ORDER BY call_key",
                    r=run_id,
                ).mappings()
            ]
            ledger = execute(
                conn, "SELECT payload FROM execution.ledger WHERE run_id=:r", r=run_id
            ).scalar_one()
        return {"artifacts": artifacts, "calls": calls, "ledger": ledger}
    finally:
        backend.close()


def assert_no_new_budget_usage(before, after):
    old, new = before["state"], after["state"]
    assert old["pending"] == new["pending"] and old["receipts"] == new["receipts"]
    for name, account in old["accounts"].items():
        assert new["accounts"][name] == account
    # Report is deterministic: a newly scheduled report may open its zero-use account.
    for name in new["accounts"].keys() - old["accounts"].keys():
        assert name == "1:report"
        account = new["accounts"][name]
        assert account["parent"] == "root"
        assert account["usage"]["calls"] == account["usage"]["total_tokens"] == 0


@pytest.mark.parametrize("case_id", ["cp04", "cp06", "cp07"])
def test_real_partial_receipt_report_and_terminal_cross_process_reuse(dev_environment, case_id):
    dev, settings = dev_environment
    config = config_for(dev, case_id)
    # Approve the finite questions, never the deliberately absent fact/source proofs.
    config["report_scope"] = confirm_finite_scope(
        ReportScope.model_validate_json(json.dumps(config["report_scope"])),
        RagScope.model_validate_json(json.dumps(config["rag_scope"])),
        confirmation_ref="public-ci-batch2-partial-scope-review",
    ).model_dump(mode="json")
    run_id = str(uuid4())
    first = probe(config, "start", run_id)
    assert first["business_completion"]["status"] == "partial"
    worker = first["results"]["1:documents"]
    assert (
        worker["status"] == "unavailable" and worker["rag_completion"]["verdict"] == "insufficient"
    )
    assert worker["rag_completion"]["submission"]["outcome"] == "insufficient"
    if case_id != "cp07":
        claim = next(c for c in first["cross_source_report"]["claims"] if c["kind"] == "context")
        assert any(claim["fact_coverage"].values())
    assert "documents" not in first["business_completion"]["verified_goals"]
    before = snapshot(settings, run_id, config["report_scope"]["owner"])
    repeated = probe(config, "resume", run_id)
    assert repeated["cross_source_report"] == first["cross_source_report"]
    assert repeated["usage"] == first["usage"]
    assert before == snapshot(settings, run_id, config["report_scope"]["owner"])
    assert all(c["status"] == "complete" for c in before["calls"])
    if case_id == "cp07":
        metric = next(
            c["metric"] for c in repeated["cross_source_report"]["claims"] if c["kind"] == "metric"
        )
        assert metric["verdict"] == metric["verification"]["verdict"] == "verified"
        assert metric["value"]["unit"] == "CNY"
        assert metric["evidence_id"] and metric["verification"]["verification_id"]


@pytest.mark.parametrize("cut", ["rag_submission_committed", "report_artifact_committed"])
def test_committed_submission_or_report_crash_reuses_without_new_model(dev_environment, cut):
    dev, settings = dev_environment
    config, run_id = config_for(dev, "cp06"), str(uuid4())
    scope = ReportScope.model_validate_json(json.dumps(config["report_scope"]))
    rag = RagScope.model_validate_json(json.dumps(config["rag_scope"]))
    config["report_scope"] = confirm_finite_scope(
        scope, rag, confirmation_ref="public-ci-batch3-partial-recovery-review"
    ).model_dump(mode="json")
    probe(config, "start", run_id, "--cut", cut, expected=91)
    before = snapshot(settings, run_id, config["report_scope"]["owner"])
    other = json.loads(json.dumps(config))
    other["report_scope"] = confirm_finite_scope(
        scope, rag, confirmation_ref="public-ci-batch3-different-confirmation"
    ).model_dump(mode="json")
    refused = probe(other, "resume", run_id, expected=2)
    assert refused["error"]["code"] == "RECOVERY_IDENTITY"
    assert before == snapshot(settings, run_id, config["report_scope"]["owner"])
    first = probe(config, "resume", run_id)
    assert first["business_completion"]["status"] == "partial"
    after = snapshot(settings, run_id, config["report_scope"]["owner"])
    assert_no_new_budget_usage(before["ledger"], after["ledger"])
    assert {c["call_key"]: c for c in before["calls"]}.items() <= {
        c["call_key"]: c for c in after["calls"]
    }.items()
    assert {k: v for k, v in before["artifacts"].items()}.items() <= after["artifacts"].items()
    assert not [c for c in after["calls"] if c["kind"] == "model" and c not in before["calls"]]
    assert probe(config, "resume", run_id)["cross_source_report"] == first["cross_source_report"]


def test_precommit_submission_unknown_remains_uncertain_without_resend(dev_environment):
    dev, settings = dev_environment
    config, run_id = config_for(dev, "cp06"), str(uuid4())
    probe(config, "start", run_id, "--cut", "rag_submission_validated", expected=91)
    before = snapshot(settings, run_id, config["report_scope"]["owner"])
    result = probe(config, "resume", run_id, expected=2)
    assert result["error"]["code"] == "RECOVERY_UNCERTAIN"
    after = snapshot(settings, run_id, config["report_scope"]["owner"])
    assert before["ledger"] == after["ledger"]
    assert before["artifacts"] == after["artifacts"]
    assert [(c["call_key"], c["payload_hash"]) for c in before["calls"]] == [
        (c["call_key"], c["payload_hash"]) for c in after["calls"]
    ]


def test_policy_manifest_conflict_and_legacy_restore(dev_environment):
    dev, settings = dev_environment
    config, run_id = config_for(dev, "cp06", policy="legacy"), str(uuid4())
    first = probe(config, "start", run_id)
    assert "partial_evidence_policy" not in config["report_scope"]
    assert first["business_completion"]["status"] == "unavailable"
    before = snapshot(settings, run_id, config["report_scope"]["owner"])
    other = json.loads(json.dumps(config))
    other["report_scope"]["partial_evidence_policy"] = "partial-facts-v1"
    denied = probe(other, "resume", run_id, expected=2)
    assert denied["error"]["code"] == "RECOVERY_IDENTITY"
    assert before == snapshot(settings, run_id, config["report_scope"]["owner"])
    assert probe(config, "resume", run_id)["cross_source_report"] == first["cross_source_report"]


def test_partial_refs_restore_across_node_checkpoint(dev_environment):
    dev, settings = dev_environment
    config, run_id = config_for(dev, "cp06"), str(uuid4())
    config["report_scope"] = confirm_finite_scope(
        ReportScope.model_validate(config["report_scope"]),
        RagScope.model_validate(config["rag_scope"]),
        confirmation_ref="public-ci-final31-partial-cross-node-review",
    ).model_dump(mode="json")
    paused = probe(config, "start", run_id, "--pause")
    assert paused["status"] == "paused"
    before = snapshot(settings, run_id, config["report_scope"]["owner"])
    final = probe(config, "resume", run_id)
    assert final["business_completion"]["status"] == "partial"
    assert final["results"]["1:documents"] == paused["results"]["1:documents"]
    assert_no_new_budget_usage(
        before["ledger"], snapshot(settings, run_id, config["report_scope"]["owner"])["ledger"]
    )


def test_review_and_cancel_do_not_execute_partial_report(dev_environment):
    dev, settings = dev_environment
    config, run_id = config_for(dev, "cp06"), str(uuid4())
    first = probe(config, "start", run_id, "--review")
    assert first["status"] == "awaiting_review"
    backend = Backend(
        settings.runtime_database_url.get_secret_value(), run_id, config["report_scope"]["owner"]
    )
    try:
        backend.cancel()
    finally:
        backend.close()
    denied = probe(config, "approve", run_id, expected=2)
    assert denied["error"]["code"] == "CANCELLED"
    assert not snapshot(settings, run_id, config["report_scope"]["owner"])["calls"]


def test_revoked_or_changed_scope_is_rejected_before_model(dev_environment):
    dev, settings = dev_environment
    config, run_id = config_for(dev, "cp06"), str(uuid4())
    probe(config, "start", run_id, "--pause")
    before = snapshot(settings, run_id, config["report_scope"]["owner"])
    changed = json.loads(json.dumps(config))
    changed["rag_scope"]["corpora"][0]["index_version"] = "0" * 64
    denied = probe(changed, "resume", run_id, expected=2)
    assert denied["error"]["code"] in {
        "DOCUMENT_NOT_AUTHORIZED",
        "DOCUMENT_VERSION",
        "RECOVERY_VERSION",
        "RECOVERY_IDENTITY",
        "RAG_VERSION_INVALID",
    }
    assert before == snapshot(settings, run_id, config["report_scope"]["owner"])


def test_real_fact_validation_after_rehydration_rejects_wrong_hash(dev_environment):
    from datapilot.contracts import AgentFailure
    from datapilot.orchestration.contracts import Artifact
    from datapilot.orchestration.runtime import ArtifactStore

    dev, settings = dev_environment
    config = config_for(dev, "cp06")
    scope, rag = (
        ReportScope.model_validate(config["report_scope"]),
        RagScope.model_validate(config["rag_scope"]),
    )
    scope = confirm_finite_scope(
        scope, rag, confirmation_ref="public-ci-batch3-partial-hash-review"
    )

    async def check():
        async with (
            rag_session(settings, rag, goal=scope.question) as retrieval,
            report_session(settings, scope, scope.question, scope.owner) as service,
        ):
            result = await retrieval.search(scope.question, 5)
            assert result.documents
            valid_store = ArtifactStore("new-partial-original-control")
            control = valid_store.put(
                Artifact(
                    run_id=valid_store.run_id,
                    task_id="documents",
                    plan_version=1,
                    kind="documents",
                    source="original-source-control",
                    documents=result,
                )
            )
            original = service.build(
                [(control, valid_store.get(control))],
                retrieval,
                source_statuses={"documents": "unavailable"},
            )
            assert original.business_completion.status == "partial"
            assert any(c.fact_coverage.get("identity") is not None for c in original.claims)
            result.documents[0].citation.sha256 = "0" * 64
            store = ArtifactStore("new-partial-corrupt-copy")
            ref = store.put(
                Artifact(
                    run_id=store.run_id,
                    task_id="documents",
                    plan_version=1,
                    kind="documents",
                    source="corrupt-test-copy",
                    documents=result,
                )
            )
            with pytest.raises(AgentFailure):
                service.build(
                    [(ref, store.get(ref))], retrieval, source_statuses={"documents": "unavailable"}
                )

    run_async(check())


def test_corrupted_partial_artifact_blocks_restore_before_any_new_call(dev_environment):
    import sqlalchemy as sa

    from datapilot.db.management import management_url

    dev, settings = dev_environment
    config, run_id = config_for(dev, "cp06"), str(uuid4())
    probe(config, "start", run_id, "--pause")
    before = snapshot(settings, run_id, config["report_scope"]["owner"])
    # Corrupt only this newly created disposable test Run, never an old artifact.
    admin = sa.create_engine(management_url("owner"), hide_parameters=True)
    try:
        with admin.begin() as conn:
            changed = execute(
                conn,
                "UPDATE execution.artifacts SET payload=jsonb_set(payload,'{source}',"
                "'\"corrupted-partial-test\"') WHERE run_id=:r AND kind='documents'",
                r=run_id,
            )
            assert changed.rowcount == 1
    finally:
        admin.dispose()
    result = probe(config, "resume", run_id, expected=2)
    assert result["error"]["code"] == "EVIDENCE_INVALID"
    backend = Backend(
        settings.runtime_database_url.get_secret_value(), run_id, config["report_scope"]["owner"]
    )
    try:
        with backend.transaction() as conn:
            assert (
                execute(
                    conn, "SELECT payload FROM execution.ledger WHERE run_id=:r", r=run_id
                ).scalar_one()
                == before["ledger"]
            )
            assert execute(
                conn, "SELECT count(*) FROM execution.calls WHERE run_id=:r", r=run_id
            ).scalar_one() == len(before["calls"])
    finally:
        backend.close()
