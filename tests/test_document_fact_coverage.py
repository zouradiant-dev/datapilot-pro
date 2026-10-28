"""Public synthetic host fact contracts; source/relevance doubles, no paid or database calls."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_cross_source_report import bridge_case as bridge_case
from test_report_causal_scope import document_case
from test_semantics import semantic_case as semantic_case

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact
from datapilot.orchestration.runtime import ArtifactStore, text_hash
from datapilot.reporting.contracts import DocumentGoal


def synthetic(
    settings, *, text="审计日志条款：本文未规定保存年限。管理员按月复核角色权限。", purpose=None
):
    service, pairs, retrieval = document_case(settings, "审计日志必须保留多少年？")
    service.scope.document_goal.purpose = purpose
    result = pairs[0][1].documents.model_copy(deep=True)
    doc = result.documents[0]
    doc.text, doc.sha256, doc.version = text, text_hash(text), text_hash(text)
    doc.document_id = doc.sha256
    doc.citation.chunk_id = doc.sha256
    doc.citation.sha256 = doc.sha256
    doc.citation.source_sha256 = doc.sha256
    doc.citation.version = doc.sha256
    doc.citation.end = len(text)
    store = ArtifactStore("public-document-facts")
    ref = store.put(
        Artifact(
            run_id=store.run_id,
            task_id="documents",
            plan_version=1,
            kind="documents",
            source="explicit-source-double",
            documents=result,
        )
    )

    def validate(value):
        if value != result:
            raise AgentFailure("DOCUMENT_CORRUPT", "Synthetic citation or payload changed")

    retrieval.validate_result = validate
    return service, [(ref, store.get(ref))], retrieval


def fact(pairs, id_="retention", quote=None):
    from datapilot.reporting.contracts import DocumentFact

    kwargs = {}
    if quote is not None:
        kwargs = {
            "citation": pairs[0][1].documents.documents[0].citation.model_copy(deep=True),
            "quotation": quote,
            "confirmation_ref": "public-host-fixture-not-human-signature-v1",
        }
    return DocumentFact(fact_id=id_, description="Host-defined synthetic document fact", **kwargs)


def test_legacy_unconfirmed_goal_cannot_complete_from_related_background(settings):
    service, pairs, retrieval = synthetic(settings)
    report = service.build(pairs, retrieval)
    assert report.business_completion.status == "unavailable"
    assert report.business_completion.verified_goals == []
    assert report.business_completion.missing_evidence["documents"] == ["document_goal_unconfirmed"]
    assert report.claims[0].kind == "context"


def test_missing_year_keeps_background_without_verifying_required_fact(settings):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    service.scope.document_goal.required_facts = [fact(pairs)]
    report = service.build(pairs, retrieval)
    assert report.business_completion.status == "unavailable"
    assert report.business_completion.verified_goals == []
    assert report.claims[0].fact_coverage == {"retention": None}
    assert (
        "document_fact_unverified:retention"
        in report.business_completion.missing_evidence["documents"]
    )
    assert report.business_completion.limited_results_visible and not report.charts


def test_reviewed_literal_year_is_supported_without_becoming_p3_metric(settings):
    service, pairs, retrieval = synthetic(
        settings, text="审计日志条款：本合成文档规定保存七年。", purpose="facts"
    )
    service.scope.document_goal.required_facts = [fact(pairs, quote="保存七年")]
    report = service.build(pairs, retrieval)
    assert report.business_completion.status == "completed"
    assert report.claims[0].fact_coverage["retention"].excerpt == "保存七年"
    assert not report.charts and all(c.metric is None for c in report.claims)
    service.verify_report(report, pairs, retrieval)


def test_explicit_document_non_specification_is_a_distinct_supported_fact(settings):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    service.scope.question = service.scope.document_goal.question = "文档是否规定日志保存年限？"
    service.scope.document_goal.required_facts = [
        fact(pairs, "policy_presence", "本文未规定保存年限")
    ]
    report = service.build(pairs, retrieval)
    assert report.business_completion.status == "completed"
    assert report.claims[0].fact_coverage["policy_presence"].excerpt == "本文未规定保存年限"


@pytest.mark.parametrize("purpose", ["locate", "summary"])
def test_explicit_locator_or_summary_needs_no_numeric_fields(settings, purpose):
    service, pairs, retrieval = synthetic(settings, purpose=purpose)
    report = service.build(pairs, retrieval)
    assert report.business_completion.status == "completed"
    assert not report.claims[0].fact_coverage


def test_two_required_facts_preserve_verified_part_and_mark_missing(settings):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    service.scope.document_goal.required_facts = [
        fact(pairs, "review_frequency", "按月复核角色权限"),
        fact(pairs),
    ]
    report = service.build(pairs, retrieval)
    assert report.business_completion.status == "partial"
    assert not report.business_completion.verified_goals
    assert report.claims[0].fact_coverage["review_frequency"] is not None
    assert report.claims[0].fact_coverage["retention"] is None
    assert report.business_completion.missing_evidence["documents"] == [
        "document_fact_unverified:retention"
    ]


def test_multiple_related_sources_do_not_replace_a_missing_fact(settings):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    result = pairs[0][1].documents.model_copy(deep=True)
    other = result.documents[0].model_copy(deep=True)
    other.text = "权限归档相关背景，另一本合成文档也不提供保存期限。"
    other.sha256 = other.document_id = text_hash(other.text)
    other.citation.chunk_id = other.citation.sha256 = other.citation.source_sha256 = other.sha256
    other.citation.version = other.sha256
    other.citation.source_id, other.citation.document_id = "f" * 64, "d" * 64
    other.citation.end = len(other.text)
    result.documents.append(other)
    corpus = other.citation.corpus_id
    retrieval.scope.corpora[0].document_ids.append(other.citation.document_id)
    retrieval.manifests[corpus].sources.append(
        SimpleNamespace(source_id=other.citation.source_id, name="other.md")
    )

    def validate(value):
        assert value == result  # Explicit two-source unit double only.

    retrieval.validate_result = validate
    store = ArtifactStore("public-two-sources")
    ref = store.put(
        Artifact(
            run_id=store.run_id,
            task_id="documents",
            plan_version=1,
            kind="documents",
            source="explicit-two-source-double",
            documents=result,
        )
    )
    pairs = [(ref, store.get(ref))]
    service.scope.question = service.scope.document_goal.question = "至少两份文档说明日志保存年限。"
    service.scope.document_goal.required_facts = [fact(pairs)]
    report = service.build(pairs, retrieval)
    assert len(report.claims[0].documents) == 2
    assert report.business_completion.status == "unavailable"
    assert not report.business_completion.verified_goals


def test_verified_p3_metric_is_preserved_when_document_fact_missing(settings, bridge_case):
    service, bridge, metric_inputs = bridge_case
    documents, pairs, retrieval = synthetic(
        settings, text="账单收入归档条款：未规定具体保存期限。", purpose="facts"
    )
    documents.scope.document_goal.required_facts = [fact(pairs)]
    documents.scope.document_goal.metric_goals = [bridge.request.goal_id]
    service.scope.document_goal = documents.scope.document_goal
    report = service.build(metric_inputs + pairs, retrieval)
    assert report.business_completion.status == "partial"
    assert report.business_completion.verified_goals == [bridge.request.goal_id]
    assert report.claims[0].metric == bridge and report.charts[0].points[0].metric == bridge
    assert report.business_completion.missing_evidence["documents"] == [
        "document_fact_unverified:retention"
    ]


@pytest.mark.parametrize("causal", [True, False])
def test_causal_host_flag_unchanged_for_supported_summary(settings, causal):
    service, pairs, retrieval = synthetic(settings, purpose="summary")
    service.scope.causal_requested = causal
    report = service.build(pairs, retrieval)
    assert report.business_completion.status == ("partial" if causal else "completed")
    assert report.business_completion.unconfirmed_claims == (
        ["causal_conclusion_not_verified"] if causal else []
    )


def test_open_conclusion_remains_unverified_despite_related_document(settings):
    service, pairs, retrieval = synthetic(settings, purpose="conclusion")
    service.scope.causal_requested = True
    report = service.build(pairs, retrieval)
    assert report.business_completion.status == "partial"
    assert not report.business_completion.verified_goals
    assert report.business_completion.unconfirmed_claims == ["causal_conclusion_not_verified"]


@pytest.mark.parametrize(
    "field", ["index_version", "source_id", "version", "source_sha256", "sha256", "chunk_id"]
)
def test_wrong_fact_pin_is_not_verified(settings, field):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    proof = fact(pairs, quote="本文未规定保存年限")
    setattr(proof.citation, field, "0" * 64)
    service.scope.document_goal.required_facts = [proof]
    report = service.build(pairs, retrieval)
    assert report.business_completion.status == "unavailable"
    assert report.claims[0].fact_coverage["retention"] is None


def test_quote_must_be_present_not_just_reviewed_or_relevant(settings):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    service.scope.document_goal.required_facts = [fact(pairs, quote="保存七年")]
    assert service.build(pairs, retrieval).business_completion.status == "unavailable"


@pytest.mark.parametrize("failure", ["irrelevant", "no_source", "bad_citation", "bad_ref"])
def test_missing_or_invalid_authorized_evidence_never_covers_fact(settings, failure):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    service.scope.document_goal.required_facts = [fact(pairs, quote="本文未规定保存年限")]
    if failure == "irrelevant":
        retrieval.qualifying_documents = lambda *_: []
    elif failure == "no_source":
        pairs = []
    elif failure == "bad_citation":
        pairs[0][1].documents.documents[0].citation.sha256 = "0" * 64
    else:
        pairs[0][0].sha256 = "0" * 64
    if failure in {"bad_citation", "bad_ref"}:
        with pytest.raises(AgentFailure):
            service.build(pairs, retrieval)
    else:
        assert service.build(pairs, retrieval).business_completion.status == "unavailable"


def test_unavailable_source_receipt_cannot_be_promoted_even_with_reviewed_quote(settings):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    service.scope.document_goal.required_facts = [fact(pairs, quote="本文未规定保存年限")]
    report = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    assert report.business_completion.status == "unavailable"


@pytest.mark.parametrize("mutation", ["purpose", "empty_facts", "duplicate", "partial_proof"])
def test_invalid_host_contract_refused(settings, mutation):
    from datapilot.reporting.contracts import DocumentFact

    service, pairs, retrieval = synthetic(settings, purpose="facts")
    goal = service.scope.document_goal
    goal.required_facts = [fact(pairs)]
    if mutation == "purpose":
        goal.purpose = "invented"
    elif mutation == "empty_facts":
        goal.required_facts = []
    elif mutation == "duplicate":
        goal.required_facts = [fact(pairs), fact(pairs)]
    else:
        with pytest.raises(ValidationError):
            DocumentFact(fact_id="x", description="test", quotation="only text")
        return
    with pytest.raises(AgentFailure):
        service.build(pairs, retrieval)


def test_old_report_cannot_retain_completed_under_new_unknown_goal_rules(settings):
    service, pairs, retrieval = synthetic(settings)
    old = service.build(pairs, retrieval)
    old.business_completion.status = "completed"
    old.business_completion.verified_goals = ["documents"]
    old.business_completion.missing_evidence = {}
    with pytest.raises(AgentFailure):
        service.verify_report(old, pairs, retrieval)


def test_default_contract_bytes_and_artifact_hash_are_history_compatible():
    raw = {"goal_id": "documents", "question": "旧问题", "metric_goals": []}
    goal = DocumentGoal.model_validate(raw)
    assert goal.model_dump(mode="json") == raw and digest(goal) == digest(raw)


def test_scoped_fact_cannot_be_deleted_via_report_self_assertion(settings):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    service.scope.document_goal.required_facts = [fact(pairs)]
    report = service.build(pairs, retrieval)
    report.authorization_scope.document_goal.required_facts = []
    with pytest.raises((AgentFailure, ValidationError)):
        service.verify_report(report, pairs, retrieval)
