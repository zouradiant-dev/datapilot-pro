"""Source-goal authority and citation binding, using independent synthetic data."""

import hashlib

import pytest
from pydantic import ValidationError
from test_completion_admission import witness

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetScope
from datapilot.orchestration.rag_completion import SOURCE_RELEVANCE_POLICY, retrieval_goal
from datapilot.orchestration.runtime import text_hash
from datapilot.rag.contracts import SourceGoal, check_source_goals, source_goal_key
from datapilot.rag.mcp import MCPRetrievalTools
from datapilot.reporting.contracts import (
    CitationPolicy,
    CitationSource,
    DocumentFact,
    DocumentGoal,
    ReportScope,
    confirm_finite_scope,
)


def source_scope():
    _, store, refs, retrieval, _ = witness()
    citations = [d.citation for d in store.get(refs[0]).documents.documents]
    question = "分别说明工单归档安排和值班交接的核对规则。"
    targets = [
        SourceGoal(
            corpus_id=c.corpus_id,
            index_version=c.index_version,
            document_id=c.document_id,
            question=q,
        )
        for c, q in zip(citations, ["工单归档安排", "值班交接核对规则"], strict=True)
    ]
    scope = ReportScope(
        question=question,
        datasets=DatasetScope(),
        metrics=[],
        document_goal=DocumentGoal(
            goal_id="documents",
            question=question,
            metric_goals=[],
            purpose="facts",
            required_facts=[DocumentFact(fact_id="requested", description="明确的合成目标")],
            source_goals=targets,
        ),
        citation_policy=CitationPolicy(
            goal_sha256=text_hash(question),
            required_sources=[
                CitationSource(**{k: getattr(c, k) for k in CitationSource.model_fields})
                for c in citations
            ],
        ),
    )
    scope = confirm_finite_scope(
        scope, retrieval.scope, confirmation_ref="public-two-component-review"
    )
    return scope, retrieval.scope, store.get(refs[0]).documents.documents


def test_source_goals_are_explicit_reviewed_parts_not_an_authorization_grant():
    scope, rag, _ = source_scope()
    client = MCPRetrievalTools(
        None, 10, scope=rag, goal=scope.question, source_goals=scope.document_goal.source_goals
    )
    goal = retrieval_goal(scope.question, client, scope)
    assert goal["relevance_policy"] == SOURCE_RELEVANCE_POLICY
    assert goal["minimum_goal_score"] == 0.55
    assert len(goal["source_goals"]) == len(goal["required_sources"]) == 2
    assert client.max_search_attempts == 2
    scope.document_goal.source_goals[0].question = "改变后的子目标"
    with pytest.raises(AgentFailure, match="confirmation changed"):
        retrieval_goal(scope.question, client, scope)


@pytest.mark.parametrize("change", ["unauthorized", "duplicate", "no-policy", "qwen"])
def test_invalid_source_goal_contract_fails_before_embedding_or_database(change):
    scope, rag, _ = source_scope()
    if change == "unauthorized":
        rag.corpora[0].document_ids = []
    elif change == "duplicate":
        scope.document_goal.source_goals[1] = scope.document_goal.source_goals[0]
    elif change == "no-policy":
        scope.citation_policy = None
    else:
        rag.embedding_profile = "qwen3-cpu-v1"
    with pytest.raises((ValueError, ValidationError)):
        confirm_finite_scope(scope, rag, confirmation_ref="invalid-synthetic-review")


def test_component_score_requires_the_exact_source_goal_hash():
    scope, rag, docs = source_scope()
    targets = scope.document_goal.source_goals
    client = MCPRetrievalTools(None, 10, scope=rag, goal=scope.question, source_goals=targets)
    goal = retrieval_goal(scope.question, client, scope)
    for d in docs:
        target = next(g for g in targets if source_goal_key(g) == source_goal_key(d.citation))
        d.citation.goal_sha256 = text_hash(scope.question)
        d.citation.goal_score = 0.8
        d.citation.source_goal_sha256 = hashlib.sha256(target.question.encode()).hexdigest()
    assert len(client.qualifying_documents(docs, goal)) == 2
    docs[0].citation.source_goal_sha256 = "0" * 64
    assert client.qualifying_documents(docs, goal) == docs[1:]
    docs[1].citation.goal_score = 0.54
    assert client.qualifying_documents(docs, goal) == []


