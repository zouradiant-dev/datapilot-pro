"""Public signed budget/profile controls; no database, Provider or sealed tasks."""

import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from test_p7_current_citation_scoring import example as example
from test_p7_partial_evidence_scoring import partial as partial
from test_p7_scorer_versions import case as case

from datapilot.ingestion.common import digest
from datapilot.orchestration.rag_completion import retrieval_goal
from evaluation.p7_v3_current import profile_scoring as scoring

KEY = b"public-profile-control-key-32bytes"


def signed(payload):
    return scoring.p7_business_scoring.sign_collection(payload, KEY)


def public_usage(totals=(7000, 7000, 7000), *, account="1:documents"):
    calls = [
        {
            "kind": "model",
            "status": "complete",
            "account": account,
            "usage": {
                "input_tokens": value - 100,
                "output_tokens": 100,
                "total_tokens": value,
            },
        }
        for value in totals
    ]
    return {
        "calls": calls,
        "snapshot": {
            "unknown": False,
            "usage": {
                "calls": len(calls),
                "total_tokens": sum(totals),
                "usage_complete": True,
            },
        },
    }


def profile36(**update):
    return scoring.BudgetProfile(root_tokens=36000, worker_tokens=36000, **update)


def with_complete_units(data, *, total=21000):
    """Give the real public scorer fixture three settled, paired model responses."""
    original = data.payload["calls"][1]
    original["usage"] = {
        "input_tokens": total // 3 - 100,
        "output_tokens": 100,
        "total_tokens": total // 3,
    }
    for index in (1, 2):
        body = {"data": {"tool_calls": []}}
        value = total // 3 if index == 1 else total - 2 * (total // 3)
        data.payload["calls"].append(
            {
                "kind": "model",
                "account": "root",
                "call_key": f"model:root:public-budget-{index}",
                "tool_name": None,
                "status": "complete",
                "payload": body,
                "payload_hash": digest(body),
                "usage": {
                    "input_tokens": value - 100,
                    "output_tokens": 100,
                    "total_tokens": value,
                },
            }
        )
    data.payload["snapshot"]["usage"] = {
        "calls": 3,
        "total_tokens": total,
        "usage_complete": True,
    }


def partial_scorer(data):
    import p7_business_evaluator
    import p7_business_scoring

    def goal(question):
        assert question == data.task.document_goal.question
        return retrieval_goal(question, SimpleNamespace(scope=data.task.rag_scope), data.scope)

    def evaluate(task, gold, record, key, pins):
        with (
            patch.object(p7_business_scoring, "ReportScope", return_value=data.scope),
            patch.object(p7_business_evaluator, "retrieval_goal", goal),
        ):
            return data.new_scorer.score(task, gold, record, key, pins)

    return evaluate


def evaluate_partial(data, *, profile=None, callback=None):
    return scoring.score_with_profile(
        data.task,
        data.gold,
        data.signing.sign_collection(data.payload, data.key),
        data.key,
        data.pins,
        profile=profile or profile36(),
        score_original=callback or partial_scorer(data),
    )


def test_profile_is_immutable_strict_and_hashes_all_declared_limits():
    profile = profile36()
    assert profile.sha256 == digest(profile.model_dump(mode="json"))
    assert profile.sha256 != profile36(input_chars=12000).sha256
    assert profile.root_tokens == profile.worker_tokens == 36000
    assert profile.context_tokens == 18000 and profile.output_tokens == 1200
    with pytest.raises(ValidationError):
        profile.root_tokens = 72000
    for update in ({"root_calls": True}, {"worker_tokens": 36001}, {"worker_calls": 9}):
        with pytest.raises(ValidationError):
            scoring.BudgetProfile(**update)


def test_root_and_worker_are_cumulative_while_window_is_per_call():
    payload = public_usage()
    assert scoring.audit_budget(payload, profile36())["valid"]
    old = scoring.audit_budget(payload, scoring.BudgetProfile())
    assert not old["valid"]
    assert old["errors"] == ["ROOT_BUDGET_LIMIT", "WORKER_BUDGET_LIMIT"]
    lower_worker = scoring.BudgetProfile(root_tokens=36000, worker_tokens=18000)
    assert scoring.audit_budget(payload, lower_worker)["errors"] == ["WORKER_BUDGET_LIMIT"]


