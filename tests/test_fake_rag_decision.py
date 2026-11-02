"""Focused Fake RAG decision contracts (no provider, no database)."""

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from datapilot.contracts import AgentFailure
from datapilot.orchestration.contracts import (
    Artifact,
    BudgetLimits,
    Document,
    RagSubmission,
    SearchResult,
    TaskEnvelope,
    TaskSpec,
)
from datapilot.orchestration.loop import initial_messages
from datapilot.orchestration.model import FakeTransport
from datapilot.orchestration.rag_completion import validate_submission
from datapilot.orchestration.runtime import ArtifactStore, text_hash
from datapilot.reporting.contracts import DocumentFact, DocumentGoal
from datapilot.reporting.service import fact_coverage

QUESTION = "计算2026年6月已支付账单收入，并引用文档规则说明：已支付账单收入仅计入状态为paid的账单。"
GOAL = {
    "protocol": "retrieval-task-v1",
    "minimum_sources": 1,
    "required_terms": [],
    "unsupported_requirements": False,
    "completion_eligible": True,
}
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Retrieve permitted documents",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "For the FIRST search use this exact host document goal. "
                            "HOST_FIRST_QUERY_JSON: " + json.dumps(QUESTION, ensure_ascii=False)
                        ),
                    },
                    "top_k": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_rag_result",
            "description": "Request host-verified completion",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def message_seed(schema='{"corpora":["synthetic"]}', instruction=QUESTION):
    envelope = TaskEnvelope(
        run_id="fake-rag-unit",
        parent_id="fake-rag-unit",
        plan_version=1,
        task=TaskSpec(task_id="documents", worker="rag", instruction=instruction),
        allowed_tools=["search_documents", "read_context", "submit_rag_result"],
        budget=BudgetLimits(),
    )
    return initial_messages(envelope, schema, rag_control=True, rag_goal=GOAL)


async def test_fake_first_search_uses_exact_host_query_not_worker_schema():
    messages = message_seed()
    human = next(m for m in messages if isinstance(m, HumanMessage))
    assert "\nSCHEMA:\n" in human.content  # Worker context is still present.
    reply = await FakeTransport(None).respond(messages, TOOLS)
    assert reply.tool_calls[0]["name"] == "search_documents"
    assert reply.tool_calls[0]["args"]["query"] == QUESTION


def outcome(documents, goal=GOAL, count=None):
    payload = {
        "artifact_refs": [{"artifact_id": "a" * 64}],
        "documents": [{"text": text} for text in documents],
        "document_count": len(documents) if count is None else count,
    }
    return FakeTransport._rag_outcome(payload, goal)


def test_fake_complete_requires_host_minimum_and_literal_terms():
    assert outcome(["已支付账单收入规则"]) == "complete"
    assert outcome([]) == "unavailable"
    assert outcome(["一条证据"], {**GOAL, "minimum_sources": 2}) == "insufficient"
    assert outcome(["缺少要求的原文"], {**GOAL, "required_terms": ["必须包含"]}) == "insufficient"
    assert outcome(["已包含必须包含"], {**GOAL, "required_terms": ["必须包含"]}) == "complete"
    assert outcome(["证据"], {**GOAL, "unsupported_requirements": True}) == "insufficient"
    assert outcome(["证据"], {**GOAL, "completion_eligible": False}) == "insufficient"
    assert outcome(["证据"], {**GOAL, "completion_eligible": None}) == "insufficient"
    assert (
        outcome(["证据"], {k: v for k, v in GOAL.items() if k != "completion_eligible"})
        == "insufficient"
    )
    assert (
        outcome(["证据"], {k: v for k, v in GOAL.items() if k != "unsupported_requirements"})
        == "insufficient"
    )
    assert outcome(["证据"], {**GOAL, "minimum_sources": "not-a-number"}) == "insufficient"
    assert (
        outcome(["证据"], {k: v for k, v in GOAL.items() if k != "minimum_sources"})
        == "insufficient"
    )
    assert (
        outcome(["证据"], {k: v for k, v in GOAL.items() if k != "required_terms"})
        == "insufficient"
    )
    assert outcome(["证据"], {**GOAL, "required_terms": "not-a-list"}) == "insufficient"
    assert outcome(["证据"], None) == "insufficient"


