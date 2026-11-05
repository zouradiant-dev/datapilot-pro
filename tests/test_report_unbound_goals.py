"""Real missing requests and required citations remain distinct from verified results."""

import copy
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_cross_dataset_document_facts import bridge_case as bridge_case
from test_cross_dataset_document_facts import combined as combined
from test_cross_dataset_document_facts import reconfirm
from test_document_fact_coverage import fact, synthetic
from test_semantics import semantic_case as semantic_case

from datapilot.reporting.adapter import finalize
from datapilot.reporting.contracts import (
    BusinessCompletion,
    CrossSourceReport,
    ReportScope,
    UnboundMetricGoal,
    confirm_finite_scope,
)


def test_actual_unbound_request_is_required_without_creating_a_worker(combined):
    service, pairs, retrieval, metric = combined
    service.scope.unbound_metric_goals = [
        UnboundMetricGoal(
            goal_id="unconfirmed_metric",
            description="A separate net settlement request",
            reason="definition_missing",
        )
    ]
    reconfirm(combined)
    report = service.build(pairs, retrieval)
    assert report.business_completion.status == "partial"
    assert report.business_completion.missing_evidence["unconfirmed_metric"] == [
        "definition_missing"
    ]
    assert "unconfirmed_metric" not in {g["task_id"] for g in service.plan_menu()}
    assert not any(c.metric for c in report.claims if c.goal_id == "unconfirmed_metric")
    assert report.business_completion.verified_goals == [metric.request.goal_id, "documents"]
    service.verify_report(report, pairs, retrieval)


def test_document_only_request_keeps_missing_p3_goal_without_promoting_a_quote(settings):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    service.scope.document_goal.required_facts = [fact(pairs, "rule", "按月复核角色权限")]
    service.scope.unbound_metric_goals = [
        UnboundMetricGoal(
            goal_id="requested_number", description="Requested total", reason="p3_evidence_required"
        )
    ]
    service.scope = confirm_finite_scope(
        service.scope, retrieval.scope, confirmation_ref="public-review"
    )
    report = service.build(pairs, retrieval)
    assert report.business_completion.status == "partial"
    assert report.business_completion.required_goals == ["documents", "requested_number"]
    assert report.business_completion.verified_goals == ["documents"]
    assert not report.charts and not any(c.kind == "metric" for c in report.claims)
    assert report.business_completion.missing_evidence["requested_number"] == [
        "p3_evidence_required"
    ]


def test_required_evidence_survives_missing_metric_without_business_promotion(combined):
    service, pairs, retrieval, metric = combined
    service.scope.document_goal.evidence_only = True
    reconfirm(combined)
    documents = [(ref, artifact) for ref, artifact in pairs if artifact.kind == "documents"]
    report = service.build(documents, retrieval)
    assert report.business_completion.status == "unavailable"
    assert report.business_completion.verified_goals == []
    assert report.business_completion.satisfied_evidence_goals == ["documents"]
    assert report.business_completion.required_goals == [metric.request.goal_id, "documents"]
    assert report.business_completion.missing_evidence == {
        metric.request.goal_id: ["metric_evidence_missing"]
    }
    context = next(c for c in report.claims if c.kind == "context")
    assert context.documents and all(context.fact_coverage.values())
    assert report.charts == []
    service.verify_report(report, documents, retrieval)


def test_required_evidence_is_still_required_when_metric_passes(combined):
    service, pairs, retrieval, metric = combined
    service.scope.document_goal.evidence_only = True
    reconfirm(combined)
    complete = service.build(pairs, retrieval)
    assert complete.business_completion.status == "completed"
    assert complete.business_completion.verified_goals == [metric.request.goal_id]
    assert complete.business_completion.satisfied_evidence_goals == ["documents"]
    metrics_only = [(ref, artifact) for ref, artifact in pairs if artifact.kind == "metric"]
    missing = service.build(metrics_only, retrieval)
    assert missing.business_completion.status == "partial"
    assert missing.business_completion.satisfied_evidence_goals == []
    assert "documents" in missing.business_completion.missing_evidence


def test_satisfied_evidence_cannot_substitute_a_different_quote(combined):
    service, pairs, retrieval, _ = combined
    service.scope.document_goal.evidence_only = True
    reconfirm(combined)
    documents = [(ref, artifact) for ref, artifact in pairs if artifact.kind == "documents"]
    value = service.build(documents, retrieval).model_dump(mode="json")
    context = next(c for c in value["claims"] if c["kind"] == "context")
    next(iter(context["fact_coverage"].values()))["excerpt"] = "A different unsupported statement"
    with pytest.raises(ValidationError, match="literal proof"):
        CrossSourceReport.model_validate_json(json.dumps(value))


@pytest.mark.parametrize("change", ["goal_omitted", "metric_promoted", "evidence_promoted"])
def test_extended_report_rejects_forged_goal_accounting(combined, change):
    service, pairs, retrieval, _ = combined
    service.scope.unbound_metric_goals = [
        UnboundMetricGoal(
            goal_id="pending", description="An actual pending metric", reason="definition_missing"
        )
    ]
    reconfirm(combined)
    report = service.build(pairs, retrieval).model_dump(mode="json")
    if change == "goal_omitted":
        report["business_completion"]["required_goals"].remove("pending")
        del report["business_completion"]["missing_evidence"]["pending"]
    else:
        del report["business_completion"]["missing_evidence"]["pending"]
        field = "verified_goals" if change == "metric_promoted" else "satisfied_evidence_goals"
        report["business_completion"].setdefault(field, []).append("pending")
    with pytest.raises(ValidationError):
        CrossSourceReport.model_validate_json(json.dumps(report))


@pytest.mark.parametrize(
    "change", ["duplicate", "reserved", "bad_reason", "evidence_without_metric"]
)
def test_host_contract_rejects_invalid_goal_declarations(combined, change):
    value = combined[0].scope.model_dump(mode="json")
    value["unbound_metric_goals"] = [
        {"goal_id": "pending", "description": "Missing request", "reason": "definition_missing"}
    ]
    if change == "duplicate":
        value["unbound_metric_goals"][0]["goal_id"] = "documents"
    elif change == "reserved":
        value["unbound_metric_goals"][0]["goal_id"] = "report"
    elif change == "bad_reason":
        value["unbound_metric_goals"][0]["reason"] = "verified"
    else:
        value["metrics"] = []
        value["document_goal"].update(
            evidence_only=True, metric_goals=[], question=value["question"]
        )
    with pytest.raises(ValidationError):
        ReportScope.model_validate_json(json.dumps(value))


def test_blocked_adapter_preserves_unbound_goal(combined):
    service = combined[0]
    service.scope.unbound_metric_goals = [
        UnboundMetricGoal(
            goal_id="pending", description="Missing request", reason="definition_missing"
        )
    ]
    engine = SimpleNamespace(reporting=service)
    result = finalize(engine, {}, "failed")
    assert "pending" in result["business_completion"].required_goals
    assert "pending" in result["business_completion"].missing_evidence


def test_default_projection_retains_historical_bytes(combined):
    scope = combined[0].scope
    value = scope.model_dump(mode="json")
    assert "unbound_metric_goals" not in value
    assert "evidence_only" not in value["document_goal"]
    completion = BusinessCompletion(
        status="unavailable", required_goals=["metric"], verified_goals=[]
    )
    assert "satisfied_evidence_goals" not in completion.model_dump(mode="json")
    assert (
        ReportScope.model_validate_json(json.dumps(copy.deepcopy(value))).model_dump(mode="json")
        == value
    )