@pytest.mark.parametrize(
    ("totals", "valid"),
    [((12000, 12000, 12000), True), ((12000, 12000, 12001), False)],
)
def test_exact_root_and_worker_token_boundary(totals, valid):
    assert scoring.audit_budget(public_usage(totals), profile36())["valid"] is valid


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("unknown", "UNKNOWN_OUTCOME"),
        ("pending", "UNSETTLED_CALL"),
        ("missing_usage", "MODEL_USAGE_INVALID"),
        ("bool_usage", "MODEL_USAGE_INVALID"),
        ("bad_units", "MODEL_USAGE_INVALID"),
        ("snapshot_tokens", "SNAPSHOT_USAGE_MISMATCH"),
        ("snapshot_calls", "SNAPSHOT_USAGE_MISMATCH"),
        ("incomplete", "SNAPSHOT_USAGE_INCOMPLETE"),
        ("worker_calls", "WORKER_BUDGET_LIMIT"),
        ("root_calls", "ROOT_BUDGET_LIMIT"),
        ("output", "OUTPUT_TOKEN_LIMIT"),
        ("window", "CONTEXT_TOKEN_LIMIT"),
    ],
)
def test_budget_rejects_unknown_incomplete_mismatched_and_over_limit_usage(mutation, code):
    payload = public_usage()
    if mutation == "unknown":
        payload["snapshot"]["unknown"] = True
    elif mutation == "pending":
        payload["calls"][0]["status"] = "issued"
    elif mutation == "missing_usage":
        del payload["calls"][0]["usage"]
    elif mutation == "bool_usage":
        payload["calls"][0]["usage"]["input_tokens"] = True
    elif mutation == "bad_units":
        payload["calls"][0]["usage"]["total_tokens"] += 1
    elif mutation == "snapshot_tokens":
        payload["snapshot"]["usage"]["total_tokens"] += 1
    elif mutation == "snapshot_calls":
        payload["snapshot"]["usage"]["calls"] = True
    elif mutation == "incomplete":
        payload["snapshot"]["usage"]["usage_complete"] = False
    elif mutation == "worker_calls":
        payload = public_usage((1000,) * 5)
    elif mutation == "root_calls":
        payload = public_usage((1000,) * 9, account="root")
    elif mutation == "output":
        payload["calls"][0]["usage"].update(input_tokens=5799, output_tokens=1201)
    elif mutation == "window":
        payload = public_usage((18001,))
    result = scoring.audit_budget(payload, profile36())
    assert result["valid"] is False and code in result["errors"]


def test_unsigned_collection_is_rejected_before_the_scorer_reads_gold():
    observed = signed(public_usage())
    observed["signature"] = "0" * 64
    invoked = []
    with pytest.raises(ValueError, match="trusted collector"):
        scoring.score_with_profile(
            None,
            None,
            observed,
            KEY,
            {},
            profile=profile36(),
            score_original=lambda *args: invoked.append(args),
        )
    assert invoked == []


@pytest.mark.parametrize("shape", ["missing", None, {}])
def test_early_failure_without_dimensions_stays_a_failure(shape):
    original = {"strict_correct": False, "status": "blocked", "failure_class": "planner_error"}
    if shape != "missing":
        original["dimensions"] = shape
    observed = signed(public_usage((684,)))
    result = scoring.score_with_profile(
        None, None, observed, KEY, {}, profile=profile36(), score_original=lambda *args: original
    )
    assert result["strict_correct"] is False
    assert result["status"] == "blocked" and result["failure_class"] == "planner_error"
    assert result["original_18000_score"] == original
    assert result.get("dimensions") == original.get("dimensions")
    assert ("dimensions" in result) == ("dimensions" in original)
    assert result["frozen_early_failure_preserved"] is True
    assert result["frozen_baseline_hook_invocations"] == 0


