import copy
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import formal_runner

from datapilot.reporting.contracts import ReportScope

ins = []
bycfg = {}


@pytest.fixture(autouse=True)
def public_formal_inputs(synthetic_binding, monkeypatch):
    root, _, _ = synthetic_binding
    dataset_id = "00000000-0000-4000-8000-000000000001"
    rows, configs = [], {}
    for i, case_id in enumerate(ids(), 1):
        scope = ReportScope.model_validate(
            {
                "owner": "public-runner-control",
                "question": f"Public synthetic runner control number {i}.",
                "datasets": {"bindings": [{"dataset_id": dataset_id, "version": 1}]},
                "metrics": [
                    {
                        "goal_id": "metric_1",
                        "dataset_id": dataset_id,
                        "dataset_version": 1,
                        "semantic_version": 1,
                        "metric_id": "paid_invoice_revenue",
                        "metric_version": 1,
                        "window": {"start": date(2032, 1, 1), "end_exclusive": date(2032, 2, 1)},
                    }
                ],
            }
        )
        row = {
            key: value
            for key, value in scope.model_dump(mode="json").items()
            if key
            in {"owner", "question", "datasets", "metrics", "document_goal", "causal_requested"}
        }
        row.update(case_id=case_id, lane="sql_only", objective=f"Public runner control {i}")
        rows.append(row)
        configs[case_id] = {
            "case_id": case_id,
            "run_id": "public-control-" + str(i),
            "report_scope": scope.model_dump(mode="json"),
            "rag_scope": None,
        }
    monkeypatch.setattr(sys.modules[__name__], "ins", rows)
    monkeypatch.setattr(sys.modules[__name__], "bycfg", configs)
    monkeypatch.setattr(formal_runner, "ROOT", root)
    env = root / "artifacts/p7/current-pg/private/environment.json"
    env.parent.mkdir(parents=True)
    env.write_text("{}", encoding="utf-8")
    material = root / "artifacts/p7/final-evaluation-v1/total-50/materialization.json"
    material.parent.mkdir()
    material.write_text(
        json.dumps({"datasets": {"public": {"id": dataset_id, "version": 1}}}), encoding="utf-8"
    )
    monkeypatch.setattr(
        formal_runner,
        "load_gold",
        lambda case_id: {
            "case_id": case_id,
            "business_completion": "completed",
            "host_decision": "review_then_run",
            "metrics": [],
            "refusal_conditions": [],
            "causal_claim_must_remain_unverified": True,
        },
    )
    monkeypatch.setattr(formal_runner, "load_pins", lambda _: {})


def ids():
    return [
        "p7-holdout-v3-061",
        "p7-holdout-v3-062",
        "p7-holdout-v3-063",
        "p7-holdout-v3-064",
        "p7-holdout-v3-065",
        "p7-holdout-v3-066",
    ]


def make_manifest():
    return {"planned": 6, "preflight": [next(c for c in ins if c["case_id"] == x) for x in ids()]}


def make_configs():
    out = []
    for x in ids():
        c = copy.deepcopy(bycfg[x])
        c["synthetic_probe"] = False
        if x == "p7-holdout-v3-062":
            c["report_scope"] = {}
        out.append(c)
    return out


def run(
    tmp_path, *, fail=False, unknown=False, max_calls=50, max_tokens=500, collected_unknown=False
):
    calls = []

    def runner(cfg, folder, mode, action, values, product, deadline, permit=None):
        calls.append((cfg["case_id"], action))
        if cfg["case_id"] == "p7-holdout-v3-064" or fail:
            raise RuntimeError("ordinary failure")
        if cfg["case_id"] == "p7-holdout-v3-065" or unknown:
            if collected_unknown:
                return {"snapshot": {"usage": {"calls": 1, "total_tokens": 37}, "unknown": True}}
            raise RuntimeError("unknown outcome")
        return {"snapshot": {"usage": {"calls": 1, "total_tokens": 10}, "unknown": False}}

    def scorer(*args):
        return {"status": "completed", "strict_correct": True}

    m = make_manifest()
    c = make_configs()
    return formal_runner.run_batch(
        m,
        c,
        None,
        tmp_path / "out",
        mode="fake",
        runner=runner,
        scorer=scorer,
        max_calls=max_calls,
        max_tokens=max_tokens,
    ), calls


def test_formal_batch_normal_rejection_continue_stop(tmp_path):
    r, calls = run(tmp_path)
    assert r["states"]["p7-holdout-v3-061"]["status"] == "completed"
    assert r["states"]["p7-holdout-v3-062"]["status"] == "expected_host_rejection"
    assert ("p7-holdout-v3-062", "probe") not in calls
    assert r["states"]["p7-holdout-v3-063"]["status"] == "completed"
    assert r["states"]["p7-holdout-v3-064"]["status"] == "failed"
    assert r["states"]["p7-holdout-v3-065"]["status"] == "unknown"
    assert r["states"]["p7-holdout-v3-066"]["status"] == "not_run"
    assert r["planned"] == 6 and r["calls"] == 2


