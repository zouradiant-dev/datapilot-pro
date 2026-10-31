"""P7-only preparation contracts and independent protocol counterexamples, never Live."""

import copy
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from p7_business_scoring import sign_collection
from v3_common import BASE, BUDGET, ROOT, infrastructure
from v3_gate import ordinary_failure_may_continue, permit_valid
from v3_oracle import query
from v3_prepare import build_cases
from v3_probe import ProbeAnswer, ProbeCase
from v3_score import score
from v3_sources import write_sources
from v3_worker import execute as worker

from datapilot.contracts import AgentFailure
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.persistence.backend import Backend, DurableLedger
from datapilot.tools.sql import SQLPolicy, validate_sql


@pytest.fixture
def pins():
    return json.loads((BASE / "bindings-v2.json").read_bytes())


def test_sixty_unique_targets_and_lanes_without_model_execution(pins):
    from collections import Counter

    tasks, golds, _ = build_cases(pins)
    assert len(tasks) == len(golds) == 60
    assert Counter(t.lane for t in tasks) == {"sql_only": 20, "rag_only": 20, "sql_rag": 20}
    assert len({t.question for t in tasks}) == len({t.case_id for t in tasks}) == 60
    assert sum(g.host_code is not None for g in golds) == 6


def test_no_boolean_or_size_escape_in_partition_budget():
    assert sum(BUDGET["partition_runtime_counts"]) == 54
    assert sum(BUDGET["partition_tokens"]) == 54 * 18000 == 972000
    assert BUDGET["provider_attempts"] == 54 * 8
    for calls, tokens in zip(
        BUDGET["partition_runtime_counts"], BUDGET["partition_tokens"], strict=True
    ):
        BudgetLimits(calls=calls, tokens=tokens)


def test_sources_reproduce_exact_bytes_and_refuse_silent_overwrite(tmp_path):
    write_sources(tmp_path)
    first = {
        f.relative_to(tmp_path).as_posix(): f.read_bytes()
        for f in tmp_path.rglob("*")
        if f.is_file()
    }
    write_sources(tmp_path)
    assert first == {
        f.relative_to(tmp_path).as_posix(): f.read_bytes()
        for f in tmp_path.rglob("*")
        if f.is_file()
    }
    (tmp_path / "master.xlsx").write_bytes(b"changed")
    with pytest.raises(ValueError):
        write_sources(tmp_path)


def test_all_independent_oracle_sql_stays_in_original_ast_allowlist(pins):
    tasks, answers, specs = build_cases(pins)
    for task, gold in zip(tasks, answers, strict=True):
        for spec, expected in zip(specs[task.case_id], gold.metrics, strict=True):
            if expected.disposition != "verified":
                continue
            schema = pins["datasets"][spec[0]]["schema"]
            validate_sql(
                query(*spec, schema),
                SQLPolicy("uploads", frozenset(t["physical_name"] for t in schema["tables"])),
            )


