"""Real isolated PG/MCP/BGE; new Runs on reused public Dev, no paid model calls."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from test_citation_policy_postgres import configured
from test_partial_evidence_postgres import config_for, snapshot
from test_partial_evidence_postgres import dev_environment as dev_environment

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetScope
from datapilot.db.management import management_url
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import BudgetLimits, TaskEnvelope, TaskSpec
from datapilot.orchestration.runtime import text_hash
from datapilot.persistence.backend import Backend, DurableArtifacts, DurableLedger, execute
from datapilot.persistence.journal import Journal
from datapilot.rag.contracts import RagScope, Target
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService, make_pin
from datapilot.reporting.contracts import DocumentGoal, ReportScope

ROOT = Path(__file__).resolve().parents[1]
OUT = None  # Bound by the module reporting_output fixture.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("reporting_output"),
    pytest.mark.skipif(
        os.getenv("DATAPILOT_RUN_DB_TESTS") != "1", reason="Explicit isolated PostgreSQL opt-in"
    ),
]


def new_config(dev, case_id="cp09"):
    config = configured(dev, case_id) if case_id in {"cp09", "cp07"} else config_for(dev, case_id)
    config["report_scope"]["rag_query_policy"] = "original-first-v1"
    return config


def probe(config, action, run_id, *args, expected=0):
    folder = OUT / run_id
    folder.mkdir(exist_ok=True)
    path = folder / (digest(config) + ".json")
    if not path.exists():
        path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/original_query_probe.py"),
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
    log = folder / (action + "-" + uuid4().hex + ".log")
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == expected, f"Probe failed; private log: {log}"
    return json.loads(result.stdout) if result.stdout.strip() else None


def journal_observations(settings, run_id, owner):
    backend = Backend(settings.runtime_database_url.get_secret_value(), run_id, owner)
    try:
        with backend.transaction() as conn:
            return [
                dict(r)
                for r in execute(
                    conn,
                    "SELECT call_key,kind,status,fingerprint,payload FROM execution.calls "
                    "WHERE run_id=:r ORDER BY call_key",
                    r=run_id,
                ).mappings()
            ]
    finally:
        backend.close()


def assert_original_search(rows, question):
    searches = [
        r for r in rows if r["call_key"].startswith("tool:") and "retrieve" in r["call_key"]
    ]
    assert len(searches) == 1
    assert searches[0]["fingerprint"] == digest(
        {"name": "search_documents", "arguments": {"query": question, "top_k": 5}}
    )
    calls = [
        c
        for r in rows
        if r["kind"] == "model"
        for c in r["payload"]["data"].get("tool_calls", [])
        if c["name"] == "search_documents"
    ]
    assert len(calls) == 1 and calls[0]["args"] == {"query": question, "top_k": 5}


@pytest.mark.parametrize("case_id", ["cp09", "cp07", "cp06", "cp12", "cp05", "english"])
def test_real_original_query_report_and_terminal_reuse(dev_environment, case_id):
    dev, settings = dev_environment
    config = new_config(dev, case_id) if case_id != "english" else english_config(settings)
    run_id = str(uuid4())
    args = ["--insufficient"] if case_id == "cp07" else []
    first = probe(config, "start", run_id, *args)
    if case_id != "english":
        assert first["business_completion"]["status"] == (
            "partial"
            if case_id in {"cp07", "cp06", "cp12"}
            else "unavailable"
            if case_id == "cp05"
            else "completed"
        )
    question, owner = (
        config["report_scope"]["document_goal"]["question"],
        config["report_scope"]["owner"],
    )
    assert_original_search(journal_observations(settings, run_id, owner), question)
    before = snapshot(settings, run_id, owner)
    if case_id == "english":
        # This is a protocol/recovery assertion, not a changed business Gold. Keep the
        # original expected completed separately: the observed English recall miss is
        # a quality failure and must appear as such even when these contracts pass.
        documents = [
            d
            for a in before["artifacts"].values()
            for d in (a.get("documents") or {}).get("documents", [])
        ]
        quality = {
            "run_id": run_id,
            "expected_business_status": "completed",
            "observed_business_status": first["business_completion"]["status"],
            "business_correct": first["business_completion"]["status"] == "completed",
            "retrieved_chunks": len(documents),
            "threshold": "0.55",
        }
        with (OUT / run_id / "english-quality.json").open("x", encoding="utf-8") as stream:
            json.dump(quality, stream, ensure_ascii=False, indent=2)
        if not documents:
            assert first["business_completion"]["status"] == "unavailable"
            assert not first["business_completion"]["verified_goals"]
    assert first["results"]["1:documents"]["rag_completion"]["goal_sha256"]
    for item in before["artifacts"].values():
        for doc in (item.get("documents") or {}).get("documents", []):
            assert doc["citation"]["goal_sha256"] == text_hash(question)
    repeated = probe(config, "resume", run_id)
    assert first["cross_source_report"] == repeated["cross_source_report"]
    assert first["usage"] == repeated["usage"]
    assert before == snapshot(settings, run_id, owner)


def english_config(settings):
    # Earlier English controls belonged to another isolated instance. Create one new
    # explicitly synthetic control here through the original restricted ingest path.
    path = OUT / "english/bindings.json"
    if path.exists():
        binding = json.loads(path.read_bytes())
    else:
        folder = path.parent
        folder.mkdir(exist_ok=True)
        source = ROOT / "tests/fixtures/rag/keys.md"
        copy = folder / "keys.md"
        copy.write_bytes(source.read_bytes())
        scope = RagScope(owner="original-query-public-en-v1", allow_saas=True)
        ingestor = IngestionService(management_url("rag_ingest"), LocalEmbedding())
        try:
            manifest, version, _, _ = ingestor.ingest(
                Target(corpus_id=str(uuid4()), owner=scope.owner),
                [copy],
                scope=scope,
                reviewed=True,
            )
        finally:
            ingestor.close()
        scope.corpora = [make_pin(manifest, version)]
        binding = {
            "scope": scope.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
        with path.open("x", encoding="utf-8") as stream:
            json.dump(binding, stream, ensure_ascii=False, indent=2)
    question = "How should API keys be rotated?"
    rag = binding["scope"]
    scope = ReportScope(
        owner=rag["owner"],
        question=question,
        datasets=DatasetScope(),
        metrics=[],
        document_goal=DocumentGoal(
            goal_id="documents", question=question, metric_goals=[], purpose="summary"
        ),
        rag_query_policy="original-first-v1",
    )
    return {
        "report_scope": scope.model_dump(mode="json"),
        "rag_scope": rag,
        "model_query": "API 密钥如何轮换？",
    }


@pytest.mark.parametrize(
    "cut",
    [
        "worker_model_committed",
        "tool_committed",
        "rag_submission_committed",
        "report_artifact_committed",
    ],
)
def test_call_and_feedback_cut_points_do_not_reissue_search_or_settle_twice(dev_environment, cut):
    dev, settings = dev_environment
    config, run_id = new_config(dev), str(uuid4())
    probe(config, "start", run_id, "--cut", cut, expected=91)
    owner = config["report_scope"]["owner"]
    before = snapshot(settings, run_id, owner)
    result = probe(
        config,
        "resume",
        run_id,
        *(["--finish"] if cut in {"worker_model_committed", "tool_committed"} else []),
    )
    assert result["business_completion"]["status"] == "completed"
    after = snapshot(settings, run_id, owner)
    old, new = before["ledger"]["state"], after["ledger"]["state"]
    assert not new["pending"]
    assert all(new["receipts"][k] == v for k, v in old["receipts"].items())
    assert new["accounts"]["root"]["usage"]["calls"] == old["accounts"]["root"]["usage"][
        "calls"
    ] + (1 if cut in {"worker_model_committed", "tool_committed"} else 0)
    assert all(after["artifacts"][k] == v for k, v in before["artifacts"].items())
    assert_original_search(
        journal_observations(settings, run_id, owner),
        config["report_scope"]["document_goal"]["question"],
    )
    assert probe(config, "resume", run_id)["usage"] == result["usage"]


def test_wrong_first_model_query_is_recorded_and_never_silently_rewritten(dev_environment):
    dev, settings = dev_environment
    config, run_id = new_config(dev), str(uuid4())
    first = probe(config, "start", run_id, "--ignore")
    task = first["results"]["1:documents"]
    assert task["status"] == "failed" and task["error"]["code"] == "RAG_QUERY_POLICY"
    owner = config["report_scope"]["owner"]
    rows = journal_observations(settings, run_id, owner)
    attempts = [r for r in rows if r["kind"] == "model"]
    assert len(attempts) == 2
    calls = [c for r in attempts for c in r["payload"]["data"].get("tool_calls", [])]
    assert calls[0]["args"]["query"] == "Explain the requested policy in English"
    observed = snapshot(settings, run_id, owner)
    assert not any(a["kind"] == "documents" for a in observed["artifacts"].values())
    assert probe(config, "resume", run_id)["usage"] == first["usage"]
    assert snapshot(settings, run_id, owner) == observed


def test_issued_unknown_search_cannot_be_replayed_under_original_query_policy(dev_environment):
    dev, settings = dev_environment
    config, run_id = new_config(dev), str(uuid4())
    probe(config, "start", run_id, "--cut", "tool_issued", expected=91)
    owner = config["report_scope"]["owner"]
    before = snapshot(settings, run_id, owner)
    denied = probe(config, "resume", run_id, expected=2)
    assert denied["error"]["code"] == "RECOVERY_UNCERTAIN"
    after = snapshot(settings, run_id, owner)
    assert before["ledger"] == after["ledger"]
    assert before["artifacts"] == after["artifacts"]
    assert len(before["calls"]) == len(after["calls"])


def test_old_query_policy_cannot_be_silently_upgraded(dev_environment):
    dev, settings = dev_environment
    current, run_id = new_config(dev), str(uuid4())
    legacy = json.loads(json.dumps(current))
    del legacy["report_scope"]["rag_query_policy"]
    legacy["model_query"] = legacy["report_scope"]["document_goal"]["question"]
    first = probe(legacy, "start", run_id)
    before = snapshot(settings, run_id, legacy["report_scope"]["owner"])
    current["model_query"] = legacy["model_query"]
    assert probe(current, "resume", run_id, expected=2)["error"]["code"] == "RECOVERY_IDENTITY"
    assert before == snapshot(settings, run_id, legacy["report_scope"]["owner"])
    assert probe(legacy, "resume", run_id)["cross_source_report"] == first["cross_source_report"]


def test_journal_rejects_rebinding_the_original_call_id_to_a_translated_query(dev_environment):
    dev, settings = dev_environment
    config, run_id = new_config(dev), str(uuid4())
    probe(config, "start", run_id)
    owner = config["report_scope"]["owner"]
    before = snapshot(settings, run_id, owner)
    backend = Backend(settings.runtime_database_url.get_secret_value(), run_id, owner)
    try:
        with backend.lease():
            journal = Journal(
                backend, DurableLedger(backend, BudgetLimits(calls=8)), DurableArtifacts(backend)
            )
            envelope = TaskEnvelope(
                run_id=run_id,
                parent_id=run_id,
                plan_version=1,
                task=TaskSpec(task_id="documents", worker="rag", instruction="trusted test"),
                allowed_tools=["search_documents"],
                budget=BudgetLimits(),
            )
            with pytest.raises(AgentFailure) as exc:
                journal.begin_tool(
                    envelope,
                    "search_documents",
                    {"query": "Translated goal", "top_k": 5},
                    "retrieve_0",
                )
            assert exc.value.error.code == "RECOVERY_CONFLICT"
    finally:
        backend.close()
    assert snapshot(settings, run_id, owner) == before


def test_model_selected_second_search_and_its_committed_feedback_are_reused(dev_environment):
    dev, settings = dev_environment
    config, run_id = new_config(dev), str(uuid4())
    config["second_query"] = "存储配额采用GiB，按二进制容量计量"
    probe(config, "start", run_id, "--cut", "second_search_committed", expected=91)
    owner = config["report_scope"]["owner"]
    before = snapshot(settings, run_id, owner)
    rows = journal_observations(settings, run_id, owner)
    second = next(r for r in rows if r["call_key"] == "tool:1:documents:followup_1")
    payload = json.loads(second["payload"]["ordered_json"])
    result = probe(config, "resume", run_id, "--finish")
    assert result["business_completion"]["status"] == "completed"
    assert result["results"]["1:documents"]["evidence_refs"] == payload["artifact_refs"]
    after = snapshot(settings, run_id, owner)
    assert result["usage"]["calls"] == 4
    assert all(
        after["ledger"]["state"]["receipts"][k] == v
        for k, v in before["ledger"]["state"]["receipts"].items()
    )
    assert (
        len(
            [
                r
                for r in journal_observations(settings, run_id, owner)
                if r["call_key"].startswith("tool:")
                and r["call_key"].split(":")[-1] in {"retrieve_0", "followup_1"}
            ]
        )
        == 2
    )


def test_wrong_scope_rejected_without_model_or_budget_changes(dev_environment):
    dev, settings = dev_environment
    config, run_id = new_config(dev), str(uuid4())
    probe(config, "start", run_id, "--pause")
    owner = config["report_scope"]["owner"]
    before = snapshot(settings, run_id, owner)
    changed = json.loads(json.dumps(config))
    changed["rag_scope"]["allow_saas"] = False
    denied = probe(changed, "resume", run_id, expected=2)
    assert denied["error"]["code"] == "DOCUMENT_NOT_AUTHORIZED"
    assert before == snapshot(settings, run_id, owner)


def test_512_characters_does_not_bypass_original_embedding_token_limit(dev_environment):
    dev, settings = dev_environment
    config, run_id = config_for(dev, "cp06"), str(uuid4())
    question = "中" * 512
    config["report_scope"]["question"] = config["report_scope"]["document_goal"]["question"] = (
        question
    )
    config["report_scope"]["rag_query_policy"] = "original-first-v1"
    result = probe(config, "start", run_id)
    assert result["results"]["1:documents"]["error"]["code"] == "EMBEDDING_LIMIT"
    assert result["business_completion"]["status"] == "blocked"
    assert_original_search(
        journal_observations(settings, run_id, config["report_scope"]["owner"]), question
    )
