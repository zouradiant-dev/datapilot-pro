"""New Dev prep boundaries; no old Gold, candidate tuning, or paid transport."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from datapilot.contracts import AgentFailure
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.contracts import BudgetLimits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import p7_smoke_pack as pack  # noqa: E402
import p7_smoke_run as runner  # noqa: E402
from p7_smoke_worker import permit_valid  # noqa: E402


def permit():
    binding = {
        "freeze_sha": "a" * 64,
        "seal_sha": "b" * 64,
        "policy_sha": "c" * 64,
        "scopes": {"smoke-01": "d" * 64},
    }
    value = {
        "kind": "p7-dev-smoke-live-authorization-1",
        "authorized": True,
        "approved_by_role": "project_owner",
        "source_user_authorization_ref": "test-only",
        "freeze_sha256": binding["freeze_sha"],
        "case_seal_sha256": binding["seal_sha"],
        "budget_policy_sha256": binding["policy_sha"],
        "scope_hashes": binding["scopes"],
        "approve_bound_runs": True,
        "provider": "deepseek",
        "model": "deepseek-flash",
        "thinking": "disabled",
        "estimated_usd_cap": "0.108",
        "max_output_tokens": 1200,
        "task_timeout_seconds": 180,
        "campaign_timeout_seconds": 1800,
        "max_cases": 8,
        "runtime_runs": 7,
        "calls_per_run": 8,
        "tokens_per_run": 18000,
        "campaign_model_calls": 56,
        "campaign_token_units": 90000,
        "concurrency": 1,
        "automatic_retries": 0,
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    return value, binding


def test_new_decimal_gold_is_not_a_replayed_demo_result():
    assert pack.independent_gold() == {
        "august_revenue": "191.34",
        "september_revenue": "398.77",
        "automation_usage": "24",
    }


def test_invalid_manifest_cannot_publish_an_empty_seal(tmp_path):
    target = tmp_path / "seal.json"
    with pytest.raises(TypeError):
        pack.write_new(target, {"invalid": object()})
    assert not target.exists()


def test_legacy_metric_claim_without_fact_field_does_not_crash_the_new_scorer():
    assert runner.coverage_counts(None, [{"kind": "metric"}]) == {
        "required": None,
        "verified": None,
        "missing_ids": [],
    }


def test_required_unproved_fact_is_counted_as_missing_not_zero_requirements():
    from types import SimpleNamespace

    goal = SimpleNamespace(required_facts=["one", "two"])
    assert runner.coverage_counts(goal, [{"fact_coverage": {"one": "a" * 64, "two": None}}]) == {
        "required": 2,
        "verified": 1,
        "missing_ids": ["two"],
    }


def test_source_generation_reuses_identical_bytes_and_refuses_changed_document(tmp_path):
    destination = tmp_path / "new-sources"
    pack.write_sources(destination)
    original = {f.name: pack.sha(f.read_bytes()) for f in destination.iterdir()}
    pack.write_sources(destination)
    assert original == {f.name: pack.sha(f.read_bytes()) for f in destination.iterdir()}
    (destination / "billing.md").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        pack.write_sources(destination)


def test_new_untracked_runtime_file_changes_the_exact_freeze_closure(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/model.py").write_text("pass\n")
    first = pack.runtime_files(tmp_path)
    (tmp_path / "src/hidden_override.py").write_text("raise RuntimeError()\n")
    assert pack.runtime_files(tmp_path) != first
    (tmp_path / ".env").write_text("DATAPILOT_API_KEY=never-freeze-me\n")
    assert ".env" not in pack.runtime_files(tmp_path)


@pytest.mark.parametrize(
    "field", ["freeze_sha256", "case_seal_sha256", "budget_policy_sha256", "scope_hashes"]
)
def test_changed_approval_identity_cannot_start_a_provider(field):
    value, binding = permit()
    value[field] = {} if field == "scope_hashes" else "0" * 64
    with pytest.raises(ValueError, match="authorization"):
        permit_valid(value, **binding)


@pytest.mark.parametrize("field", ["max_cases", "concurrency", "automatic_retries"])
def test_boolean_budget_or_retry_escalation_is_not_authority(field):
    value, binding = permit()
    value[field] = True
    with pytest.raises(ValueError, match="budget"):
        permit_valid(value, **binding)


def test_old_holdout_authorization_and_pending_template_are_rejected():
    value, binding = permit()
    for replacement in ["business-live-authorization", "pending"]:
        value["kind"] = replacement
        with pytest.raises(ValueError):
            permit_valid(value, **binding)
    value, binding = permit()
    value["authorized"] = False
    with pytest.raises(ValueError):
        permit_valid(value, **binding)


async def test_pending_live_authority_fails_before_settings_or_sdk(monkeypatch):
    import p7_smoke_worker as worker

    called = []
    monkeypatch.setattr(worker, "Settings", lambda **_: called.append(True))
    value, authority = permit()
    value["authorized"] = False
    with pytest.raises(ValueError, match="authorization"):
        await worker.main(
            {
                "schema_version": "p7-dev-smoke-launch-1",
                "case_id": "smoke-01",
                "authorization_binding": authority,
            },
            "live",
            "start",
            value,
        )
    assert called == []


def test_expired_or_naive_approval_cannot_be_reused():
    value, binding = permit()
    for date in ["2025-01-01T00:00:00+00:00", "2027-01-01T00:00:00"]:
        value["expires_at"] = date
        with pytest.raises(ValueError, match="expired"):
            permit_valid(value, **binding)


@pytest.mark.parametrize(
    "code,expected",
    [
        ("MODEL_TIMEOUT", "provider_failure"),
        ("MODEL_OUTPUT_INVALID", "model_reasoning"),
        ("BUDGET_EXCEEDED", "budget_exceeded"),
        ("DOCUMENT_NOT_AUTHORIZED", "permission_denied"),
    ],
)
def test_diagnostic_classes_use_original_structured_codes(code, expected):
    payload = {
        "snapshot": {"unknown": False, "state": {"results": {"1:t": {"error": {"code": code}}}}}
    }
    assert runner.failure_class(payload) == expected
    payload["snapshot"]["unknown"] = True
    assert runner.failure_class(payload) == "unknown_outcome"


def test_whole_run_admission_stops_before_exceeding_global_tokens():
    ledger = BudgetLedger(BudgetLimits(calls=7, tokens=90000))
    for _ in range(5):
        runner.reserve_case(ledger)
    with pytest.raises(AgentFailure, match="budget"):
        runner.reserve_case(ledger)
    assert ledger.snapshot().total_tokens == 90000
    assert ledger.snapshot().calls == 5  # Whole-Run slots, never mislabeled provider calls.


def test_unknown_dispatch_keeps_full_reservation_and_cannot_refund_as_zero():
    ledger = BudgetLedger(BudgetLimits(calls=7, tokens=90000))
    ticket = runner.reserve_case(ledger)
    ledger.settle(ticket, None)
    assert ledger.snapshot().total_tokens == 18000
    assert not ledger.snapshot().usage_complete
    with pytest.raises(AgentFailure):
        ledger.release_unissued(ticket)


def test_user_stop_terminates_only_the_new_candidate_and_never_retries(tmp_path, monkeypatch):
    import subprocess

    class Pending:
        returncode = None
        killed = False

        def communicate(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("synthetic", timeout)
            return b"", b""

        def poll(self):
            return 0 if self.killed else None

        def kill(self):
            self.killed = True

    process, stopped = Pending(), []
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(runner.subprocess, "run", lambda args, **_: stopped.append(args))
    stop = tmp_path / "STOP"
    stop.touch()
    with pytest.raises(TimeoutError, match="uncertain"):
        runner.checked_process(
            ["unused"],
            env={},
            name="new-smoke-contract-only",
            deadline=1000000000000,
            stop_path=stop,
        )
    assert process.killed and len(stopped) == 1
    assert stopped[0][-1] == "new-smoke-contract-only"


async def test_permission_negative_performs_metadata_only_not_table_fingerprints(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    touched = []

    async def fingerprint(*_):
        touched.append("business_query")

    async def schema(_):
        return SimpleNamespace(source_sha256="a" * 64)

    @asynccontextmanager
    async def dataset(*_):
        yield SimpleNamespace(schema=schema)

    @asynccontextmanager
    async def forbidden(*_):
        raise AgentFailure("DOCUMENT_NOT_AUTHORIZED", "Synthetic scope not delegated")
        yield  # pragma: no cover - required only for the async context manager protocol

    monkeypatch.setattr(runner, "settings_for", lambda _: None)
    monkeypatch.setattr(runner, "table_snapshots", fingerprint)
    monkeypatch.setattr(runner, "dataset_session", dataset)
    monkeypatch.setattr(runner, "rag_session", forbidden)
    task = SimpleNamespace(
        preflight_rejection="DOCUMENT_NOT_AUTHORIZED", datasets=None, metrics=[], rag_scope=object()
    )
    assert (
        await runner.preflight(
            task, {"schema": {"dataset_id": "new", "source_sha256": "a" * 64}}, {}, {}
        )
        == "DOCUMENT_NOT_AUTHORIZED"
    )
    assert touched == []


def test_exact_known_settlement_allows_remaining_cases_without_raising_run_limits():
    ledger = BudgetLedger(BudgetLimits(calls=7, tokens=90000))
    for _ in range(7):
        ledger.settle(runner.reserve_case(ledger), 1500)
    with pytest.raises(AgentFailure):
        runner.reserve_case(ledger)
    assert ledger.snapshot().total_tokens == 10500
    assert pack.POLICY["campaign_model_calls"] == 7 * pack.PROFILE["max_model_calls"]
    assert pack.PROFILE["max_worker_turns"] == 4


@pytest.mark.parametrize("mutation", ["source", "protocol", "snapshot_extra"])
def test_changed_manifest_and_unregistered_files_fail_before_execution(
    tmp_path, monkeypatch, mutation
):
    source = tmp_path / "source.py"
    source.write_text("original\n")
    frozen = tmp_path / "private/frozen-source"
    frozen.mkdir(parents=True)
    (frozen / "source.py").write_bytes(source.read_bytes())
    manifest = {
        "files": {"source.py": pack.sha(source.read_bytes())},
        "case_seal_sha256": "seal",
        "source_snapshot": "frozen-source",
        "evaluation_seal_path": "private/evaluator-seal-v1.json",
    }
    for file, field in [
        ("evaluation-protocol-v1.json", "evaluation_protocol_sha256"),
        ("evaluator-seal-v1.json", "evaluation_seal_sha256"),
    ]:
        pack.write_new(tmp_path / "private" / file, {"immutable": True})
        manifest[field] = pack.sha((tmp_path / "private" / file).read_bytes())
    pack.write_new(tmp_path / "manifest.json", manifest)
    pack.write_new(
        tmp_path / "anchor.json",
        {
            "manifest_path": "manifest.json",
            "manifest_sha256": pack.sha((tmp_path / "manifest.json").read_bytes()),
        },
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "BASE", tmp_path / "private")
    monkeypatch.setattr(runner, "ANCHOR", tmp_path / "anchor.json")
    monkeypatch.setattr(runner, "runtime_files", lambda: manifest["files"])
    monkeypatch.setattr(runner, "load_pack", lambda: ([], {}, {"seal_sha256": "seal"}))
    runner.verify_freeze()
    if mutation == "source":
        source.write_text("changed\n")
    elif mutation == "protocol":
        (tmp_path / "private/evaluation-protocol-v1.json").write_text("changed")
    else:
        (frozen / "hidden.py").write_text("changed")
    with pytest.raises(ValueError, match="FREEZE_INVALIDATED"):
        runner.verify_freeze()


@pytest.mark.integration
def test_original_durable_campaign_ledger_survives_process_reopen(portable_pg):
    from datapilot.persistence.backend import Backend, DurableLedger

    url = portable_pg.runtime_database_url.get_secret_value()
    identity = str(uuid4())
    limits = BudgetLimits(calls=7, tokens=90000)
    backend = Backend(url, identity, "smoke-budget-contract")
    backend.register({"purpose": "public synthetic budget counterexample"}, limits)
    try:
        ledger = DurableLedger(backend, limits)
        ledger.settle(runner.reserve_case(ledger), None)
    finally:
        backend.close()
    reopened = Backend(url, identity, "smoke-budget-contract")
    try:
        state = DurableLedger(reopened, limits).snapshot()
        assert state.calls == 1 and state.total_tokens == 18000 and not state.usage_complete
    finally:
        reopened.close()
