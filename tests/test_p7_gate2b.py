"""Public Toy contracts only. Never opens actual sealed Gold or a paid model."""

import copy
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return tuple(
        importlib.import_module(n)
        for n in (
            "p7_holdout_pack",
            "p7_business_runtime",
            "p7_business_scoring",
            "p7_gate2b",
        )
    )


@pytest.fixture
def case(modules):
    p, _, s, _ = modules
    from datapilot.ingestion.common import digest
    from datapilot.reporting.contracts import ReportScope

    value = {
        "case_id": "bh2-001",
        "lane": "sql_only",
        "objective": "public toy only",
        "question": "请计算公开 Toy 在 2031 年二月的已支付账单收入。",
        "owner": "toy",
        "datasets": {
            "bindings": [{"dataset_id": "11111111-1111-4111-8111-111111111111", "version": 1}]
        },
        "metrics": [
            {
                "goal_id": "revenue",
                "dataset_id": "11111111-1111-4111-8111-111111111111",
                "dataset_version": 1,
                "semantic_version": 1,
                "metric_id": "paid_invoice_revenue",
                "metric_version": 1,
                "window": {"start": "2031-02-01", "end_exclusive": "2031-03-01"},
            }
        ],
    }
    task = p.CaseInput.model_validate_json(json.dumps(value))
    gold = p.Gold(
        case_id=task.case_id,
        business_completion="completed",
        host_decision="review_then_run",
        metrics=[
            p.NumericGold(goal_id="revenue", disposition="verified", value="3.03", unit="CNY")
        ],
        refusal_conditions=[],
        causal_claim_must_remain_unverified=False,
    )
    scope = ReportScope(
        owner=task.owner, question=task.question, datasets=task.datasets, metrics=task.metrics
    )
    bridge = {
        "request": task.metrics[0].model_dump(mode="json"),
        "source_sha256": "a" * 64,
        "verdict": "verified",
        "verification": {"verdict": "verified", "verification_id": "toy-v"},
        "evidence_id": "toy-e",
        "value": {"value": "3.03", "unit": "CNY"},
    }
    payload = {
        "case_id": task.case_id,
        "question_sha256": digest(task.question),
        "manifest": {"cross_source_report": {"scope": scope.model_dump(mode="json")}},
        "snapshot": {
            "unknown": False,
            "next": False,
            "review": False,
            "report": {
                "claims": [
                    {"goal_id": "revenue", "kind": "metric", "metric": bridge, "documents": []}
                ],
                "business_completion": {"status": "completed", "unconfirmed_claims": []},
            },
        },
    }
    assert digest(scope) == digest(payload["manifest"]["cross_source_report"]["scope"])
    return task, gold, payload, b"k" * 32, {(task.metrics[0].dataset_id, 1): "a" * 64}


def test_gold_case_and_paid_key_cannot_enter_toy_runtime(modules):
    _, runtime, _, _ = modules
    for value in [
        {"phase": "gate2b_toy", "case_id": "bh2-001"},
        {"phase": "business_live", "case_id": "toy-one"},
        {
            "phase": "gate2b_toy",
            "case_id": "toy-one",
            "settings": {"llm_mode": "fake", "api_key": "not-a-real-key"},
        },
    ]:
        with pytest.raises(ValueError):
            runtime.configuration(json.dumps(value))


def test_collection_signature_and_hash_fail_closed(modules, case):
    _, _, s, _ = modules
    _, _, payload, key, _ = case
    record = s.sign_collection(payload, key)
    assert s.authenticated(record, key) == payload
    record["payload"]["snapshot"]["unknown"] = True
    with pytest.raises(ValueError, match="changed"):
        s.authenticated(record, key)
    with pytest.raises(ValueError):
        s.authenticated(s.sign_collection(payload, key), b"z" * 32)