def example_permit():
    binding = {
        "campaign_id": "synthetic-authorization-contract-only",
        "implementation_sha256": "a" * 64,
    }
    value = {
        "kind": "p7-business-v3-one-campaign-permit-1",
        "authorized": True,
        "approved_by_role": "project_owner",
        "source_user_authorization_ref": "test-only-not-approval",
        "approve_bound_runs": True,
        **binding,
        "cases": 60,
        "runtime_runs": 54,
        "model_attempts": 432,
        "token_units": 972000,
        "root_calls": 8,
        "root_tokens": 18000,
        "child_calls": 4,
        "child_tokens": 18000,
        "output_tokens": 1200,
        "concurrency": 1,
        "automatic_retries": 0,
        "task_timeout_seconds": 180,
        "campaign_timeout_seconds": 10800,
        "provider": "deepseek",
        "model": "deepseek-flash",
        "thinking": "disabled",
        "base_url": "https://api.deepseek.com",
        "estimated_usd_cap": "1.1664",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    return value, binding


@pytest.mark.parametrize(
    "field",
    [
        "cases",
        "runtime_runs",
        "model_attempts",
        "token_units",
        "concurrency",
        "automatic_retries",
        "root_calls",
        "output_tokens",
    ],
)
def test_pending_or_boolean_budget_is_never_authority(field):
    permit, binding = example_permit()
    permit[field] = True
    with pytest.raises(ValueError):
        permit_valid(permit, binding)


@pytest.mark.parametrize(
    "field",
    [
        "authorized",
        "approve_bound_runs",
        "implementation_sha256",
        "model",
        "estimated_usd_cap",
        "expires_at",
    ],
)
def test_wrong_identity_expiry_and_old_authorization_are_rejected(field):
    permit, binding = example_permit()
    permit[field] = False if field in {"authorized", "approve_bound_runs"} else "invalid"
    with pytest.raises((ValueError, TypeError)):
        permit_valid(permit, binding)


@pytest.mark.asyncio
async def test_fake_cannot_impersonate_any_formal_case_before_settings(monkeypatch):
    import v3_worker

    monkeypatch.setattr(
        v3_worker, "Settings", lambda **_: pytest.fail("Settings constructed for forbidden Fake")
    )
    with pytest.raises(ValueError):
        await worker(
            {"synthetic_probe": True, "case_id": "p7-holdout-v3-001"}, "fake", "start", None
        )


@pytest.mark.asyncio
async def test_pending_live_fails_before_credentials_or_runtime(monkeypatch):
    import v3_worker

    monkeypatch.setattr(
        v3_worker, "Settings", lambda **_: pytest.fail("No paid credential/SDK construction")
    )
    with pytest.raises(ValueError):
        await worker({"authorization_binding": {}}, "live", "start", {})


def test_protocol_b_preserves_business_failure_but_stops_unknown_and_budget():
    result = {"strict_correct": False, "failure_class": "business_or_evidence_mismatch"}
    payload = {"snapshot": {"unknown": False, "state": {"results": {}}}, "calls": []}
    assert ordinary_failure_may_continue(result, payload)
    payload["snapshot"]["unknown"] = True
    assert not ordinary_failure_may_continue(result, payload)
    payload["snapshot"]["unknown"] = False
    payload["snapshot"]["state"]["error"] = {"code": "BUDGET_EXCEEDED"}
    assert not ordinary_failure_may_continue(result, payload)


def test_evidence_integrity_failure_always_stops_even_with_known_usage():
    assert not ordinary_failure_may_continue(
        {"dimensions": {"evidence": False}},
        {"snapshot": {"unknown": False, "state": {}}, "calls": []},
    )


def test_full_run_reservation_and_unknown_usage_keep_original_ledger_semantics():
    ledger = BudgetLedger(BudgetLimits(calls=5, tokens=90000))
    tickets = [ledger.reserve_batch("root", [(0, 18000)])[0] for _ in range(5)]
    with pytest.raises(AgentFailure):
        ledger.reserve_batch("root", [(0, 18000)])
    ledger.settle(tickets[0], None)
    assert ledger.snapshot().total_tokens == 90000 and not ledger.snapshot().usage_complete
    with pytest.raises(AgentFailure):
        ledger.settle(tickets[0], 0)


def probe_fixture(kind):
    root = BASE / "private/probe"
    fixtures = json.loads((root / "fixtures.json").read_bytes())
    task_raw, gold_raw = next(
        (t, g) for t, g in fixtures["cases"] if t["case_id"] == "probe-v3-" + kind
    )
    task = ProbeCase.model_validate_json(json.dumps(task_raw))
    gold = ProbeAnswer.model_validate_json(json.dumps(gold_raw))
    payload = json.loads((root / task.case_id / "collection.json").read_bytes())
    key = b"protocol-probe-collector-key-not-live"
    return task, gold, payload, key, fixtures["pins"]


@pytest.fixture(params=["completed", "partial", "unavailable"])
def probe(request):
    return probe_fixture(request.param)


def evaluate(probe, mutate=None):
    task, gold, payload, key, pins = copy.deepcopy(probe)
    if mutate:
        mutate(payload)
    return score(task, gold, sign_collection(payload, key), key, pins)


@pytest.mark.parametrize(
    "field", ["unit", "value", "metric_version", "semantic_hash", "verification_id"]
)
def test_report_cannot_replace_original_p3_metric_bridge(field):
    def change(payload):
        bridge = next(
            c["metric"] for c in payload["snapshot"]["report"]["claims"] if c["kind"] == "metric"
        )
        if field == "unit":
            bridge["value"]["unit"] = "USD"
        elif field == "value":
            bridge["value"]["value"] = "999.91"
        elif field == "metric_version":
            bridge["request"]["metric_version"] = 999
        elif field == "semantic_hash":
            bridge["context"]["semantic_sha256"] = "a" * 64
        else:
            bridge["verification"]["verification_id"] = str(uuid4())

    assert not evaluate(probe_fixture("completed"), change)["strict_correct"]


def test_all_three_completion_states_score_from_real_pg_fake_probe(probe):
    assert evaluate(probe)["strict_correct"]


def test_unsigned_payload_change_is_not_trusted(probe):
    task, gold, payload, key, pins = probe
    signed = sign_collection(payload, key)
    signed["payload"] = copy.deepcopy(payload)
    signed["payload"]["case_id"] = "forged"
    with pytest.raises(ValueError):
        score(task, gold, signed, key, pins)


def test_wrong_citation_hash_cannot_pass(probe):
    def change(payload):
        document = next(d for c in payload["snapshot"]["report"]["claims"] for d in c["documents"])
        document["citation"]["sha256"] = "a" * 64

    assert not evaluate(probe, change)["strict_correct"]


def test_missing_receipt_or_forged_succeeded_cannot_pass(probe):
    def change(payload):
        version = payload["snapshot"]["state"]["plan_version"]
        payload["snapshot"]["state"]["results"][f"{version}:documents"]["rag_completion"] = None

    try:
        result = evaluate(probe, change)
    except ValueError:
        return
    assert not result["strict_correct"]


def test_missing_fact_cannot_be_promoted_to_completed(probe):
    if probe[1].business_completion == "completed":
        return

    def change(payload):
        bc = payload["snapshot"]["report"]["business_completion"]
        bc["status"] = "completed"
        bc["verified_goals"] = bc["required_goals"]
        bc["missing_evidence"] = {}

    assert not evaluate(probe, change)["strict_correct"]


def test_wrong_provider_usage_or_model_payload_fails_closed(probe):
    def change(payload):
        row = next(c for c in payload["calls"] if c["kind"] == "model")
        row["payload_hash"] = "b" * 64

    assert not evaluate(probe, change)["strict_correct"]


def test_planned_denominator_does_not_drop_not_run(pins):
    from p7_business_scoring import planned_summary

    tasks, _, _ = build_cases(pins)
    result = planned_summary(tasks, {tasks[0].case_id: {"strict_correct": True}})
    assert result["planned_tasks"] == 60 and len(result["not_run"]) == 59


def test_aggregation_retains_sixty_and_no_zero_observation_rates(pins):
    from v3_score import aggregate

    tasks, golds, _ = build_cases(pins)
    empty = aggregate(tasks, golds, {})
    assert empty["all"]["strict_over_observed"] is None and len(empty["not_run"]) == 60
    one = aggregate(
        tasks, golds, {tasks[0].case_id: {"strict_correct": False, "status": "blocked"}}
    )
    assert one["all"]["observed"] == 1 and one["all"]["planned"] == 60 and len(one["not_run"]) == 59


@pytest.mark.asyncio
async def test_fingerprint_uses_confirmed_dataset_version_instead_of_assuming_one(
    pins, monkeypatch
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import v3_seal

    seen = []

    class Tools:
        async def execute(self, dataset_id, sql):
            table = next(
                t
                for t in pins["datasets"]["future"]["schema"]["tables"]
                if t["physical_name"] in sql
            )
            return SimpleNamespace(
                result=SimpleNamespace(truncated=False, row_count=table["row_count"]),
                result_sha256="a" * 64,
            )

    @asynccontextmanager
    async def session(settings, scope):
        seen.extend(b.version for b in scope.bindings)
        yield Tools()

    monkeypatch.setattr(v3_seal, "dataset_session", session)
    await v3_seal.versioned_snapshots(None, pins["datasets"]["future"])
    assert seen == [2]


def test_pg_budget_reopen_keeps_unknown_charge_and_blocks_duplicate_settlement():
    if os.environ.get("DATAPILOT_RUN_DB_TESTS") != "1":
        pytest.skip("Explicit isolated PG opt-in required")
    values = infrastructure(ROOT / "artifacts/p7/unified-regression/private/environment.json")
    run = str(uuid4())
    limits = BudgetLimits(calls=5, tokens=90000)
    backend = Backend(values["DATAPILOT_RUNTIME_DATABASE_URL"], run, "p7-v3-budget-probe")
    try:
        backend.register({"kind": "nonpaid-budget-probe"}, limits)
        with backend.lease():
            ledger = DurableLedger(backend, limits)
            ticket = ledger.reserve_batch("root", [(0, 18000)])[0]
            ledger.settle(ticket, None)
    finally:
        backend.close()
    backend = Backend(values["DATAPILOT_RUNTIME_DATABASE_URL"], run, "p7-v3-budget-probe")
    try:
        with backend.lease():
            ledger = DurableLedger(backend, limits)
            assert ledger.snapshot().total_tokens == 18000 and not ledger.snapshot().usage_complete
            with pytest.raises(AgentFailure):
                ledger.settle(ticket, 0)
    finally:
        backend.close()