async def test_fake_downgrades_after_host_rejects_complete_without_new_evidence():
    messages = message_seed()
    messages.append(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "submit_1",
                    "name": "submit_rag_result",
                    "args": {"artifact_ids": ["a" * 64], "outcome": "complete"},
                }
            ],
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
    )
    messages.append(
        ToolMessage(
            content=json.dumps({"error": {"code": "EVIDENCE_INSUFFICIENT"}}),
            tool_call_id="submit_1",
            name="submit_rag_result",
        )
    )
    transport = FakeTransport(None)
    transport._rag_artifacts = ["a" * 64]
    transport._rag_complete_attempted = True
    reply = await transport.respond(messages, TOOLS)
    call = reply.tool_calls[0]
    assert call["name"] == "submit_rag_result"
    assert call["args"] == {"artifact_ids": ["a" * 64], "outcome": "insufficient"}


class _RetrievalDouble:
    def validate_result(self, result):
        assert result.fixture

    def qualifying_documents(self, documents, goal):
        return documents


def same_source_store():
    run_id = "fake-safety-same-source"
    store = ArtifactStore(run_id)
    documents = [
        Document(
            document_id=f"chunk-{index}",
            source="same-billing-guide.md",
            version="1",
            text="已支付账单收入规则",
            sha256=text_hash("已支付账单收入规则"),
        )
        for index in (1, 2)
    ]
    artifact = Artifact(
        run_id=run_id,
        task_id="documents",
        plan_version=1,
        kind="documents",
        source="retrieval",
        documents=SearchResult(documents=documents, fixture=True),
    )
    ref = store.put(artifact)
    envelope = TaskEnvelope(
        run_id=run_id,
        parent_id=run_id,
        plan_version=1,
        task=TaskSpec(task_id="documents", worker="rag", instruction=QUESTION),
        allowed_tools=["search_documents", "submit_rag_result"],
        budget=BudgetLimits(),
    )
    return store, ref, envelope


def test_fake_complete_candidate_on_same_source_is_rejected_by_host():
    store, ref, envelope = same_source_store()
    goal = {
        "protocol": "retrieval-task-v1",
        "minimum_sources": 2,
        "required_terms": [],
        "unsupported_requirements": False,
        "completion_eligible": True,
    }
    payload = {
        "artifact_refs": [{"artifact_id": ref.artifact_id}],
        "documents": [{"text": "同一来源的两段内容"}, {"text": "同一来源的另一段"}],
        "document_count": 2,
    }
    # Fake's heuristic counts documents, so it proposes complete.
    assert FakeTransport._rag_outcome(payload, goal) == "complete"
    submission = RagSubmission(artifact_ids=[ref.artifact_id], outcome="complete")
    with pytest.raises(AgentFailure) as exc:
        validate_submission(envelope, store, [ref], submission, _RetrievalDouble(), goal)
    assert exc.value.error.code == "EVIDENCE_INSUFFICIENT"


def test_keyword_presence_cannot_create_host_fact_proof():
    goal = DocumentGoal(
        goal_id="documents",
        question="总结已支付账单收入规则并说明下一年度退款比例。",
        metric_goals=[],
        purpose="facts",
        required_facts=[DocumentFact(fact_id="future_refund", description="下一年度退款比例")],
    )
    documents = [
        SimpleNamespace(
            citation=None,
            excerpt="下一年度退款比例不适用；已支付账单收入仅计入paid账单。",
        )
    ]
    coverage = fact_coverage(goal, documents)
    assert coverage == {"future_refund": None}


async def test_rejected_complete_is_bound_to_its_own_tool_call_and_artifacts():
    messages = message_seed()
    messages.append(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "submit_other",
                    "name": "submit_rag_result",
                    "args": {"artifact_ids": ["b" * 64], "outcome": "complete"},
                }
            ],
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
    )
    messages.append(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "submit_1",
                    "name": "submit_rag_result",
                    "args": {"artifact_ids": ["a" * 64], "outcome": "complete"},
                }
            ],
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
    )
    messages.append(
        ToolMessage(
            content=json.dumps({"error": {"code": "EVIDENCE_INSUFFICIENT"}}),
            tool_call_id="submit_1",
            name="submit_rag_result",
        )
    )
    reply = await FakeTransport(None).respond(messages, TOOLS)
    assert reply.tool_calls[0]["args"] == {
        "artifact_ids": ["a" * 64],
        "outcome": "insufficient",
    }