def test_source_goal_session_cannot_replace_the_parent_review():
    scope, rag, _ = source_scope()
    other = [g.model_copy(deep=True) for g in scope.document_goal.source_goals]
    other[0].question += "另一个解释"
    client = MCPRetrievalTools(None, 10, scope=rag, goal=scope.question, source_goals=other)
    with pytest.raises(AgentFailure) as error:
        retrieval_goal(scope.question, client, scope)
    assert error.value.error.code == "REPORT_SCOPE_INVALID"


def test_legacy_client_cannot_accept_component_metadata():
    scope, rag, docs = source_scope()
    client = MCPRetrievalTools(None, 10, scope=rag, goal=scope.question)
    doc = docs[0]
    assert "source_goal_sha256" not in doc.citation.model_dump(mode="json")
    doc.citation.goal_sha256 = text_hash(scope.question)
    doc.citation.goal_score = 0.8
    doc.citation.source_goal_sha256 = "e" * 64
    legacy = scope.model_copy(deep=True)
    legacy.document_goal.source_goals = []
    legacy = confirm_finite_scope(legacy, rag, confirmation_ref="public-legacy-source-control")
    assert client.qualifying_documents(docs, retrieval_goal(scope.question, client, legacy)) == []
    assert check_source_goals(rag, scope.question, []) == []


async def test_component_query_schema_and_server_side_quota():
    from types import SimpleNamespace

    from datapilot.orchestration.contracts import BudgetLimits, SearchResult, TaskEnvelope, TaskSpec
    from datapilot.orchestration.rag_completion import PROTOCOL
    from datapilot.orchestration.runtime import ArtifactStore
    from datapilot.orchestration.tools import ToolRegistry

    scope, rag, _ = source_scope()
    calls = []

    async def search(query, _):
        calls.append(query)
        return SearchResult(documents=[], fixture=True)

    retrieval = SimpleNamespace(
        scope=rag, completion_protocol=PROTOCOL, max_search_attempts=2, search=search
    )
    store = ArtifactStore("public-component-query-control")
    env = TaskEnvelope(
        run_id=store.run_id,
        parent_id=store.run_id,
        plan_version=1,
        task=TaskSpec(task_id="documents", worker="rag", instruction=scope.question),
        allowed_tools=["search_documents", "submit_rag_result"],
        budget=BudgetLimits(),
    )
    queries = [g.question for g in scope.document_goal.source_goals]
    tools = ToolRegistry(
        env,
        store,
        retrieval=retrieval,
        rag_goal=retrieval_goal(scope.question, retrieval, scope),
        source_queries=queries,
    )
    schema = next(s for s in tools.schemas() if s["function"]["name"] == "search_documents")
    assert schema["function"]["parameters"]["properties"]["query"]["enum"] == queries
    with pytest.raises(AgentFailure) as error:
        await tools.invoke("search_documents", {"query": "模型擅改子目标"}, call_id="denied")
    assert error.value.error.code == "RAG_QUERY_POLICY" and calls == []
    for i, q in enumerate(queries):
        await tools.invoke("search_documents", {"query": q}, call_id=f"valid_{i}")
    with pytest.raises(AgentFailure) as error:
        await tools.invoke("search_documents", {"query": queries[0]}, call_id="third")
    assert error.value.error.code == "RAG_ATTEMPTS_EXHAUSTED" and len(calls) == 2


def test_source_goal_adapter_preserves_incomplete_failure(monkeypatch):
    from types import SimpleNamespace

    from evaluation.p7_v3_current import source_goal_scoring as scorer

    scope, _, _ = source_scope()
    payload = {"snapshot": {"report": None}}
    key = b"public-incomplete-score-control-key"
    record = scorer.host.p7_business_scoring.sign_collection(payload, key)
    monkeypatch.setattr(
        scorer.host,
        "score",
        lambda *_: {"strict_correct": False, "failure_class": "unknown_outcome"},
    )
    result = scorer.score(SimpleNamespace(report_scope=scope), None, record, key, {})
    assert result["strict_correct"] is False and result["failure_class"] == "unknown_outcome"
