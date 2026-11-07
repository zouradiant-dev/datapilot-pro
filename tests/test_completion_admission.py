"""Independent synthetic protocol controls; no private cases or provider calls."""

from types import SimpleNamespace

import pytest

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetScope
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import (
    Artifact,
    BudgetLimits,
    Document,
    RagSubmission,
    SearchResult,
    TaskEnvelope,
    TaskSpec,
)
from datapilot.orchestration.rag_completion import (
    requirement_class,
    retrieval_goal,
    validate_submission,
)
from datapilot.orchestration.runtime import ArtifactStore, text_hash
from datapilot.rag.contracts import ChunkCitation, CorpusPin, RagScope
from datapilot.reporting.contracts import (
    CitationPolicy,
    CitationSource,
    DocumentFact,
    DocumentGoal,
    ReportScope,
    confirm_finite_scope,
)
from evaluation.p7_v3_current.completion_admission import check_retrieval_expectation


def witness(*, returned=(0, 1), related=True, classified=True):
    documents = []
    for i, text in enumerate(
        ("公开合成：工单每周归档。", "公开合成：值班记录逐日核对。", "额外合成来源。")
    ):
        h = text_hash(text)
        citation = ChunkCitation(
            chunk_id=h,
            start=0,
            end=len(text),
            line_start=1,
            line_end=1,
            sha256=h,
            corpus_id="00000000-0000-4000-8000-000000000017",
            index_version="a" * 64,
            source_id=digest(["source", i]),
            document_id=digest(["document", i]),
            version=h,
            source_sha256=h,
            model_revision="d" * 40,
            chunker_sha256="e" * 64,
            score=0.8,
        )
        documents.append(
            Document(
                document_id=h,
                source=f"sample-{i}.md",
                version=h,
                text=text,
                sha256=h,
                citation=citation,
            )
        )
    rag = RagScope(
        allow_saas=True,
        corpora=[
            CorpusPin(
                corpus_id=documents[0].citation.corpus_id,
                index_version="a" * 64,
                document_ids=[d.citation.document_id for d in documents],
            )
        ],
    )
    question = "说明工单归档与值班核对规则，以及未确认的恢复时长。"
    scope = ReportScope(
        question=question,
        datasets=DatasetScope(),
        metrics=[],
        document_goal=DocumentGoal(
            goal_id="documents",
            question=question,
            metric_goals=[],
            purpose="facts",
            required_facts=[
                DocumentFact(fact_id="missing_time", description="恢复时长尚无来源证明")
            ],
        ),
        citation_policy=CitationPolicy(
            goal_sha256=text_hash(question),
            required_sources=[
                CitationSource(**{k: getattr(d.citation, k) for k in CitationSource.model_fields})
                for d in documents[:2]
            ],
        )
        if classified
        else None,
    )
    scope = confirm_finite_scope(
        scope, rag, confirmation_ref="independent-synthetic-completion-review"
    )
    selected = SearchResult(documents=[documents[i] for i in returned], fixture=True)

    def validate(result):
        if result != selected:
            raise AgentFailure("DOCUMENT_CORRUPT", "Synthetic witness changed")

    retrieval = SimpleNamespace(
        scope=rag,
        validate_result=validate,
        qualifying_documents=lambda docs, _: docs if related else [],
    )
    store = ArtifactStore("completion-control")
    ref = store.put(
        Artifact(
            run_id=store.run_id,
            task_id="documents",
            plan_version=1,
            kind="documents",
            source="public-synthetic-completion-control",
            documents=selected,
        )
    )
    envelope = TaskEnvelope(
        run_id=store.run_id,
        parent_id=store.run_id,
        plan_version=1,
        task=TaskSpec(task_id="documents", worker="rag", instruction=question),
        allowed_tools=["search_documents", "submit_rag_result"],
        budget=BudgetLimits(),
    )
    goal = retrieval_goal(question, retrieval, scope)
    return envelope, store, [ref], retrieval, goal


@pytest.mark.parametrize(
    "returned,related,expected",
    [
        ((0, 1), True, "complete"),
        ((0, 1, 2), True, "complete"),
        ((0,), True, "insufficient"),
        ((0, 2), True, "insufficient"),
        ((0, 1), False, "insufficient"),
        ((), True, "unavailable"),
    ],
)
def test_independent_retrieval_truth_table(returned, related, expected):
    assert (
        check_retrieval_expectation(*witness(returned=returned, related=related), expected)
        == expected
    )


def test_missing_business_fact_does_not_change_retrieval_expectation():
    control = witness()
    with pytest.raises(ValueError, match="conflicts with Runtime witness complete"):
        check_retrieval_expectation(*control, "insufficient")


def test_missing_required_source_is_rejected_even_with_an_extra_source():
    env, store, refs, retrieval, goal = witness(returned=(0, 2))
    with pytest.raises(AgentFailure) as error:
        validate_submission(
            env,
            store,
            refs,
            RagSubmission(artifact_ids=[refs[0].artifact_id], outcome="complete"),
            retrieval,
            goal,
        )
    assert error.value.error.code == "EVIDENCE_INSUFFICIENT"


def test_unclassified_legacy_goal_has_no_added_source_requirements():
    control = witness(returned=(0,), classified=False)
    assert "required_sources" not in control[-1]
    assert check_retrieval_expectation(*control, "complete") == "complete"


def test_model_view_exposes_the_actual_source_identity_for_required_source_selection():
    from datapilot.orchestration.context import tool_view

    _, store, refs, _, goal = witness()
    artifact = store.get(refs[0])
    view = tool_view(artifact, refs[0], 20000)
    for doc, observed, required in zip(
        artifact.documents.documents, view["documents"], goal["required_sources"], strict=True
    ):
        assert observed["document_id"] == doc.document_id
        assert observed["source_ref"] == {
            k: required[k] for k in ["corpus_id", "index_version", "source_id", "document_id"]
        }
        assert observed["source_ref"]["document_id"] != observed["document_id"]


def test_permission_failure_cannot_be_admitted_as_insufficient():
    control = witness()

    def denied(_):
        raise AgentFailure("DOCUMENT_NOT_AUTHORIZED", "Revoked synthetic source")

    control[3].validate_result = denied
    with pytest.raises(AgentFailure) as error:
        check_retrieval_expectation(*control, "insufficient")
    assert error.value.error.code == "DOCUMENT_NOT_AUTHORIZED"


@pytest.mark.parametrize(
    "question",
    [
        "说明工单档案每周归档和核对编号的规则。",
        "说明每月复核权限的规则。",
        "Explain the rules for checking ticket records every week.",
        "Explain how each day the confirmed records are archived.",
    ],
)
def test_time_frequency_is_not_an_exhaustive_collection(question):
    assert requirement_class(question) == "bounded_facts"


@pytest.mark.parametrize(
    "question",
    [
        "每周检查全部文档，不能漏掉来源。",
        "Review all documents every week.",
    ],
)
def test_frequency_does_not_hide_a_real_collection_requirement(question):
    assert requirement_class(question) == "exhaustive_collection"
