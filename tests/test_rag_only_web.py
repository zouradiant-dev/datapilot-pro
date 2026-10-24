"""RAG-only host/report contracts and the recorded DeepSeek read failure; no paid API."""

from datetime import date
from uuid import uuid4

import pytest
import test_rag_completion as rag_tests
from pydantic import ValidationError

from datapilot.datasets.contracts import DatasetScope
from datapilot.orchestration.context import closed_batches
from datapilot.reporting.contracts import DocumentGoal, ReportScope
from datapilot.web.chat_contracts import ChatSelection
from datapilot.web.contracts import CitationView, CreateTask
from datapilot.web.intent import resolve

QUESTION = "根据已授权的 billing.md，说明文档明确记载的已支付账单收入规则，并给出对应引用。"


def test_existing_citation_projection_is_unchanged_until_explicit_document_answer():
    from datapilot.rag.contracts import ChunkCitation

    citation = ChunkCitation(
        chunk_id="a" * 64,
        start=0,
        end=3,
        line_start=1,
        line_end=1,
        sha256="b" * 64,
        corpus_id=str(uuid4()),
        index_version="c" * 64,
        source_id="d" * 64,
        document_id="e" * 64,
        version="f" * 64,
        source_sha256="a" * 64,
        model_revision="a" * 40,
        chunker_sha256="b" * 64,
        score=0.7,
    )
    view = CitationView(artifact_id="a" * 64, citation=citation)
    assert set(view.model_dump()) == {"artifact_id", "citation"}
    view.quotation = "真实引用式回答"
    assert view.model_dump()["quotation"] == "真实引用式回答"


def test_zero_metrics_requires_an_actual_document_goal():
    corpus = str(uuid4())
    request = CreateTask(
        question=QUESTION,
        metrics=[],
        documents={"question": QUESTION, "metric_goals": [], "corpus_ids": [corpus]},
    )
    assert not request.metrics and request.require_review
    scope = ReportScope(
        question=QUESTION,
        datasets=DatasetScope(),
        metrics=[],
        document_goal=DocumentGoal(goal_id="documents", question=QUESTION, metric_goals=[]),
    )
    assert not scope.metrics
    with pytest.raises(ValidationError):
        CreateTask(question=QUESTION, metrics=[])
    with pytest.raises(ValidationError):
        ReportScope(question=QUESTION, datasets=DatasetScope(), metrics=[])


def test_document_intent_never_invents_metric_date_or_authority():
    pending = resolve(QUESTION, ChatSelection(), [], today=date(2026, 10, 24))
    assert pending.request is None and pending.missing
    selected = ChatSelection(corpus_ids=[str(uuid4())])
    draft = resolve(QUESTION, selected, [], today=date(2026, 10, 24))
    assert draft.request and not draft.request.metrics
    assert draft.request.documents.question == QUESTION
    assert draft.request.documents.corpus_ids == selected.corpus_ids


@pytest.mark.parametrize(
    "mutation", ["no_review", "changed_question", "metric_ref", "no_corpus", "repeated_corpus"]
)
def test_document_only_candidates_cannot_bypass_goal_or_approval(mutation):
    corpus = str(uuid4())
    body = {
        "question": QUESTION,
        "metrics": [],
        "documents": {"question": QUESTION, "metric_goals": [], "corpus_ids": [corpus]},
    }
    if mutation == "no_review":
        body["require_review"] = False
    elif mutation == "changed_question":
        body["documents"]["question"] = "另一个问题"
    elif mutation == "metric_ref":
        body["documents"]["metric_goals"] = ["invented_metric"]
    elif mutation == "no_corpus":
        body["documents"]["corpus_ids"] = []
    else:
        body["documents"]["corpus_ids"] *= 2
    with pytest.raises(ValidationError):
        CreateTask.model_validate(body)


def test_metric_calculation_is_not_silently_mapped_to_document_answer():
    draft = resolve(
        "计算本月收入并给出文档引用",
        ChatSelection(corpus_ids=[str(uuid4())]),
        [],
        today=date(2026, 10, 24),
    )
    assert draft.request is None and draft.missing
    long = resolve(
        "根据文档说明规则" + "。" * 512,
        ChatSelection(corpus_ids=[str(uuid4())]),
        [],
        today=date(2026, 10, 24),
    )
    assert long.request is None and any("512" in m for m in long.missing)


@pytest.mark.parametrize("bad_reads", [1, 2])
async def test_recorded_missing_document_id_is_rejected_and_bounded_repair(
    settings, monkeypatch, bad_reads
):
    original = rag_tests.Decisions

    class MissingRead(original):
        async def respond(self, messages, tools):
            reply = await super().respond(messages, tools)
            calls = reply.tool_calls
            if calls and calls[0]["name"] == "read_context":
                self.read_requests = getattr(self, "read_requests", 0) + 1
                if self.read_requests <= bad_reads:
                    calls[0]["args"].pop("document_id", None)
            return reply

    monkeypatch.setattr(rag_tests, "Decisions", MissingRead)
    result, engine, model, retrieval = await rag_tests.run(
        settings, ["search", "read", "read", "complete"]
    )
    closed_batches(engine.transcripts["1:rag"])
    assert len(retrieval.calls) == 1
    if bad_reads == 1:
        assert result["completion"].status == "completed"
        assert len(model.requests) == 4
    else:
        assert result["results"]["1:rag"].error.code == "RAG_COMPLETION_REPAIR_EXHAUSTED"
        assert len(model.requests) == 3
    assert any(e["error_code"] == "INPUT_INVALID" for e in engine.events)


async def test_document_read_forged_artifact_still_fails_without_correction(settings, monkeypatch):
    original = rag_tests.Decisions

    class ForgedRead(original):
        async def respond(self, messages, tools):
            reply = await super().respond(messages, tools)
            if reply.tool_calls and reply.tool_calls[0]["name"] == "read_context":
                reply.tool_calls[0]["args"]["artifact_id"] = "f" * 64
            return reply

    monkeypatch.setattr(rag_tests, "Decisions", ForgedRead)
    result, engine, model, _ = await rag_tests.run(settings, ["search", "read"])
    assert result["results"]["1:rag"].error.code == "TOOL_FORBIDDEN"
    assert len(model.requests) == 2
    assert not any(e["node"] == "rag_stop_hook" for e in engine.events)
    closed_batches(engine.transcripts["1:rag"])


async def test_recorded_two_missing_reads_in_one_batch_close_both_calls(settings, monkeypatch):
    original = rag_tests.Decisions

    class BatchRead(original):
        async def respond(self, messages, tools):
            reply = await super().respond(messages, tools)
            if reply.tool_calls and reply.tool_calls[0]["name"] == "read_context":
                reply.tool_calls[0]["args"].pop("document_id")
                reply.tool_calls.append(
                    {
                        "id": "recorded-sibling-read",
                        "name": "read_context",
                        "args": dict(reply.tool_calls[0]["args"]),
                        "type": "tool_call",
                    }
                )
            return reply

    monkeypatch.setattr(rag_tests, "Decisions", BatchRead)
    result, engine, model, _ = await rag_tests.run(settings, ["search", "read", "complete"])
    assert result["completion"].status == "completed" and len(model.requests) == 3
    transcript = engine.transcripts["1:rag"]
    closed_batches(transcript)
    assert sum(m.type == "tool" and '"code": "INPUT_INVALID"' in m.content for m in transcript) == 2
    assert sum(e["node"] == "rag_stop_hook" for e in engine.events) == 1
