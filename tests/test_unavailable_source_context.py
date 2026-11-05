"""An insufficient document may be quoted without satisfying any requested fact."""

import json

import pytest
from pydantic import ValidationError
from test_document_fact_coverage import fact, synthetic

from datapilot.contracts import AgentFailure
from datapilot.reporting.contracts import ReportScope, confirm_finite_scope


def context_case(settings):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    service.scope.document_goal.required_facts = [fact(pairs)]
    service.scope.document_goal.retain_source_context = True
    service.scope.partial_evidence_policy = "partial-facts-v1"
    service.scope = confirm_finite_scope(
        service.scope, retrieval.scope, confirmation_ref="public-source-context-review"
    )
    return service, pairs, retrieval


def test_insufficient_context_keeps_quote_without_business_credit(settings):
    service, pairs, retrieval = context_case(settings)
    report = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    assert report.business_completion.status == "unavailable"
    assert report.business_completion.verified_goals == []
    assert report.business_completion.satisfied_evidence_goals == []
    claim = report.claims[0]
    assert claim.kind == "context" and claim.documents
    assert claim.fact_coverage == {"retention": None}
    assert claim.documents[0].excerpt == pairs[0][1].documents.documents[0].text
    assert (
        "document_fact_unverified:retention"
        in report.business_completion.missing_evidence["documents"]
    )
    assert "rag_task_insufficient" in report.business_completion.missing_evidence["documents"]
    assert not report.charts
    service.verify_report(report, pairs, retrieval, source_statuses={"documents": "unavailable"})


@pytest.mark.parametrize("status", ["failed", "blocked", "cancelled", "missing"])
def test_unaccepted_dependencies_cannot_supply_context(settings, status):
    service, pairs, retrieval = context_case(settings)
    report = service.build(
        pairs, retrieval, source_statuses={} if status == "missing" else {"documents": status}
    )
    assert not any(c.documents for c in report.claims)
    assert report.business_completion.status == (
        "unavailable" if status == "missing" else "blocked"
    )


def test_retained_context_still_checks_source_integrity(settings):
    service, pairs, retrieval = context_case(settings)
    pairs[0][0].sha256 = "0" * 64
    with pytest.raises(AgentFailure):
        service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})


def test_source_context_cannot_bypass_snapshot_requirements(settings):
    service, pairs, retrieval = context_case(settings)
    service.scope.question = service.scope.document_goal.question = "按最新快照说明日志保存年限。"
    service.scope = confirm_finite_scope(
        service.scope, retrieval.scope, confirmation_ref="public-snapshot-review"
    )
    report = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    assert not any(c.documents for c in report.claims)
    assert report.business_completion.status == "unavailable"


def test_source_context_requires_explicit_host_policy(settings):
    service, _, _ = context_case(settings)
    value = service.scope.model_dump(mode="json")
    value.pop("partial_evidence_policy")
    with pytest.raises(ValidationError, match="explicit partial policy"):
        ReportScope.model_validate_json(json.dumps(value))


def test_default_document_contract_serialization_is_unchanged(settings):
    service, _, _ = synthetic(settings, purpose="facts")
    service.scope.document_goal.required_facts = [fact([])]
    assert "retain_source_context" not in service.scope.model_dump(mode="json")["document_goal"]
