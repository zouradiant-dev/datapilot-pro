"""Publication controls use public evidence doubles, never a private Fake Run."""

import copy
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
from evaluation.p7_v3_current.publication_admission import check_publication_expectation

DOCUMENT_DATASET = "00000000-0000-4000-8000-000000000097"


@pytest.fixture
def publication_case(settings, bridge_case):
    def make(
        *, same_dataset=False, topics=False, independent=True, evidence_only=True, causal=True
    ):
        service, metric, metric_pairs = bridge_case
        case = copy.deepcopy(DATA[0])
        if topics:
            case["source_quote"] = "Paid invoice policy: " + case["source_quote"]
        doc_service, doc_pairs, retrieval = public_case(settings, case)
        value = doc_service.scope.model_dump(mode="json", exclude={"goal_scope_attestation"})
        value["question"] = "核验收入并独立引用条款；无法证明因果关系时保留未验证。"
        value["metrics"] = [metric.request.model_dump(mode="json")]
        value["datasets"] = DatasetScope(
            bindings=[
                *service.scope.datasets.bindings,
                DatasetBinding(dataset_id=DOCUMENT_DATASET, version=1),
            ]
        ).model_dump(mode="json")
        value["causal_requested"] = causal
        value["document_goal"].update(
            metric_goals=[metric.request.goal_id],
            purpose="facts" if independent else "conclusion",
            independent_facts=independent,
            evidence_only=evidence_only,
        )
        value["citation_policy"]["goal_sha256"] = hashlib.sha256(
            value["question"].encode()
        ).hexdigest()
        scope = ReportScope.model_validate_json(json.dumps(value))
        retrieval.scope.datasets = scope.datasets.model_copy(deep=True)
        retrieval.scope.allow_saas = False
        for corpus, manifest in retrieval.manifests.items():
            manifest.target = Target(
                corpus_id=corpus,
                owner=scope.owner,
                dataset_id=metric.request.dataset_id if same_dataset else DOCUMENT_DATASET,
                dataset_version=1,
            )
        service.scope = confirm_finite_scope(
            scope, retrieval.scope, confirmation_ref="public-publication-admission-dev"
        )
        return service, [*metric_pairs, *doc_pairs], retrieval, metric

    return make


def admit(case, *, evidence=True, causal=True):
    service, pairs, retrieval, metric = case
    return check_publication_expectation(
        service,
        pairs,
        retrieval,
        source_statuses={metric.request.goal_id: "succeeded", "documents": "succeeded"},
        expected_status="partial" if causal or not evidence else "completed",
        expected_verified_goals={metric.request.goal_id},
        expected_evidence_goals={"documents"} if evidence else set(),
        expected_unconfirmed_claims={"causal_conclusion_not_verified"} if causal else set(),
    )


def reconfirm(case):
    service, _, retrieval, _ = case
    service.scope = confirm_finite_scope(
        service.scope, retrieval.scope, confirmation_ref="public-publication-contract-change"
    )


@pytest.mark.parametrize("same_dataset", [False, True])
@pytest.mark.parametrize("topics", [False, True])
def test_independent_evidence_publishes_without_becoming_causal_proof(
    publication_case, same_dataset, topics
):
    case = publication_case(same_dataset=same_dataset, topics=topics)
    report = admit(case)
    doc = next(claim for claim in report.claims if claim.kind == "context")
    assert doc.documents and all(doc.fact_coverage.values())
    assert report.business_completion.verified_goals == [case[3].request.goal_id]
    assert report.business_completion.satisfied_evidence_goals == ["documents"]


def test_retrieval_success_does_not_hide_an_unsatisfiable_publication_contract(publication_case):
    case = publication_case(same_dataset=True, independent=False, evidence_only=False)
    with pytest.raises(ValueError, match="required reviewed literal fact"):
        admit(case, evidence=False)


def test_genuine_conclusion_keeps_its_unverified_obligation(publication_case):
    case = publication_case(
        same_dataset=True, topics=True, independent=False, evidence_only=False, causal=False
    )
    report = admit(case, evidence=False, causal=False)
    assert (
        "document_conclusion_unverified" in report.business_completion.missing_evidence["documents"]
    )
    assert "documents" not in report.business_completion.verified_goals


def test_default_dependent_conclusion_still_rejects_other_dataset(publication_case):
    case = publication_case(independent=False, evidence_only=False)
    with pytest.raises(AgentFailure, match="metric Dataset/version"):
        admit(case, evidence=False)


@pytest.mark.parametrize("mutation", ["foreign_dataset", "foreign_version", "source_pin", "hash"])
def test_publication_integrity_failures_are_never_downgraded(publication_case, mutation):
    case = publication_case()
    service, pairs, retrieval, _ = case
    if mutation in {"foreign_dataset", "foreign_version"}:
        for manifest in retrieval.manifests.values():
            if mutation == "foreign_dataset":
                manifest.target.dataset_id = "00000000-0000-4000-8000-000000000096"
            else:
                manifest.target.dataset_version = 2
    elif mutation == "source_pin":
        service.scope.citation_policy.required_sources[0].source_sha256 = "0" * 64
        service.scope.document_goal.required_facts[0].citation.source_sha256 = "0" * 64
        reconfirm(case)
    else:
        next(artifact for _, artifact in pairs if artifact.documents).documents.documents[
            0
        ].text += "changed"
    with pytest.raises(AgentFailure):
        admit(case)


@pytest.mark.parametrize("mutation", ["fact_span", "required_artifact_missing", "old_attestation"])
def test_missing_publication_requirements_fail_admission(publication_case, mutation):
    case = publication_case()
    service, pairs, _, _ = case
    if mutation == "fact_span":
        service.scope.document_goal.required_facts[0].citation.end += 1
        reconfirm(case)
    elif mutation == "required_artifact_missing":
        pairs[:] = [(ref, artifact) for ref, artifact in pairs if artifact.kind != "documents"]
    else:
        service.scope.document_goal.evidence_only = False
    with pytest.raises((ValueError, AgentFailure)):
        admit(case)


def test_wrong_expected_completion_is_rejected_even_for_a_valid_report(publication_case):
    service, pairs, retrieval, metric = publication_case()
    with pytest.raises(ValueError, match="business status"):
        check_publication_expectation(
            service,
            pairs,
            retrieval,
            source_statuses={metric.request.goal_id: "succeeded", "documents": "succeeded"},
            expected_status="completed",
            expected_verified_goals={metric.request.goal_id},
            expected_evidence_goals={"documents"},
            expected_unconfirmed_claims=set(),
        )
