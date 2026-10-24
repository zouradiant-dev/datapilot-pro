"""Receipt arithmetic counterexamples; no Holdout, database or model calls."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def reporter(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "gate2_reporter", scripts / "summarize_p7_gate2.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def example():
    return {
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_token_details": {"cache_read": 4},
        },
        "provider_token_usage": {"prompt_cache_miss_tokens": 6},
    }


def test_price_estimate_is_exact_decimal_and_reported_miss_is_separate(reporter):
    totals = reporter.provider_totals([example()])
    assert totals["cache_miss_reported"] == totals["cache_miss_derived"] == 6
    assert (
        reporter.estimated_cost(
            totals,
            {"input_cache_hit_usd": ".003", "input_cache_miss_usd": ".15", "output_usd": ".6"},
        )
        == "0.000003912"
    )


def test_unknown_usage_cannot_be_reported_as_zero_cost(reporter):
    totals = reporter.provider_totals([{"usage": None}])
    assert all(v is None for v in totals.values())
    assert reporter.estimated_cost(totals, {}) is None


@pytest.mark.parametrize("field,value", [("total_tokens", 14), ("input_tokens", 9)])
def test_conflicting_provider_counts_rejected(reporter, field, value):
    call = example()
    call["usage"][field] = value
    with pytest.raises(ValueError, match="disagree"):
        reporter.provider_totals([call])


def test_reported_cache_miss_unknown_does_not_masquerade_as_provider_data(reporter):
    call = example()
    call.pop("provider_token_usage")
    totals = reporter.provider_totals([call])
    assert totals["cache_miss_derived"] == 6 and totals["cache_miss_reported"] is None


def test_reported_cache_miss_must_match_total_input(reporter):
    call = example()
    call["provider_token_usage"]["prompt_cache_miss_tokens"] = 99
    with pytest.raises(ValueError, match="cache hit/miss"):
        reporter.provider_totals([call])


def test_report_output_path_is_separate_from_task_jsonl(reporter, tmp_path, monkeypatch):
    """A report run must not try to overwrite its final strategy observation file."""
    from datapilot.evaluation import IntentObservation

    private = tmp_path / "private"
    private.mkdir()
    docs = tmp_path / "docs/research"
    docs.mkdir(parents=True)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "approved_at": "2026-10-24T00:00:00+00:00",
                "total_max_calls": 118,
                "total_max_tokens": 750000,
                "source_commit": "synthetic-contract-only",
            }
        )
    )
    (docs / "p7-gate2-pricing.json").write_text(
        json.dumps(
            {
                "input_cache_hit_usd": ".003",
                "input_cache_miss_usd": ".15",
                "output_usd": ".6",
            }
        )
    )
    (private / "template-overlap.json").write_text("{}")
    (private / "bad-case-analysis.json").write_text("[]")
    gold = {"action": "clarify", "metrics": [], "documents": False}
    case = {"case_id": "synthetic-only", "expected": gold, "category": "contract"}
    for strategy in ("rule_only", "llm_only", "hybrid"):
        observation = IntentObservation.model_validate_json(
            json.dumps(
                {
                    "case_id": case["case_id"],
                    "expected": gold,
                    "actual": gold,
                    "strategy": strategy,
                    "transport": "none" if strategy == "rule_only" else "mock",
                    "elapsed_ms": 1,
                }
            )
        )
        filename = "rule-only.json" if strategy == "rule_only" else f"{strategy}-batch-0.json"
        (private / filename).write_text(
            json.dumps({"observations": [observation.model_dump(mode="json")]})
        )
    monkeypatch.setattr(reporter, "ROOT", tmp_path)
    monkeypatch.setattr(reporter, "BASE", private)
    monkeypatch.setattr(reporter, "PLAN", plan_path)
    monkeypatch.setattr(reporter, "BATCH_SIZES", (1,))
    monkeypatch.setattr(reporter, "load_cases", lambda plan: [case])
    monkeypatch.setattr(
        reporter, "inspect", lambda: {"Config": {"Image": "Mock"}, "HostConfig": {}}
    )
    monkeypatch.setattr(reporter, "environment", dict)
    monkeypatch.setattr(reporter, "Settings", lambda **kwargs: object())
    monkeypatch.setattr(reporter, "audit_batch", lambda *args: ([], {}))
    destination = docs / "explicit-report.json"
    reporter.main(destination)
    assert (
        json.loads(destination.read_text())["status"]
        == "intent_holdout_completed_business_e2e_not_run"
    )
    assert (private / "hybrid-observations.jsonl").exists()