@pytest.mark.parametrize(
    "mutation", [None, "unit", "source", "metric_version", "window", "verdict"]
)
def test_numeric_score_requires_exact_business_pins_and_not_raw_success(modules, case, mutation):
    _, _, s, _ = modules
    task, gold, payload, key, sources = case
    payload = copy.deepcopy(payload)
    bridge = payload["snapshot"]["report"]["claims"][0]["metric"]
    if mutation == "unit":
        bridge["value"]["unit"] = "USD"
    elif mutation == "source":
        bridge["source_sha256"] = "b" * 64
    elif mutation == "metric_version":
        bridge["request"]["metric_version"] = 2
    elif mutation == "window":
        bridge["request"]["window"]["end_exclusive"] = "2031-03-02"
    elif mutation == "verdict":
        bridge["verification"]["verdict"] = "unavailable"
    result = s.score_case(task, gold, s.sign_collection(payload, key), key, source_hashes=sources)
    assert result["strict_correct"] is (mutation is None)


@pytest.mark.parametrize("state", ["unknown", "next", "review"])
def test_incomplete_collection_cannot_be_scored_as_success(modules, case, state):
    _, _, s, _ = modules
    task, gold, payload, key, sources = case
    payload["snapshot"][state] = True
    result = s.score_case(task, gold, s.sign_collection(payload, key), key, source_hashes=sources)
    assert not result["strict_correct"]


def test_changed_goal_or_scope_cannot_reuse_a_valid_signed_collection(modules, case):
    _, _, s, _ = modules
    task, gold, payload, key, sources = case
    for field in ["question", "scope", "rag_scope"]:
        bad = copy.deepcopy(payload)
        if field == "question":
            bad["question_sha256"] = "c" * 64
        elif field == "scope":
            bad["manifest"]["cross_source_report"]["scope"]["metrics"][0]["metric_version"] = 9
        else:
            bad["manifest"]["rag_scope"] = {"owner": "another-owner"}
        with pytest.raises(ValueError):
            s.score_case(task, gold, s.sign_collection(bad, key), key, source_hashes=sources)


def test_ranking_and_empty_business_denominator_are_not_live_quality(modules, case):
    _, _, s, _ = modules
    assert s.rank_metrics(["a", "a", "b", "x"], ["b", "c"])["recall"] == 0.5
    assert s.rank_metrics([], [])["recall"] is None
    assert s.rank_metrics([], [])["precision"] == 0
    result = s.planned_summary([case[0]], {})
    assert result["planned_tasks"] == 1 and result["not_run"] == [case[0].case_id]
    assert result["live_success_rate"] is None


def test_unadjudicated_refusal_is_never_automatically_marked_correct(modules, case):
    _, _, s, _ = modules
    task, gold, payload, key, sources = case
    gold = gold.model_copy(update={"refusal_conditions": ["an_independent_reason"]})
    result = s.score_case(task, gold, s.sign_collection(payload, key), key, source_hashes=sources)
    assert not result["strict_correct"] and result["requires_human_adjudication"]


def test_actual_runner_canonical_question_hash_is_accepted_by_scorer(modules, case):
    from datapilot.ingestion.common import digest

    _, _, scoring, _ = modules
    task, gold, payload, key, sources = case
    payload["question_sha256"] = digest(task.question)
    result = scoring.score_case(
        task, gold, scoring.sign_collection(payload, key), key, source_hashes=sources
    )
    assert result["strict_correct"]


def test_environment_cannot_inherit_paid_credentials_or_another_database(
    modules, tmp_path, monkeypatch
):
    _, _, _, ops = modules
    monkeypatch.setattr(ops, "PRIVATE", tmp_path)
    monkeypatch.setenv("DATAPILOT_API_KEY", "not-a-real-secret")
    (tmp_path / "environment.json").write_text(
        json.dumps({"DATAPILOT_LLM_MODE": "fake", "DATAPILOT_API_KEY": ""})
    )
    assert ops.environment()["DATAPILOT_API_KEY"] == ""
    (tmp_path / "environment.json").write_text(
        json.dumps(
            {
                "DATAPILOT_READER_DATABASE_URL": "postgresql+psycopg://datapilot_reader:p@127.0.0.1:55432/demo"
            }
        )
    )
    with pytest.raises(ValueError, match="escaped"):
        ops.environment()
