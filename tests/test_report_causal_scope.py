"""Public synthetic facts and retrieval doubles; no PG, embedding, provider or Holdout."""

import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_cross_source_report import bridge_case as bridge_case
from test_semantics import semantic_case as semantic_case

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetScope
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact, Document, SearchResult
from datapilot.orchestration.runtime import ArtifactStore
from datapilot.rag.contracts import ChunkCitation, CorpusPin, RagScope
from datapilot.reporting.contracts import DocumentGoal, ReportScope
from datapilot.reporting.service import ReportService, report_session


def document_case(settings, question, causal_requested=False):
    text = "公开合成公告：新增导出按钮，旧入口仍保留。这里只记录产品行为变化。"
    h = hashlib.sha256(text.encode()).hexdigest()
    corpus = str(uuid4())
    scope = ReportScope(
        question=question,
        datasets=DatasetScope(),
        metrics=[],
        document_goal=DocumentGoal(
            goal_id="documents", question=question, metric_goals=[], purpose="summary"
        ),
        causal_requested=causal_requested,
    )
    rag_scope = RagScope(
        owner=scope.owner,
        allow_saas=True,
        corpora=[
            CorpusPin(corpus_id=corpus, index_version="a" * 64, document_ids=["c" * 64]),
        ],
    )
    citation = ChunkCitation(
        chunk_id=h,
        start=0,
        end=len(text),
        line_start=1,
        line_end=1,
        sha256=h,
        corpus_id=corpus,
        index_version="a" * 64,
        source_id="b" * 64,
        document_id="c" * 64,
        version=h,
        source_sha256=h,
        model_revision="d" * 40,
        chunker_sha256="e" * 64,
        score=0.9,
    )
    result = SearchResult(
        documents=[
            Document(
                document_id=h,
                source="public-phase2.md",
                version=h,
                text=text,
                sha256=h,
                citation=citation,
            )
        ],
        fixture=True,
    )

    def validate(value):
        assert value == result  # Explicit unit double, not a claim of real RAG validation.

    retrieval = SimpleNamespace(
        scope=rag_scope,
        authority_context=lambda: {"rag_scope_sha256": digest(rag_scope)},
        validate_result=validate,
        qualifying_documents=lambda docs, goal: docs,
        manifests={
            corpus: SimpleNamespace(
                sources=[SimpleNamespace(source_id="b" * 64, name="public-phase2.md")],
                target=SimpleNamespace(dataset_id=None),
            )
        },
    )
    store = ArtifactStore("public-phase2")
    ref = store.put(
        Artifact(
            run_id="public-phase2",
            task_id="documents",
            plan_version=1,
            kind="documents",
            source="unit-fixture",
            documents=result,
        )
    )
    return ReportService(settings, scope, {}, {}, {}, {}), [(ref, store.get(ref))], retrieval


@pytest.mark.parametrize(
    "question",
    [
        "请摘录公告事实，不要宣称它证明了续订提升的因果关系。",
        "只总结公开资料，不要求证明产品变化导致收入提升。",
        "Summarize documented changes; do not claim proof of causal improvement.",
    ],
)
def test_explicit_no_causality_is_not_overridden_by_keywords(settings, question):
    service, inputs, retrieval = document_case(settings, question, False)
    report = service.build(inputs, retrieval)
    assert report.business_completion.status == "completed"
    assert not report.business_completion.unconfirmed_claims
    assert report.claims[0].kind == "context" and not report.charts
    assert "不证明因果" in report.markdown
    service.verify_report(report, inputs, retrieval)


@pytest.mark.parametrize(
    "question",
    [
        "请证明产品发布导致客户续订提升。",
        "请总结公开公告中的变化。",  # Structured host goal wins even without causal keywords.
        "不要宣称产品变化已证明收入提升。",  # Conflicting text cannot weaken an explicit True.
    ],
)
def test_host_causal_goal_stays_unverified(settings, question):
    service, inputs, retrieval = document_case(settings, question, True)
    report = service.build(inputs, retrieval)
    assert report.business_completion.status == "partial"
    assert report.business_completion.unconfirmed_claims == ["causal_conclusion_not_verified"]
    assert report.claims[0].kind == "context"


def test_ordinary_document_fact_summary_completes(settings):
    service, inputs, retrieval = document_case(settings, "请根据公开公告总结功能入口变化。")
    report = service.build(inputs, retrieval)
    service.verify_report(report, inputs, retrieval)
    assert report.business_completion.status == "completed"


@pytest.mark.parametrize("causal", [False, True])
def test_missing_facts_still_cannot_complete(settings, causal):
    service, _, retrieval = document_case(
        settings, "请总结公告事实，不得将描述当作因果证明。", causal
    )
    report = service.build([], retrieval)
    assert report.business_completion.status == "unavailable"
    assert report.business_completion.missing_evidence
    assert not report.business_completion.verified_goals


def test_verified_metric_with_missing_document_fact_stays_partial(settings, bridge_case):
    service, bridge, inputs = bridge_case
    question = "查看收入及公告事实，不要把描述当作因果证明。"
    service.scope.question = question
    service.scope.causal_requested = False
    service.scope.document_goal = DocumentGoal(
        goal_id="documents",
        question=question,
        metric_goals=[bridge.request.goal_id],
    )
    _, _, retrieval = document_case(settings, question)
    report = service.build(inputs, retrieval)
    assert report.business_completion.status == "partial"
    assert report.business_completion.missing_evidence
    assert report.claims[0].metric.verification.verdict == "verified"
    assert not report.business_completion.unconfirmed_claims


@pytest.mark.parametrize("bad", [None, "false", 0])
def test_invalid_host_causal_field_fails_closed(settings, bad):
    service, inputs, retrieval = document_case(settings, "请总结公开公告中的事实。")
    service.scope.causal_requested = bad  # Simulate a bypassed/mutated host DTO.
    with pytest.raises(AgentFailure, match="Host report scope"):
        service.build(inputs, retrieval)


def test_missing_scope_fails_closed(settings):
    service, inputs, retrieval = document_case(settings, "请总结公开公告中的事实。")
    service.scope = None
    with pytest.raises(AgentFailure, match="Host report scope"):
        service.build(inputs, retrieval)


async def test_absent_report_session_does_not_create_trusted_report(settings):
    async with report_session(settings, None, "没有报告授权", "local-user") as reporting:
        assert reporting is None


def test_report_cannot_replace_host_causal_flag(settings):
    service, inputs, retrieval = document_case(settings, "请证明产品变化改善了客户续订。", True)
    report = service.build(inputs, retrieval)
    report.authorization_scope.causal_requested = False
    with pytest.raises(AgentFailure):
        service.verify_report(report, inputs, retrieval)


@pytest.mark.parametrize("bad", [None, "false", 0])
def test_host_contract_rejects_non_boolean_causality(settings, bad):
    service, _, _ = document_case(settings, "请总结公开公告中的事实。")
    data = service.scope.model_dump()
    data["causal_requested"] = bad
    with pytest.raises(ValidationError):
        ReportScope.model_validate(data)