def test_genuine_zero_call_host_refusal_is_not_runtime_budget_scoring():
    payload = {"model_calls": 0, "business_queries": 0, "retrieval_queries": 0}
    original = {"strict_correct": True, "host_refusal_correct": True}
    result = scoring.score_with_profile(
        None,
        None,
        signed(payload),
        KEY,
        {},
        profile=profile36(),
        score_original=lambda *args: original,
        host_refusal=True,
    )
    assert result["strict_correct"] is True and result["budget_profile_audit"] is None
    with patch.object(scoring, "ordinary_failure_may_continue") as runtime_gate:
        assert (
            scoring.ordinary_failure_may_continue_profiled(
                result, signed(payload), KEY, expected_profile=profile36()
            )
            is False
        )
    runtime_gate.assert_not_called()
    with pytest.raises(scoring.ProfileScoringError, match="ZERO_RUNTIME"):
        scoring.score_with_profile(
            None,
            None,
            signed(payload | {"snapshot": {}}),
            KEY,
            {},
            profile=profile36(),
            score_original=lambda *args: original,
            host_refusal=True,
        )


def test_invalid_early_usage_preserves_failure_and_requires_operator_stop():
    payload = public_usage((684,))
    payload["snapshot"]["usage"]["usage_complete"] = False
    original = {"strict_correct": False, "status": "blocked", "failure_class": "planner_error"}
    result = scoring.score_with_profile(
        None,
        None,
        signed(payload),
        KEY,
        {},
        profile=profile36(),
        score_original=lambda *args: original,
    )
    assert result["strict_correct"] is False and "dimensions" not in result
    assert result["failure_class"] == "planner_error"
    assert result["budget_audit_requires_stop"] is True
    assert result["original_18000_score"] == original
    with patch.object(scoring, "ordinary_failure_may_continue") as runtime_gate:
        assert (
            scoring.ordinary_failure_may_continue_profiled(
                result, signed(payload), KEY, expected_profile=profile36()
            )
            is False
        )
    runtime_gate.assert_not_called()


def ordinary_profile_result(payload=None, profile=None):
    original = {
        "strict_correct": False,
        "failure_class": "planner_error",
        "dimensions": {},
    }
    return scoring.score_with_profile(
        None,
        None,
        signed(payload if payload is not None else public_usage()),
        KEY,
        {},
        profile=profile if profile is not None else profile36(),
        score_original=lambda *args: original,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"budget_audit_requires_stop": True},
        {"budget_audit_requires_stop": None},
        {"profile_scorer_version": "PUBLIC_UNKNOWN_SCORER"},
        {"budget_profile_audit": None},
        {"budget_profile_audit": {"valid": False}},
        {"host_refusal_budget_not_applicable": True},
        {"dimensions": None},
    ],
)
def test_profile_consumer_fails_closed_before_runtime_policy(change):
    result = ordinary_profile_result() | change
    with patch.object(scoring, "ordinary_failure_may_continue") as runtime_gate:
        assert (
            scoring.ordinary_failure_may_continue_profiled(
                result, signed(public_usage()), KEY, expected_profile=profile36()
            )
            is False
        )
    runtime_gate.assert_not_called()


@pytest.mark.parametrize(
    ("error_code", "may_continue"),
    [
        (None, True),
        ("BUSINESS_ERROR", True),
        ("MODEL_ERROR", False),
        ("BUDGET_EXCEEDED", False),
        ("EVIDENCE_INVALID", False),
        ("REPORT_EVIDENCE_INVALID", False),
    ],
)
def test_profile_consumer_delegates_original_stop_rules_without_isolation(error_code, may_continue):
    payload = public_usage()
    if error_code:
        payload["snapshot"]["state"] = {"error": {"code": error_code}}
    result = ordinary_profile_result(payload)
    with patch.object(
        scoring, "ordinary_failure_may_continue", wraps=scoring.ordinary_failure_may_continue
    ) as runtime_gate:
        assert (
            scoring.ordinary_failure_may_continue_profiled(
                result, signed(payload), KEY, expected_profile=profile36()
            )
            is may_continue
        )
    runtime_gate.assert_called_once_with(result, payload)


def test_profile_consumer_rejects_valid_score_from_another_budget_profile():
    payload = public_usage((7000, 7000, 7000))
    result = ordinary_profile_result(payload)
    with patch.object(scoring, "ordinary_failure_may_continue") as runtime_gate:
        assert (
            scoring.ordinary_failure_may_continue_profiled(
                result, signed(payload), KEY, expected_profile=scoring.BudgetProfile()
            )
            is False
        )
    runtime_gate.assert_not_called()