def test_repeat_no_redispatch(tmp_path):
    # normal-only subset
    m = {
        "planned": 2,
        "preflight": [
            next(c for c in ins if c["case_id"] == "p7-holdout-v3-061"),
            next(c for c in ins if c["case_id"] == "p7-holdout-v3-063"),
        ],
    }
    c = [copy.deepcopy(bycfg[x]) for x in ["p7-holdout-v3-061", "p7-holdout-v3-063"]]
    calls = []

    def runner(cfg, folder, mode, action, values, product, deadline, permit=None):
        calls.append((cfg["case_id"], action))
        return {"snapshot": {"usage": {"calls": 1, "total_tokens": 10}, "unknown": False}}

    def scorer(*args):
        return {"status": "completed", "strict_correct": True}

    out = tmp_path / "repeat"
    formal_runner.run_batch(m, c, None, out, mode="fake", runner=runner, scorer=scorer)
    n = len(calls)
    formal_runner.run_batch(m, c, None, out, mode="fake", runner=runner, scorer=scorer)
    assert len(calls) == n


def test_permit_invalid():
    try:
        formal_runner.validate_permit({"authorized": False}, {"planned": 50}, "live")
    except ValueError:
        return
    raise AssertionError


def test_budget_rejected_before_dispatch(tmp_path):
    r, calls = run(tmp_path, max_calls=0)
    assert not calls
    assert r["states"] and all(
        v["status"] in {"not_run", "expected_host_rejection"} for v in r["states"].values()
    )


def test_infrastructure_error_stops_and_leaves_rest_not_run(tmp_path):
    cases = [
        next(c for c in ins if c["case_id"] == "p7-holdout-v3-061"),
        next(c for c in ins if c["case_id"] == "p7-holdout-v3-063"),
        next(c for c in ins if c["case_id"] == "p7-holdout-v3-064"),
    ]
    configs = [copy.deepcopy(bycfg[c["case_id"]]) for c in cases]
    calls = []

    def runner(config, folder, mode, action, values, product, deadline, permit=None):
        calls.append((config["case_id"], action))
        raise KeyError("question_sha256")

    def scorer(*args):
        return {"status": "completed", "strict_correct": True}

    result = formal_runner.run_batch(
        {"planned": 3, "preflight": cases},
        configs,
        None,
        tmp_path / "infra",
        mode="fake",
        runner=runner,
        scorer=scorer,
    )
    assert calls == [("p7-holdout-v3-061", "probe")]
    assert result["states"]["p7-holdout-v3-061"]["status"] == "blocked"
    assert result["states"]["p7-holdout-v3-063"]["status"] == "not_run"
    assert result["states"]["p7-holdout-v3-064"]["status"] == "not_run"
    assert result["stop"] == "infrastructure"


def test_failed_case_is_not_redispatched(tmp_path):
    _, first = run(tmp_path)
    assert ("p7-holdout-v3-064", "probe") in first
    result, second = run(tmp_path)
    assert not second
    assert result["states"]["p7-holdout-v3-064"]["status"] == "failed"


def test_live_permit_requires_exact_budget_and_exclusion():
    import pytest

    excluded = [f"synthetic-{i}" for i in range(37)]
    manifest = {
        "planned": 50,
        "preflight": [{"case_id": cid, "status": "PREVIOUSLY_COLLECTED"} for cid in excluded],
    }
    permit = {
        "authorized": True,
        "provider": "deepseek",
        "model": "deepseek-flash",
        "thinking": "disabled",
        "approved_by_role": "project_owner",
        "approval_ref": "test-only",
        "case_count": 50,
        "runtime_runs": 13,
        "provider_attempts": 104,
        "token_units": 234000,
        "excluded_case_ids": excluded,
        "campaign_id": "p7-final-50-v7",
        "manifest_sha256": formal_runner.digest(manifest),
        "evaluation_sha256": formal_runner.digest(formal_runner.current_binding.load_manifest()),
    }
    formal_runner.validate_permit(permit, manifest, "live")
    with pytest.raises(ValueError, match="permit budget mismatch"):
        formal_runner.validate_permit(permit | {"provider_attempts": 400}, manifest, "live")
    with pytest.raises(ValueError, match="exclusion mismatch"):
        formal_runner.validate_permit(permit | {"excluded_case_ids": []}, manifest, "live")


def test_collected_unknown_usage_is_included_in_summary(tmp_path):
    result, _ = run(tmp_path, collected_unknown=True)
    unknown = result["states"]["p7-holdout-v3-065"]
    assert (unknown["status"], unknown["calls"], unknown["tokens"]) == ("unknown", 1, 37)
    assert (result["calls"], result["tokens"]) == (3, 57)


def test_frozen_scope_mismatch_is_rejected():
    import pytest

    raw = next(row for row in ins if row["case_id"] == ids()[0])
    task = formal_runner.Case.model_validate_json(json.dumps(raw))
    cfg = copy.deepcopy(bycfg[ids()[0]])
    formal_runner.verify_scoring_scope(task, cfg)
    cfg["report_scope"]["metrics"][0]["metric_version"] += 1
    with pytest.raises(ValueError, match="launch differs"):
        formal_runner.verify_scoring_scope(task, cfg)


def test_collected_503_exception_is_limited_to_one_uncertain_model():
    error = {
        "code": "MODEL_ERROR",
        "message": "Async model provider failed (OpenAIAPIError, HTTP 503)",
    }
    payload = {
        "snapshot": {"unknown": True, "state": {"error": error}},
        "calls": [{"kind": "model", "status": "uncertain"}],
    }
    assert formal_runner.collected_provider_503(payload)
    payload["calls"].append({"kind": "tool", "status": "uncertain"})
    assert not formal_runner.collected_provider_503(payload)
    payload["calls"].pop()
    error["message"] = error["message"].replace("503", "401")
    assert not formal_runner.collected_provider_503(payload)
