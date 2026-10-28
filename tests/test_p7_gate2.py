"""Gate 2 harness counterexamples; synthetic cases, never the sealed Holdout or Live."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from datapilot.evaluation import IntentGold, IntentObservation

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def harness(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "gate2_measurement", ROOT / "scripts/evaluate_gate2.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


@pytest.fixture
def plan(tmp_path):
    (tmp_path / "candidate.py").write_bytes(b"frozen\n")
    return {
        "phase": "p7-gate2-intent",
        "holdout_authorized": True,
        "batch_sizes": [12, 12, 12, 12, 11],
        "strategies": ["llm_only", "hybrid"],
        "total_max_calls": 118,
        "total_max_tokens": 750000,
        "files": {"candidate.py": hashlib.sha256(b"frozen\n").hexdigest()},
        "live_allowed": False,
        "live_approval_status": "pending",
    }


def test_offline_permission_does_not_authorize_a_paid_call(harness, plan):
    harness.check_plan(plan)
    with pytest.raises(ValueError, match="paid Holdout approval"):
        harness.check_plan(plan, live=True)
    plan.update(live_allowed=True, live_approval_status="explicit_human_approved")
    with pytest.raises(ValueError, match="paid Holdout approval"):
        harness.check_plan(plan, live=True)
    plan["live_approval_text"] = "synthetic explicit bounded approval"
    harness.check_plan(plan, live=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("phase", "p7-gate1-dev"),
        ("holdout_authorized", False),
        ("batch_sizes", [59]),
        ("strategies", ["hybrid"]),
        ("total_max_calls", 119),
        ("total_max_tokens", 750001),
    ],
)
def test_reject_unauthorized_phase_selection_or_budget_changes(harness, plan, field, value):
    plan[field] = value
    with pytest.raises(ValueError):
        harness.check_plan(plan)


def test_candidate_changed_after_freeze_is_rejected(harness, plan, tmp_path):
    (tmp_path / "candidate.py").write_text("tuned after Holdout\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen candidate"):
        harness.check_plan(plan)


async def test_paid_denial_precedes_gold_database_or_model_access(harness, plan, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unauthorized Live touched Holdout or database")

    monkeypatch.setattr(harness, "load_cases", forbidden)
    monkeypatch.setattr(harness, "inspect", forbidden)
    monkeypatch.setattr(harness, "live_transport", forbidden)
    with pytest.raises(ValueError, match="paid Holdout approval"):
        await harness.live_batch(plan, "llm_only", 0)


def test_partial_batch_keeps_planned_denominator_and_unknown_usage(harness):
    observed = IntentObservation(
        case_id="synthetic-only",
        strategy="llm_only",
        transport="mock",
        expected=IntentGold(action="clarify"),
        actual=IntentGold(action="clarify"),
        elapsed_ms=2,
        reported_tokens=None,
    )
    result = harness.summarize([observed], 12)
    assert result["observed_only"]["intent_exact_match"]["denominator"] == 1
    assert result["planned_denominator_exact_match"]["denominator"] == 12
    assert result["not_run_tasks"] == 11 and not result["all_planned_tasks_observed"]
    assert result["observed_only"]["reported_tokens"] is None
    assert result["agent_execution"] == result["evidence_verification"] == "not_run"
    assert not result["observed_only"]["live_quality_evidence"]


def test_observer_refuses_to_overwrite_original_attempt(harness, tmp_path):
    destination = tmp_path / "observations.json"
    harness.save(destination, {"original": True}, first=True)
    with pytest.raises(FileExistsError):
        harness.save(destination, {"original": False}, first=True)
    assert json.loads(destination.read_text(encoding="utf-8")) == {"original": True}


def test_later_batches_cannot_skip_or_continue_after_a_failed_attempt(
    harness, tmp_path, monkeypatch
):
    monkeypatch.setattr(harness, "BASE", tmp_path)
    harness.check_order("llm_only", 0)
    with pytest.raises(ValueError, match="order"):
        harness.check_order("llm_only", 1)
    first = tmp_path / "llm_only-batch-0.json"
    first.write_text(json.dumps({"complete": False, "error_code": "RECOVERY_UNCERTAIN"}))
    with pytest.raises(ValueError, match="Earlier batch stopped"):
        harness.check_order("llm_only", 1)
    first.write_text(json.dumps({"complete": True, "error_code": None}))
    harness.check_order("llm_only", 1)


def test_holdout_hash_checked_before_json_is_decoded(harness, plan, tmp_path):
    docs = tmp_path / "docs/research"
    docs.mkdir(parents=True)
    raw = tmp_path / "private.jsonl"
    raw.write_text("not JSON", encoding="utf-8")
    (docs / "p7-intent-corpus-manifest.json").write_text(
        json.dumps({"splits": {"holdout": {"path": "private.jsonl", "sha256": "0" * 64}}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Holdout bytes changed"):
        harness.load_cases(plan)


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("DATAPILOT_P7_ISOLATED") != "1",
    reason="Explicit isolated P7 PostgreSQL opt-in required",
)
@pytest.mark.parametrize("fail_transport", [False, True])
async def test_batch_real_isolated_journal_with_mock_never_paid(
    harness, plan, tmp_path, monkeypatch, fail_transport, portable_pg
):
    from langchain_core.messages import AIMessage
    from reporting_fixtures import validate_environment

    from datapilot.contracts import AgentFailure
    from datapilot.web.semantic_intent import IntentProposal

    # The shared fixture validates explicit test DB identity and designated roles.
    # Keep the original Mock transport, Journal/ledger and unknown-outcome assertions.
    mock_environment = dict(os.environ) | {
        "DATAPILOT_API_KEY": "synthetic-mock-only-not-a-provider-key",
        "DATAPILOT_MODEL": "deepseek-flash",
        "DATAPILOT_MODEL_PROVIDER": "deepseek",
        "DATAPILOT_BASE_URL": "https://api.deepseek.com",
    }
    for key, value in mock_environment.items():
        monkeypatch.setenv(key, value)
    # live_batch reloads its environment. Keep the same isolated DSNs and Mock-only
    # profile there as well; no operator credential or real HTTP transport is used.
    # portable_pg already checked the actual PG17/role; recheck the exact immutable
    # test environment at the old host guard boundary without needing a Docker socket.
    monkeypatch.setattr(harness, "inspect", lambda: validate_environment(mock_environment))
    monkeypatch.setattr(harness, "environment", lambda: dict(mock_environment))
    monkeypatch.setattr(harness, "BASE", tmp_path)
    plan.update(
        live_allowed=True,
        live_approval_status="explicit_human_approved",
        live_approval_text="Synthetic test only; all provider requests replaced by a Mock",
        campaign_id="contract-only-" + str(uuid4()),
        gateway_limits={
            "max_input_chars": 16000,
            "max_context_tokens": 18000,
            "model_timeout_seconds": 30.0,
        },
    )
    dataset = "7fe6d68b-7b61-57db-a695-88aadba18ce6"
    catalog = [
        {
            "schema": {"dataset_id": dataset, "version": 1},
            "metrics": [
                {
                    "dataset_id": dataset,
                    "dataset_version": 1,
                    "semantic_version": 1,
                    "metric_id": "paid_invoice_revenue",
                    "metric_version": 1,
                    "definition": {"currency": "CNY"},
                }
            ],
        }
    ]
    cases = []
    for number in range(59):
        question = f"2025年10月实收，合成用例 {number}"
        expected = IntentGold(
            action="candidate",
            metrics=[
                {
                    "dataset_id": dataset,
                    "dataset_version": 1,
                    "semantic_version": 1,
                    "metric_id": "paid_invoice_revenue",
                    "metric_version": 1,
                    "window": {"start": "2025-10-01", "end_exclusive": "2025-11-01"},
                    "as_of": None,
                }
            ],
        )
        cases.append(
            {
                "case_id": f"mock-only-{number}",
                "question": question,
                "selection": {},
                "datasets": catalog,
                "today": "2026-10-24",
                "previous": None,
                "expected": expected.model_dump(mode="json"),
            }
        )

    class MockTransport:
        calls = 0

        async def respond(self, messages, tools):
            self.calls += 1
            if fail_transport:
                raise TimeoutError("Synthetic network outcome is unknown")
            payload = json.loads(messages[-1].content)
            return AIMessage(
                content=IntentProposal(
                    question_sha256=payload["question_sha256"],
                    outcome="candidate",
                    metrics=[{"metric_id": "paid_invoice_revenue", "phrase": "实收"}],
                    periods=["2025年10月"],
                ).model_dump_json(),
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                    "input_token_details": {"cache_read": 0},
                },
            )

    transport = MockTransport()
    monkeypatch.setattr(harness, "load_cases", lambda _plan: cases)
    monkeypatch.setattr(harness, "live_transport", lambda _settings: transport)
    if fail_transport:
        with pytest.raises(AgentFailure):
            await harness.live_batch(plan, "llm_only", 0)
    else:
        await harness.live_batch(plan, "llm_only", 0)
    observed = json.loads((tmp_path / "llm_only-batch-0.json").read_text(encoding="utf-8"))
    assert observed["transport"] == "mock"
    assert not observed["summary"]["observed_only"]["live_quality_evidence"]
    if fail_transport:
        assert transport.calls == 1 and not observed["complete"]
        assert not observed["ledger"]["usage_complete"]
        assert observed["model_receipts"][0]["status"] == "uncertain"
        assert observed["summary"]["not_run_tasks"] == 11
        with pytest.raises(ValueError, match="Earlier batch stopped"):
            await harness.live_batch(plan, "llm_only", 1)
    else:
        assert transport.calls == 12 and observed["complete"]
        assert observed["ledger"]["reported_tokens"] == 180
        assert len(observed["model_receipts"]) == 12
        assert observed["summary"]["planned_denominator_exact_match"]["numerator"] == 12
        with pytest.raises(ValueError, match="already recorded"):
            await harness.live_batch(plan, "llm_only", 0)
        assert transport.calls == 12
