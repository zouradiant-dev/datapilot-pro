"""Public synthetic inputs only; no sealed Gold or live network call is read/executed."""

import copy
import importlib
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_cross_source_report import bridge_case as bridge_case
from test_semantics import semantic_case as semantic_case

from datapilot.ingestion.common import digest


@pytest.fixture
def campaign_modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return tuple(
        importlib.import_module(n)
        for n in ("p7_campaign", "p7_business_evaluator", "p7_holdout_pack", "p7_business_scoring")
    )


@pytest.fixture
def scored(campaign_modules, bridge_case):
    _, evaluator, pack, signing = campaign_modules
    service, bridge, artifacts = bridge_case
    service.scope.question += "；这是一条公开的独立契约测试问题。"
    scope = service.scope
    task = pack.CaseInput.model_validate_json(
        json.dumps(
            {
                "case_id": "bh2-001",
                "lane": "sql_only",
                "objective": "public test only",
                "question": scope.question,
                "owner": scope.owner,
                "datasets": scope.datasets.model_dump(mode="json"),
                "metrics": [m.model_dump(mode="json") for m in scope.metrics],
            }
        )
    )
    gold = pack.Gold(
        case_id=task.case_id,
        business_completion="completed",
        host_decision="review_then_run",
        metrics=[
            pack.NumericGold(
                goal_id=bridge.request.goal_id, disposition="verified", value="300", unit="CNY"
            )
        ],
        refusal_conditions=[],
        causal_claim_must_remain_unverified=False,
    )
    report = service.build(artifacts, None)
    payload = {
        "run_id": "unit-report",
        "case_id": task.case_id,
        "question_sha256": digest(task.question),
        "model_mode": "fake",
        "manifest": {"cross_source_report": {"scope": scope.model_dump(mode="json")}},
        "snapshot": {
            "unknown": False,
            "next": False,
            "review": False,
            "state": {"results": {}},
            "report": report.model_dump(mode="json"),
        },
        "calls": [],
        "artifacts": {},
    }
    return (
        task,
        gold,
        payload,
        b"k" * 32,
        {(bridge.request.dataset_id, bridge.request.dataset_version): bridge.source_sha256},
    )


def test_real_contract_shape_and_signed_numeric_score(campaign_modules, scored):
    _, evaluator, _, signing = campaign_modules
    task, gold, payload, key, sources = scored
    assert evaluator.score(
        task, gold, signing.sign_collection(payload, key), key, source_hashes=sources
    )["strict_correct"]