@pytest.mark.parametrize(
    "field",
    [
        "authenticated_collection_sha256",
        "authenticated_payload_sha256",
        "budget_profile",
        "budget_profile_sha256",
    ],
)
def test_profile_consumer_requires_every_score_binding(field):
    result = ordinary_profile_result()
    del result[field]
    with patch.object(scoring, "ordinary_failure_may_continue") as runtime_gate:
        assert (
            scoring.ordinary_failure_may_continue_profiled(
                result, signed(public_usage()), KEY, expected_profile=profile36()
            )
            is False
        )
    runtime_gate.assert_not_called()


def test_profile_consumer_recomputes_the_declared_profile_hash_with_strict_json_types():
    profile = scoring.BudgetProfile(root_calls=1, worker_calls=1)
    payload = public_usage((7000,))
    result = ordinary_profile_result(payload, profile)
    result["budget_profile"]["root_calls"] = True
    with patch.object(scoring, "ordinary_failure_may_continue") as runtime_gate:
        assert (
            scoring.ordinary_failure_may_continue_profiled(
                result, signed(payload), KEY, expected_profile=profile
            )
            is False
        )
    runtime_gate.assert_not_called()


@pytest.mark.parametrize("broken_usage", [False, True])
def test_profile_consumer_rejects_score_from_another_run_even_with_same_budget(broken_usage):
    previous = public_usage() | {"case_id": "public_previous", "run_id": "public_run_previous"}
    current = public_usage() | {"case_id": "public_current", "run_id": "public_run_current"}
    if broken_usage:
        current["snapshot"]["usage"]["usage_complete"] = False
    result = ordinary_profile_result(previous)
    with patch.object(scoring, "ordinary_failure_may_continue") as runtime_gate:
        assert (
            scoring.ordinary_failure_may_continue_profiled(
                result, signed(current), KEY, expected_profile=profile36()
            )
            is False
        )
    runtime_gate.assert_not_called()


def test_profile_consumer_reauthenticates_the_current_collection():
    record = signed(public_usage())
    result = ordinary_profile_result(record["payload"])
    record["payload"]["snapshot"]["usage"]["usage_complete"] = False
    with patch.object(scoring, "ordinary_failure_may_continue") as runtime_gate:
        with pytest.raises(ValueError, match="not signed by the trusted collector"):
            scoring.ordinary_failure_may_continue_profiled(
                result, record, KEY, expected_profile=profile36()
            )
    runtime_gate.assert_not_called()


def test_profile_consumer_reaudits_current_usage_instead_of_trusting_audit_metadata():
    payload = public_usage()
    result = ordinary_profile_result(payload)
    payload["snapshot"]["usage"]["usage_complete"] = False
    record = signed(payload)
    result["authenticated_collection_sha256"] = record["sha256"]
    result["authenticated_payload_sha256"] = digest(payload)
    with patch.object(scoring, "ordinary_failure_may_continue") as runtime_gate:
        assert (
            scoring.ordinary_failure_may_continue_profiled(
                result, record, KEY, expected_profile=profile36()
            )
            is False
        )
    runtime_gate.assert_not_called()


def test_real_partial_receipt_uses_same_budget_before_derived_decision(partial):
    with_complete_units(partial)
    original_payload = copy.deepcopy(partial.payload)
    original_gold = partial.gold.model_copy(deep=True)
    original_callable = scoring.legacy.original.score
    old = evaluate_partial(partial, profile=scoring.BudgetProfile())
    assert old["strict_correct"] is False
    assert old["dimensions"]["budget"] is False
    assert old["dimensions"]["retrieval_contract"] is False
    new = evaluate_partial(partial)
    assert new["strict_correct"] is True
    assert new["dimensions"]["budget"] is True
    assert new["dimensions"]["retrieval_contract"] is True
    assert new["partial_evidence_scoring"]["insufficient_compatible_with_partial"] is True
    assert new["original_18000_score"] == old["original_18000_score"]
    assert new["budget_derived_dimension_changes"] == {
        "retrieval_contract": {
            "original": False,
            "profile": True,
            "basis": "Unchanged frozen partial_receipt budget conjunction",
        }
    }
    assert new["non_budget_rules_unchanged"] is True
    assert scoring.legacy.original.score is original_callable
    assert partial.payload == original_payload and partial.gold == original_gold


