"""New synthetic publication contracts, without editing original evaluation results."""

import copy

from test_document_fact_coverage import fact, synthetic

from datapilot.reporting.contracts import UnboundMetricGoal, confirm_finite_scope
from evaluation.p7_v3_current.partial_evidence_scope import confirm_document_evidence


def reviewed(settings):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    service.scope.document_goal.required_facts = [fact(pairs, "review", "按月复核角色权限")]
    return service, pairs, retrieval


def test_insufficient_background_survives_while_unbound_number_is_refused(settings):
    service, pairs, retrieval = reviewed(settings)
    service.scope.unbound_metric_goals = [
        UnboundMetricGoal(
            goal_id="requested_number",
            description="需另行验证的实际账单金额",
            reason="p3_evidence_required",
        )
    ]
    original = copy.deepcopy(service.scope)
    service.scope = confirm_document_evidence(
        service.scope, retrieval.scope, confirmation_ref="public-unbound-number-and-document-review"
    )
    assert original.document_explanation_policy == "legacy"
    report = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    assert report.business_completion.status == "partial"
    context = next(c for c in report.claims if c.goal_id == "documents")
    assert context.documents and context.fact_coverage["review"]
    assert any(m.code == "rag_task_insufficient" for m in context.evidence_explanations)
    assert report.business_completion.missing_evidence["requested_number"] == [
        "p3_evidence_required"
    ]
    assert not report.charts and all(c.metric is None for c in report.claims)
    assert "requested_number" not in report.business_completion.verified_goals
    service.verify_report(report, pairs, retrieval, source_statuses={"documents": "unavailable"})


def test_missing_document_evidence_does_not_invent_a_conflict_reason(settings):
    service, _, retrieval = reviewed(settings)
    service.scope = confirm_document_evidence(
        service.scope, retrieval.scope, confirmation_ref="public-empty-evidence-explanation-review"
    )
    report = service.build([], retrieval, source_statuses={"documents": "unavailable"})
    assert report.business_completion.status == "unavailable"
    message = " ".join(m.message for c in report.claims for m in c.missing_requirements)
    assert "尚未取得" in message and "无法确定" in message
    assert "冲突" not in message and "优先级" not in message
    assert not any(c.documents for c in report.claims)


def test_quoted_statements_do_not_become_a_resolved_conclusion(settings):
    service, pairs, retrieval = reviewed(settings)
    service.scope.document_goal.purpose = "conclusion"
    service.scope = confirm_document_evidence(
        service.scope, retrieval.scope, confirmation_ref="public-quoted-but-unresolved-review"
    )
    report = service.build(pairs, retrieval, source_statuses={"documents": "succeeded"})
    assert report.business_completion.status == "partial"
    claim = report.claims[0]
    assert claim.documents and any(
        m.code == "document_conclusion_unverified" for m in claim.evidence_explanations
    )
    assert "尚不足以确定" in report.markdown


def test_default_policy_preserves_old_projection_and_message_behavior(settings):
    service, pairs, retrieval = reviewed(settings)
    service.scope = confirm_finite_scope(
        service.scope, retrieval.scope, confirmation_ref="public-legacy-document-review"
    )
    assert "document_explanation_policy" not in service.scope.model_dump(mode="json")
    report = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    assert report.business_completion.status == "unavailable"
    assert not any(c.documents for c in report.claims)


def test_partial_fact_explanation_preserves_detailed_business_missing_codes(settings):
    from datapilot.reporting.contracts import DocumentFact

    service, pairs, retrieval = reviewed(settings)
    service.scope.document_goal.required_facts.append(
        DocumentFact(fact_id="missing_time", description="仍缺少时长证明")
    )
    service.scope = confirm_document_evidence(
        service.scope, retrieval.scope, confirmation_ref="public-partial-fact-explanation"
    )
    report = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    assert report.business_completion.status == "partial"
    assert (
        "document_fact_unverified:missing_time"
        in report.business_completion.missing_evidence["documents"]
    )
    assert any(m.code == "document_fact_unverified" for m in report.claims[0].evidence_explanations)
    service.verify_report(report, pairs, retrieval, source_statuses={"documents": "unavailable"})