def test_formal_runner_without_new_permit_cannot_dispatch(campaign_modules, monkeypatch, tmp_path):
    campaign, _, _, _ = campaign_modules
    folder = tmp_path / "launch"
    folder.mkdir()
    config = {"phase": "formal", "case_id": "bh2-001"}
    raw = json.dumps(config).encode()
    (folder / "config.json").write_bytes(raw)
    (folder / "launch-pin.json").write_text(
        json.dumps({"config_sha256": campaign.sha(raw)}), encoding="utf-8"
    )
    policy = tmp_path / "policy.json"
    policy.write_text("{}", encoding="utf-8")
    (tmp_path / "context-policy-index.json").write_text(
        json.dumps({"bh2-001": {"path": "policy.json", "sha256": campaign.sha(b"{}")}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(campaign, "BASE", tmp_path)
    monkeypatch.setattr(campaign, "ROOT", tmp_path)
    monkeypatch.setattr(campaign, "inspect", lambda: None)
    monkeypatch.setattr(
        campaign.subprocess, "run", lambda *a, **kw: pytest.fail("Unauthorized dispatch")
    )
    with pytest.raises(ValueError, match="No business Live authorization"):
        campaign._run_container(folder, "start")
    assert not list(folder.glob("*.issued"))


def test_batch_lost_response_is_signed_unknown_and_stops(campaign_modules, monkeypatch, tmp_path):
    campaign, _, _, signing = campaign_modules
    driver = importlib.import_module("p7_run_approved_campaign")
    ids = [f"bh2-{n:03}" for n in range(1, 61)]
    tasks = [SimpleNamespace(case_id=id_, owner="public-test-owner") for id_ in ids]
    rows = [
        {"case_id": id_, "stage": "runtime", "path": id_, "config_sha256": "c" * 64} for id_ in ids
    ]
    (tmp_path / "launches.json").write_text(
        json.dumps({"campaign_id": "public-mock-campaign", "cases": rows}), encoding="utf-8"
    )
    config = {
        "case_id": ids[0],
        "run_id": "public-mock-run",
        "question_sha256": "a" * 64,
        "pack_sha256": "b" * 64,
        "report_scope": {},
        "rag_scope": None,
    }
    (tmp_path / ids[0]).mkdir()
    (tmp_path / ids[0] / "config.json").write_text(json.dumps(config), encoding="utf-8")
    freeze = tmp_path / "docs/research/p7-business-v2-freeze.json"
    freeze.parent.mkdir(parents=True)
    freeze.write_text('{"files":{}}', encoding="utf-8")
    permit = {
        "config_hashes": dict.fromkeys(ids, "c" * 64),
        "approve_bound_runs": True,
        "implementation_sha256": campaign.sha(freeze.read_bytes()),
        "source_user_authorization_ref": "public-unit-mock-not-real-permission",
    }
    monkeypatch.setattr(driver, "BASE", tmp_path)
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "load_v2", lambda: (tasks, {}, {"seal_sha256": "b" * 64}))
    monkeypatch.setattr(driver, "permit_valid", lambda *a, **kw: None)
    monkeypatch.setattr(
        driver, "environment", lambda: {"DATAPILOT_RUNTIME_DATABASE_URL": "not-a-real-dsn"}
    )
    monkeypatch.setattr(
        driver,
        "Backend",
        lambda *a: SimpleNamespace(
            lease=nullcontext, assert_lease=lambda: None, close=lambda: None
        ),
    )
    dispatched = []

    def dispatch(folder, action, **kwargs):
        dispatched.append((folder.name, action))
        if action == "approve":
            raise TimeoutError("Mock: request sent, response lost")

    monkeypatch.setattr(driver, "_run_container", dispatch)
    with pytest.raises(RuntimeError, match="outcome retained as unknown"):
        driver.execute(permit)
    assert dispatched == [(ids[0], "start"), (ids[0], "approve")]
    results = tmp_path / "private/campaign-results/public-mock-campaign"
    record = json.loads((results / (ids[0] + ".json")).read_bytes())
    payload = signing.authenticated(record, (results / "collector.key").read_bytes())
    assert payload["unresolved_dispatch"] and payload["snapshot"]["unknown"]
    assert payload["actual_provider_cost"] is None and not (results / (ids[1] + ".json")).exists()
    with pytest.raises(FileExistsError):
        driver.execute(permit)
    assert len(dispatched) == 2


@pytest.mark.parametrize(
    "mutation", ["unit", "version", "source", "verdict", "chart", "question", "unsigned"]
)
def test_forged_units_versions_charts_or_signatures_fail_closed(campaign_modules, scored, mutation):
    _, evaluator, _, signing = campaign_modules
    task, gold, payload, key, sources = scored
    payload = copy.deepcopy(payload)
    metric = payload["snapshot"]["report"]["claims"][0]["metric"]
    if mutation == "unit":
        metric["value"]["unit"] = "USD"
    if mutation == "source":
        metric["source_sha256"] = "b" * 64
    if mutation == "version":
        metric["request"]["metric_version"] += 1
    if mutation == "verdict":
        metric["verification"]["verdict"] = "unavailable"
    if mutation == "chart":
        payload["snapshot"]["report"]["charts"][0]["unit"] = "events"
    if mutation == "question":
        payload["question_sha256"] = "c" * 64
    record = signing.sign_collection(payload, key)
    if mutation == "unsigned":
        record["signature"] = "d" * 64
    try:
        result = evaluator.score(task, gold, record, key, source_hashes=sources)
        assert not result["strict_correct"]
    except ValueError:
        pass


@pytest.mark.parametrize("state", ["unknown", "next", "review"])
def test_unknown_or_unapproved_never_becomes_business_success(campaign_modules, scored, state):
    _, evaluator, _, signing = campaign_modules
    task, gold, payload, key, sources = scored
    payload["snapshot"][state] = True
    assert not evaluator.score(
        task, gold, signing.sign_collection(payload, key), key, source_hashes=sources
    )["strict_correct"]


def test_join_keyword_or_missing_proof_cannot_pass(campaign_modules, scored):
    _, evaluator, _, signing = campaign_modules
    task, gold, payload, key, sources = scored
    payload["sql"] = "JOIN customers"
    result = evaluator.score(
        task,
        gold,
        signing.sign_collection(payload, key),
        key,
        source_hashes=sources,
        rule={"customer_linkage_and_invoice_grain": True},
    )
    assert not result["strict_correct"] and not result["lineage_valid"]


def test_unregistered_refusal_is_not_silently_dropped(campaign_modules, scored):
    _, evaluator, _, signing = campaign_modules
    task, gold, payload, key, sources = scored
    gold = gold.model_copy(update={"refusal_conditions": ["unreviewed_new_meaning"]})
    result = evaluator.score(
        task, gold, signing.sign_collection(payload, key), key, source_hashes=sources
    )
    assert not result["strict_correct"] and result["requires_human_adjudication"]


def test_preflight_phase_does_not_require_forbidden_document_execution(campaign_modules, scored):
    _, evaluator, _, signing = campaign_modules
    task, gold, _, key, sources = scored
    gold = gold.model_copy(
        update={
            "host_decision": "confirmation_required",
            "business_completion": "blocked",
            "metrics": [],
            "refusal_conditions": ["version_confirmation_required"],
        }
    )
    payload = {
        "stage": "preflight",
        "case_id": task.case_id,
        "task_sha256": digest(task),
        "preflight_code": "REPORT_SCOPE_INVALID",
        "model_calls": 0,
        "business_queries": 0,
        "retrieval_queries": 0,
        "report": None,
    }
    result = evaluator.score(
        task,
        gold,
        signing.sign_collection(payload, key),
        key,
        source_hashes=sources,
        rule={"execution_phase": "preflight"},
    )
    assert result["strict_correct"] and not result["retrieval_obligation"]
    for field in ("model_calls", "business_queries", "retrieval_queries"):
        bad = payload | {field: 1}
        assert not evaluator.score_preflight(task, gold, bad)["strict_correct"]
    assert not evaluator.score_preflight(task, gold, payload | {"preflight_code": "MODEL_TIMEOUT"})[
        "strict_correct"
    ]


def test_ranking_preserves_empty_and_duplicate_source_penalties(campaign_modules):
    _, evaluator, _, _ = campaign_modules
    result = evaluator.ranks(["a", "a", "b"], ["b", "c"])
    assert result["recall_at_k"] == 0.5 and result["precision_at_k"] == 1 / 3
    assert result["mrr_at_k"] == 0.5
    assert evaluator.ranks([], [])["recall_at_k"] is None


def test_missing_cases_and_fake_usage_never_become_live_quality(campaign_modules, scored):
    _, evaluator, _, _ = campaign_modules
    task = scored[0]
    summary = evaluator.summarize([task], {}, mode="live")
    assert summary["planned"] == 1 and summary["live_success_rate"] is None
    assert evaluator.wilson(0, 0) is None
    assert evaluator.usage_summary([])["estimated_usd"] is None
    assert evaluator.quantile([], 0.95) is None
    with pytest.raises(ValueError, match="Fake"):
        evaluator.summarize(
            [task], {task.case_id: {"strict_correct": True, "model_mode": "fake"}}, mode="live"
        )


def permit():
    return {
        "kind": "business-live-authorization",
        "approved_by_role": "project_owner",
        "source_user_authorization_ref": "future-specific-human-message",
        "pack_sha256": "a" * 64,
        "campaign_id": "test-campaign",
        "mode": "live",
        "provider": "deepseek",
        "model": "deepseek-flash",
        "thinking": "disabled",
        "config_hashes": {"bh2-001": "b" * 64},
        "max_runs": 60,
        "calls_per_run": 8,
        "tokens_per_run": 18000,
        "concurrency": 1,
        "automatic_retries": 0,
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }


@pytest.mark.parametrize(
    "change",
    [
        {"tokens_per_run": 18001},
        {"concurrency": True},
        {"automatic_retries": 1},
        {"model": "other"},
        {"source_user_authorization_ref": ""},
        {"pack_sha256": "x" * 64},
    ],
)
def test_future_live_permission_cannot_expand_budget_or_identity(campaign_modules, change):
    campaign, _, _, _ = campaign_modules
    p = permit() | change
    with pytest.raises(ValueError):
        campaign.permit_valid(
            p,
            pack_hash="a" * 64,
            campaign_id="test-campaign",
            case_id="bh2-001",
            config_hash="b" * 64,
        )


def test_launch_path_and_fake_formal_rejected_before_any_io(campaign_modules):
    campaign, _, _, _ = campaign_modules
    task = SimpleNamespace(case_id="toy-../../outside")
    with pytest.raises(ValueError):
        campaign.prepare_launch(
            task, phase="toy", campaign_id="test", pack_hash="a" * 64, assets={}
        )
    task.case_id = "bh2-001"
    with pytest.raises(ValueError):
        campaign.prepare_launch(
            task, phase="toy", campaign_id="test", pack_hash="a" * 64, assets={}
        )


def test_missing_definition_policy_is_exact_and_does_not_self_approve(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    worker = importlib.import_module("p7_campaign_worker")
    expected = {"source_sha256": "a" * 64, "semantic_sha256": "b" * 64, "metric_sha256": "c" * 64}
    negative = {"expected_hashes": expected, "required_error_code": "SEMANTIC_NOT_CONFIRMED"}
    worker.check_context_observation(expected, None, "SEMANTIC_NOT_CONFIRMED", negative)
    with pytest.raises(ValueError):
        worker.check_context_observation(expected, expected, None, negative)
    with pytest.raises(ValueError):
        worker.check_context_observation(expected, None, "MODEL_TIMEOUT", negative)
    with pytest.raises(ValueError):
        worker.check_context_observation(expected, None, "SEMANTIC_NOT_CONFIRMED", None)


def test_unknown_dispatch_is_not_not_run_or_zero_bill(campaign_modules, scored):
    _, evaluator, _, signing = campaign_modules
    runner = importlib.import_module("p7_run_approved_campaign")
    task, gold, original, key, sources = scored
    config = {
        "case_id": task.case_id,
        "run_id": "unit-report",
        "question_sha256": digest(task.question),
        "pack_sha256": "a" * 64,
        "report_scope": original["manifest"]["cross_source_report"]["scope"],
        "rag_scope": None,
    }
    event = runner.unknown_dispatch(config, "synthetic-unit-authorization")
    result = evaluator.score(
        task, gold, signing.sign_collection(event, key), key, source_hashes=sources
    )
    assert result["status"] == "unknown" and not result["strict_correct"]
    usage = evaluator.usage_summary([event])
    assert not usage["model_call_count_complete"] and usage["unresolved_dispatches"] == 1
    assert usage["actual_bill_usd"] is None and usage["estimated_usd"] is None


def test_zero_observations_keep_numeric_and_rag_denominators(campaign_modules, scored):
    _, evaluator, _, _ = campaign_modules
    task, gold, *_ = scored
    result = evaluator.quality_summary(
        {task.case_id: gold}, {}, {"cases": {}, "default": {"execution_phase": "runtime"}}
    )
    assert result["numeric"]["planned_goals"] == 1 and result["numeric"]["observed_rate"] is None
    assert result["rag"]["observed_tasks"] == 0


def test_malformed_provider_usage_does_not_fabricate_tokens(campaign_modules):
    _, evaluator, _, _ = campaign_modules
    result = evaluator.usage_summary(
        [
            {
                "model_mode": "live",
                "calls": [
                    {
                        "kind": "model",
                        "status": "complete",
                        "usage": {"input_tokens": 3, "output_tokens": None},
                    }
                ],
            }
        ]
    )
    assert result["unknown_usage_calls"] == 1 and result["estimated_usd"] is None
