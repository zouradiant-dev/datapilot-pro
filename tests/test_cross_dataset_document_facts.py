"""Independent policy facts keep their own grants and cannot repair metric evidence."""

import hashlib
import json

import pytest
from test_cross_source_report import bridge_case as bridge_case
from test_semantics import semantic_case as semantic_case
from test_trusted_goal_scope import DATA, public_case

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding, DatasetScope
from datapilot.rag.contracts import Target
from datapilot.reporting.contracts import ReportScope, confirm_finite_scope
from evaluation.p7_v3_current.final50_scope_repair import confirm_independent_policy

DOCUMENT_DATASET = "00000000-0000-4000-8000-000000000099"


@pytest.fixture
def combined(settings, bridge_case):
    service, metric, metric_pairs = bridge_case
    doc_service, doc_pairs, retrieval = public_case(settings, DATA[0])
    value = doc_service.scope.model_dump(mode="json", exclude={"goal_scope_attestation"})
    value["question"] = "核验已支付收入，同时引用独立政策事实；政策不证明收入数字。"
    value["metrics"] = [metric.request.model_dump(mode="json")]
    value["datasets"] = DatasetScope(
        bindings=[
            *service.scope.datasets.bindings,
            DatasetBinding(dataset_id=DOCUMENT_DATASET, version=1),
        ]
    ).model_dump(mode="json")
    value["document_goal"]["metric_goals"] = [metric.request.goal_id]
    value["document_goal"]["independent_facts"] = True
    value["citation_policy"]["goal_sha256"] = hashlib.sha256(value["question"].encode()).hexdigest()
    scope = ReportScope.model_validate_json(json.dumps(value))
    retrieval.scope.datasets = scope.datasets.model_copy(deep=True)
    retrieval.scope.allow_saas = False
    for corpus, manifest in retrieval.manifests.items():
        manifest.target = Target(
            corpus_id=corpus, owner=scope.owner, dataset_id=DOCUMENT_DATASET, dataset_version=1
        )
    service.scope = confirm_finite_scope(
        scope, retrieval.scope, confirmation_ref="public-reviewed-cross-dataset-policy-facts"
    )
    return service, [*metric_pairs, *doc_pairs], retrieval, metric


def build(combined):
    service, pairs, retrieval, metric = combined
    return service.build(
        pairs,
        retrieval,
        source_statuses={metric.request.goal_id: "succeeded", "documents": "succeeded"},
    )


def reconfirm(combined):
    service, _, retrieval, _ = combined
    service.scope = confirm_finite_scope(
        service.scope, retrieval.scope, confirmation_ref="public-reviewed-contract-change"
    )


def test_independent_cross_dataset_policy_and_metric_remain_separate(combined):
    service, pairs, retrieval, metric = combined
    report = build(combined)
    assert report.business_completion.status == "completed"
    assert next(c for c in report.claims if c.kind == "metric").metric == metric
    doc = next(c for c in report.claims if c.kind == "context")
    assert doc.related_metric_goals == [metric.request.goal_id]
    assert all(doc.fact_coverage.values())
    assert service.scope.document_goal.independent_facts is True
    service.verify_report(
        report,
        pairs,
        retrieval,
        source_statuses={metric.request.goal_id: "succeeded", "documents": "succeeded"},
    )


def test_default_metric_source_association_still_rejects_other_dataset(combined):
    combined[0].scope.document_goal.independent_facts = False
    reconfirm(combined)
    with pytest.raises(AgentFailure, match="metric Dataset/version"):
        build(combined)


@pytest.mark.parametrize("mutation", ["foreign_dataset", "foreign_version"])
def test_independent_facts_never_authorize_an_unlisted_source_dataset(combined, mutation):
    for manifest in combined[2].manifests.values():
        if mutation == "foreign_dataset":
            manifest.target.dataset_id = "00000000-0000-4000-8000-000000000098"
        else:
            manifest.target.dataset_version = 2
    with pytest.raises(AgentFailure):
        build(combined)


def test_independent_policy_cannot_replace_missing_metric_evidence(combined):
    service, pairs, retrieval, metric = combined
    docs_only = [(ref, artifact) for ref, artifact in pairs if artifact.kind == "documents"]
    report = service.build(docs_only, retrieval, source_statuses={"documents": "succeeded"})
    assert report.business_completion.status != "completed"
    assert metric.request.goal_id not in report.business_completion.verified_goals
    assert not any(c.kind == "metric" for c in report.claims)


def test_independent_policy_cannot_verify_causality(combined):
    combined[0].scope.causal_requested = True
    reconfirm(combined)
    report = build(combined)
    assert report.business_completion.status == "partial"
    assert "causal_conclusion_not_verified" in report.business_completion.unconfirmed_claims


def test_dataset_scope_change_requires_new_host_confirmation(combined):
    service, _, retrieval, _ = combined
    retrieval.scope.datasets.bindings = [
        b for b in retrieval.scope.datasets.bindings if b.dataset_id == DOCUMENT_DATASET
    ]
    with pytest.raises(ValueError, match="exact authorized scope"):
        reconfirm(combined)
    with pytest.raises(AgentFailure):
        build(combined)


def test_host_repair_reuses_only_existing_report_grants(combined):
    service, _, retrieval, _ = combined
    old = service.scope.model_copy(deep=True)
    retrieval.scope.datasets.bindings = [
        b for b in retrieval.scope.datasets.bindings if b.dataset_id == DOCUMENT_DATASET
    ]
    scope, rag = confirm_independent_policy(
        old, retrieval.scope, confirmation_ref="public-reviewed-policy-scope-repair"
    )
    assert scope.datasets == rag.datasets == old.datasets
    assert scope.metrics == old.metrics and scope.question == old.question
    assert scope.document_goal.metric_goals == old.document_goal.metric_goals
    assert scope.document_goal.required_facts == old.document_goal.required_facts
    assert scope.goal_scope_attestation.confirmation_ref == "public-reviewed-policy-scope-repair"


def test_host_repair_cannot_import_unapproved_rag_grants(combined):
    service, _, retrieval, _ = combined
    retrieval.scope.datasets.bindings.append(
        DatasetBinding(dataset_id="00000000-0000-4000-8000-000000000098", version=1)
    )
    with pytest.raises(ValueError, match="report-authorized datasets"):
        confirm_independent_policy(service.scope, retrieval.scope, confirmation_ref="invalid-grant")


def test_host_repair_cannot_fill_missing_fact_proof(combined):
    service, _, retrieval, _ = combined
    fact = service.scope.document_goal.required_facts[0]
    fact.citation = fact.quotation = fact.confirmation_ref = None
    with pytest.raises(ValueError, match="reviewed facts"):
        confirm_independent_policy(service.scope, retrieval.scope, confirmation_ref="missing-fact")
