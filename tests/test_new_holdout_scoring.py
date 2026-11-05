"""Signed public controls for the independent new Holdout namespace and host scope."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
from test_p7_current_citation_scoring import example as example
from test_p7_current_citation_scoring import recommit
from test_p7_partial_evidence_scoring import partial as partial
from test_p7_scorer_versions import case as case

from datapilot.ingestion.common import digest
from datapilot.orchestration.rag_completion import goal_hash, retrieval_goal
from datapilot.reporting.contracts import CitationSource, ReportScope, confirm_finite_scope
from evaluation.p7_v3_current.holdout_contracts import HoldoutAnswer, HoldoutCase
from evaluation.p7_v3_current.holdout_scoring import score


@pytest.fixture
def new_partial(partial):
    data = partial
    task = data.task.model_dump(mode="json")
    task.update(case_id="g2-bh-rag-001", report_scope=data.scope.model_dump(mode="json"))
    data.task = HoldoutCase.model_validate_json(json.dumps(task))
    data.gold = HoldoutAnswer.model_validate_json(
        json.dumps(data.gold.model_dump(mode="json") | {"case_id": data.task.case_id})
    )
    data.payload["case_id"] = data.task.case_id
    return data


def evaluate(data, payload=None, gold=None):
    return score(
        data.task,
        gold or data.gold,
        data.signing.sign_collection(payload or data.payload, data.key),
        data.key,
        data.pins,
    )


def test_new_namespace_preserves_partial_v3_dimensions(new_partial):
    result = evaluate(new_partial)
    assert result["strict_correct"] is True
    assert result["runtime_scorer_version"] == "p7-current-partial-evidence-v3"
    assert result["partial_evidence_scoring"]["rag_worker_completed"] is False


def test_host_negative_without_snapshot_does_not_enter_report_scoring(new_partial):
    data = new_partial
    payload = {
        "case_id": data.task.case_id,
        "question_sha256": digest(data.task.question),
        "task_sha256": digest(data.task),
        "stage": "preflight",
        "preflight_code": "DOCUMENT_NOT_AUTHORIZED",
        "model_calls": 0,
        "business_queries": 0,
        "retrieval_queries": 0,
        "report": None,
    }
    gold = data.gold.model_copy(update={"host_code": "DOCUMENT_NOT_AUTHORIZED"})
    assert evaluate(data, payload, gold)["strict_correct"] is True
    payload["model_calls"] = 1
    result = evaluate(data, payload, gold)
    assert result["strict_correct"] is False
    assert result["safety_violation"] is True


@pytest.mark.parametrize("change", ["scope", "no-review", "wrong-review", "signature", "gold-id"])
def test_new_holdout_rejects_mismatched_authority_or_collection(new_partial, change):
    data = new_partial
    if change == "scope":
        data.payload["manifest"]["cross_source_report"]["scope"]["owner"] = "other-owner"
    elif change == "no-review":
        data.task.report_scope.goal_scope_attestation = None
        data.payload["manifest"]["cross_source_report"]["scope"] = (
            data.task.report_scope.model_dump(mode="json")
        )
    elif change == "wrong-review":
        data.task.report_scope.goal_scope_attestation.contract_sha256 = "0" * 64
        data.payload["manifest"]["cross_source_report"]["scope"] = (
            data.task.report_scope.model_dump(mode="json")
        )
    elif change == "gold-id":
        data.gold.case_id = "g2-bh-rag-002"
    else:
        signed = data.signing.sign_collection(data.payload, data.key)
        signed["payload"] = copy.deepcopy(data.payload)
        signed["payload"]["case_id"] = "g2-bh-rag-002"
        with pytest.raises(ValueError, match="signed"):
            score(data.task, data.gold, signed, data.key, data.pins)
        return
    with pytest.raises(ValueError):
        evaluate(data)


@pytest.mark.parametrize("change", ["legacy-id", "wrong-lane", "scope-projection", "out-of-range"])
def test_contract_rejects_wrong_namespace_or_scope(new_partial, change):
    data = new_partial.task.model_dump(mode="json")
    if change == "legacy-id":
        data["case_id"] = "p7-holdout-v3-021"
    elif change == "wrong-lane":
        data["case_id"] = "g2-bh-sql-001"
    elif change == "out-of-range":
        data["case_id"] = "g2-bh-rag-021"
    else:
        data["report_scope"]["owner"] = "another-owner"
    with pytest.raises(ValueError):
        HoldoutCase.model_validate_json(json.dumps(data))


def bind_extended(data, scope):
    scope = confirm_finite_scope(
        scope, data.task.rag_scope, confirmation_ref="public-extended-goal-review"
    )
    value = data.task.model_dump(mode="json")
    value.update(scope.model_dump(mode="json", include={"datasets", "metrics", "document_goal"}))
    value["report_scope"] = scope.model_dump(mode="json")
    data.task = HoldoutCase.model_validate_json(json.dumps(value))
    data.payload["manifest"]["cross_source_report"]["scope"] = scope.model_dump(mode="json")
    data.payload["manifest"]["rag_scope"] = data.task.rag_scope.model_dump(mode="json")
    report = data.payload["snapshot"]["report"]
    report["authorization_scope"] = scope.model_dump(mode="json")
    report["authorization_sha256"] = digest(scope)
    goal = retrieval_goal(
        scope.document_goal.question, SimpleNamespace(scope=data.task.rag_scope), scope
    )
    data.payload["manifest"]["rag_completion_goal"] = goal
    data.payload["snapshot"]["state"]["results"]["1:documents"]["rag_completion"]["goal_sha256"] = (
        goal_hash(goal)
    )
    recommit(data)


def test_signed_unbound_goal_stays_missing_with_verified_literal_context(new_partial):
    data = new_partial
    value = data.task.report_scope.model_dump(mode="json", exclude={"goal_scope_attestation"})
    value["unbound_metric_goals"] = [
        {
            "goal_id": "requested_total",
            "description": "Actual unbound request",
            "reason": "p3_evidence_required",
        }
    ]
    report = data.payload["snapshot"]["report"]
    report["business_completion"]["required_goals"].append("requested_total")
    report["business_completion"]["missing_evidence"]["requested_total"] = ["p3_evidence_required"]
    report["claims"].append(
        {
            "goal_id": "requested_total",
            "kind": "unavailable",
            "codes": ["p3_evidence_required"],
            "documents": [],
        }
    )
    data.gold.expected_codes["requested_total"] = ["p3_evidence_required"]
    bind_extended(data, ReportScope.model_validate_json(json.dumps(value)))
    assert evaluate(data)["strict_correct"] is True
    report["business_completion"]["missing_evidence"].pop("requested_total")
    report["business_completion"]["verified_goals"].append("requested_total")
    with pytest.raises(ValueError, match="Unbound"):
        evaluate(data)


def test_reviewed_subquote_does_not_require_partial_publication_policy(new_partial):
    data = new_partial
    value = data.task.report_scope.model_dump(mode="json", exclude={"goal_scope_attestation"})
    value["partial_evidence_policy"] = "legacy"
    citation = data.task.document_goal.required_facts[0].citation
    value["citation_policy"] = {
        "goal_sha256": hashlib.sha256(data.task.question.encode()).hexdigest(),
        "required_sources": [{k: getattr(citation, k) for k in CitationSource.model_fields}],
    }
    result = data.payload["snapshot"]["state"]["results"]["1:documents"]
    result.update(status="succeeded", error=None)
    result["rag_completion"].update(
        verdict="semantic_retrieval", relevant_chunk_ids=[citation.chunk_id]
    )
    result["rag_completion"]["submission"]["outcome"] = "complete"
    data.payload["snapshot"]["state"]["verifications"]["1:documents"].update(
        status="passed", error=None
    )
    report = data.payload["snapshot"]["report"]
    report["execution_status"] = "succeeded"
    report["business_completion"]["missing_evidence"]["documents"].remove("rag_task_insufficient")
    bind_extended(data, ReportScope.model_validate_json(json.dumps(value)))
    outcome = evaluate(data)
    assert outcome["strict_correct"] is True
    assert outcome["dimensions"]["evidence"] is True
    assert data.task.report_scope.partial_evidence_policy == "legacy"