def test_under_original_budget_every_frozen_score_field_is_identical(partial):
    with_complete_units(partial, total=3000)
    record = partial.signing.sign_collection(partial.payload, partial.key)
    original = partial_scorer(partial)(
        partial.task, partial.gold, record, partial.key, partial.pins
    )
    result = evaluate_partial(partial)
    assert result["strict_correct"] is True
    assert all(result[name] == value for name, value in original.items())
    assert result["original_18000_score"] == original
    assert result["budget_derived_dimension_changes"] == {}


@pytest.mark.parametrize("mutation", ["missing_fact", "minimum_sources"])
def test_budget_changes_do_not_repair_other_business_requirements(partial, mutation):
    with_complete_units(partial)
    if mutation == "missing_fact":
        partial.payload["snapshot"]["report"]["claims"][0]["fact_coverage"]["fact_1"] = None
    else:
        partial.gold.minimum_cited_sources = 2
    result = evaluate_partial(partial)
    assert result["budget_profile_audit"]["valid"] is True
    assert result["strict_correct"] is False
    assert result["budget_derived_dimension_changes"] == {}
    original = result["original_18000_score"]["dimensions"]
    assert all(result["dimensions"][k] == v for k, v in original.items() if k != "budget")


@pytest.mark.parametrize("mutation", ["permission", "literal_hash"])
def test_higher_budget_never_repairs_permission_or_literal_integrity(partial, mutation):
    with_complete_units(partial)
    if mutation == "permission":
        partial.task.rag_scope.corpora[0].document_ids = []
    else:
        next(iter(partial.payload["artifacts"].values()))["source"] = "PUBLIC_CORRUPTION"
    expected = "document authority differs" if mutation == "permission" else "evidence is missing"
    with pytest.raises(ValueError, match=expected):
        evaluate_partial(partial)


@pytest.mark.parametrize("field", ["authorization", "status", "numeric"])
def test_unrelated_dimension_change_is_evaluator_error_not_a_new_grade(partial, field):
    with_complete_units(partial)
    callback = partial_scorer(partial)
    calls = 0

    def drifting(*args):
        nonlocal calls
        calls += 1
        result = callback(*args)
        if calls == 2:
            if field == "authorization":
                result["dimensions"][field] = False
            else:
                result[field] = "PUBLIC_UNRELATED_CHANGE"
        return result

    with pytest.raises(scoring.ProfileScoringError, match="NON_BUDGET_SCORING_DRIFT"):
        evaluate_partial(partial, callback=drifting)


def test_plain_frozen_calls_stay_18k_during_profile_hook(partial):
    with_complete_units(partial)
    callback = partial_scorer(partial)
    entered, release = Event(), Event()
    calls = 0

    def paused(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            assert release.wait(5)
        return callback(*args)

    original_callable = scoring.legacy.original.score
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(evaluate_partial, partial, callback=paused)
        try:
            assert entered.wait(5)
            plain = callback(
                partial.task,
                partial.gold,
                partial.signing.sign_collection(partial.payload, partial.key),
                partial.key,
                partial.pins,
            )
            assert plain["strict_correct"] is False and plain["dimensions"]["budget"] is False
        finally:
            release.set()
        assert future.result(timeout=5)["strict_correct"] is True
    assert scoring.legacy.original.score is original_callable


def test_hook_and_context_restore_after_callback_exception(partial):
    with_complete_units(partial)
    original_callable = scoring.legacy.original.score
    callback = partial_scorer(partial)
    calls = 0

    def broken(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("PUBLIC_CALLBACK_FAILURE")
        return callback(*args)

    with pytest.raises(RuntimeError, match="PUBLIC_CALLBACK_FAILURE"):
        evaluate_partial(partial, callback=broken)
    assert scoring.legacy.original.score is original_callable
    assert evaluate_partial(partial)["strict_correct"] is True


def test_unrelated_scorer_cannot_claim_budget_profile_compatibility():
    result = {"strict_correct": True, "dimensions": {"business": True, "budget": True}}
    with pytest.raises(scoring.ProfileCompatibilityError, match="BASELINE_NOT_REACHED"):
        scoring.score_with_profile(
            None,
            None,
            signed(public_usage((1000,))),
            KEY,
            {},
            profile=profile36(),
            score_original=lambda *args: result,
        )
