"""Scripted model/retrieval doubles. No embedding, database or paid API inference."""

import json

import pytest
from langchain_core.messages import AIMessage

from datapilot.contracts import AgentFailure
from datapilot.orchestration.context import closed_batches
from datapilot.orchestration.contracts import Document, Plan, SearchResult, TaskSpec
from datapilot.orchestration.coordinator import Coordinator
from datapilot.orchestration.rag_completion import PROTOCOL, SUBMIT
from datapilot.orchestration.runtime import text_hash

QUESTION = "检索包含“入门培训”的文档片段，保留实际来源引用"
USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class RetrievalDouble:
    completion_protocol = PROTOCOL
    max_search_attempts = 2

    def __init__(self, text="入门培训是本合成文档的主题。", *, related=False):
        self.text, self.calls, self.related = text, [], related

    async def search(self, query, top_k):
        self.calls.append(query)
        docs = (
            []
            if not self.text
            else [
                Document(
                    document_id="synthetic-chunk",
                    source="synthetic.md",
                    version="1",
                    text=self.text,
                    sha256=text_hash(self.text),
                )
            ]
        )
        return SearchResult(documents=docs, fixture=True)

    def validate_result(self, result):
        assert result.fixture
        assert all(text_hash(d.text) == d.sha256 for d in result.documents)

    def qualifying_documents(self, documents, goal):
        # Explicit relevance double, not an assertion about embedding accuracy.
        return documents if self.related else []


def refs(messages):
    return [
        json.loads(m.content)["artifact_refs"][0]["artifact_id"]
        for m in messages
        if m.type == "tool" and json.loads(m.content).get("artifact_refs")
    ]


class Decisions:
    def __init__(self, steps):
        self.steps, self.requests = iter(steps), []

    async def respond(self, messages, tools):
        if messages[0].content.startswith("PLAN_JSON"):
            return AIMessage(
                content=Plan(
                    tasks=[
                        TaskSpec(
                            task_id="rag",
                            worker="rag",
                            instruction=messages[-1].content,
                        )
                    ]
                ).model_dump_json(),
                usage_metadata=USAGE,
            )
        self.requests.append((list(messages), tools))
        step = next(self.steps)
        if step == "plain":
            return AIMessage(content="我已经完成检索。", usage_metadata=USAGE)
        if step == "malformed":
            return AIMessage(
                content="",
                invalid_tool_calls=[
                    {
                        "id": f"bad-{len(self.requests)}",
                        "name": SUBMIT,
                        "args": "{bad-json",
                        "error": "invalid JSON",
                    }
                ],
                usage_metadata=USAGE,
            )
        if step == "search":
            name, args = "search_documents", {"query": "入门培训的具体内容是什么？", "top_k": 2}
        else:
            name = SUBMIT
            args = {"artifact_ids": refs(messages)[-1:], "outcome": step}
        if step == "missing":
            args = {"outcome": "complete"}
        elif step == "forged":
            args = {"artifact_ids": ["f" * 64], "outcome": "complete"}
        elif step == "chunk":
            args = {"artifact_ids": ["synthetic-chunk"], "outcome": "complete"}
        elif step == "duplicate":
            args = {"artifact_ids": refs(messages)[-1:] * 2, "outcome": "complete"}
        elif step == "sql":
            name, args = "query_database", {"sql": "SELECT 1"}
        elif step == "read":
            name, args = (
                "read_context",
                {"artifact_id": refs(messages)[-1], "document_id": "synthetic-chunk"},
            )
        call = {"id": f"call-{len(self.requests)}", "name": name, "args": args}
        calls = [call]
        if step in {"mixed", "multiple"}:
            call["args"]["outcome"] = "complete"
            calls.append(
                {
                    "id": "second-submit",
                    "name": SUBMIT if step == "multiple" else "search_documents",
                    "args": call["args"]
                    if step == "multiple"
                    else {"query": "禁止执行", "top_k": 1},
                }
            )
        return AIMessage(content="", tool_calls=calls, usage_metadata=USAGE)


async def run(
    settings,
    steps,
    *,
    text="入门培训是本合成文档的主题。",
    question=QUESTION,
    calls=10,
    related=False,
    trusted_finite=False,
):
    config = settings.model_copy(
        update={
            "max_model_calls": calls,
            "max_worker_turns": 8,
            "max_total_tokens": 100000,
            "max_replans": 0,
        }
    )
    model, retrieval = Decisions(steps), RetrievalDouble(text, related=related)
    scope = None
    if trusted_finite:
        from datapilot.datasets.contracts import DatasetScope
        from datapilot.rag.contracts import CorpusPin, RagScope
        from datapilot.reporting.contracts import DocumentGoal, ReportScope, confirm_finite_scope

        retrieval.scope = RagScope(
            allow_saas=True,
            corpora=[
                CorpusPin(
                    corpus_id="00000000-0000-4000-8000-000000000001",
                    index_version="a" * 64,
                    document_ids=["b" * 64],
                )
            ],
        )
        scope = confirm_finite_scope(
            ReportScope(
                question=question,
                datasets=DatasetScope(),
                metrics=[],
                document_goal=DocumentGoal(
                    goal_id="rag", question=question, metric_goals=[], purpose="summary"
                ),
            ),
            retrieval.scope,
            confirmation_ref="public-finite-retrieval-fixture",
        )
    engine = Coordinator(
        config, model, retrieval=retrieval, run_id="completion-unit", rag_task_scope=scope
    )
    result = await engine.graph.ainvoke(
        {
            "run_id": "completion-unit",
            "question": question,
            "status": "pending",
            "results": {},
            "verifications": {},
            "steps": 0,
            "replans": 0,
            "error": None,
        },
        config={"recursion_limit": 80},
    )
    return result, engine, model, retrieval


@pytest.mark.parametrize("searches", [1, 2])
async def test_model_selects_when_to_submit_and_stops_without_extra_model(settings, searches):
    result, engine, model, retrieval = await run(settings, ["search"] * searches + ["complete"])
    assert result["completion"].status == "completed"
    task = result["results"]["1:rag"]
    assert task.rag_completion.verdict == "literal_locator"
    assert len(retrieval.calls) == searches and len(model.requests) == searches + 1
    assert engine.ledger.snapshot().calls == searches + 2
    closed_batches(engine.transcripts["1:rag"])


async def test_stop_hook_corrects_plain_response_once(settings):
    result, engine, model, _ = await run(settings, ["search", "plain", "complete"])
    assert result["completion"].status == "completed" and len(model.requests) == 3
    assert sum(e["node"] == "rag_stop_hook" for e in engine.events) == 1
    assert engine.ledger.snapshot().reported_tokens == 60


async def test_stop_hook_repeated_non_submission_fails_with_bound(settings):
    result, _, model, _ = await run(settings, ["plain", "plain"])
    assert result["results"]["1:rag"].error.code == "RAG_COMPLETION_REPAIR_EXHAUSTED"
    assert len(model.requests) == 2 and result["completion"].status == "blocked"


@pytest.mark.parametrize("bad", ["missing", "chunk", "malformed"])
async def test_repairable_submission_parameter_error_preserves_pairing(settings, bad):
    result, engine, model, _ = await run(settings, ["search", bad, "complete"])
    assert result["completion"].status == "completed" and len(model.requests) == 3
    closed_batches(engine.transcripts["1:rag"])
    if bad == "malformed":
        assert any(m.invalid_tool_calls for m in engine.transcripts["1:rag"] if m.type == "ai")


@pytest.mark.parametrize("bad", ["forged", "duplicate", "sql"])
async def test_security_failure_never_gets_completion_retry(settings, bad):
    result, engine, model, _ = await run(settings, ["search", bad])
    assert result["results"]["1:rag"].status == "failed"
    assert len(model.requests) == 2 and not any(e["node"] == "rag_stop_hook" for e in engine.events)
    closed_batches(engine.transcripts["1:rag"])


@pytest.mark.parametrize("batch", ["mixed", "multiple"])
async def test_completion_batch_is_rejected_before_any_side_effect(settings, batch):
    result, engine, _, retrieval = await run(settings, ["search", batch, "complete"])
    assert result["completion"].status == "completed" and len(retrieval.calls) == 1
    assert sum(e["node"] == "rag_stop_hook" for e in engine.events) == 1
    closed_batches(engine.transcripts["1:rag"])
    assert sum(e["error_code"] == "COMPLETION_BATCH_INVALID" for e in engine.events) >= 2


async def test_search_phase_shrinks_but_keeps_read_and_submission(settings):
    result, _, model, retrieval = await run(settings, ["search", "search", "read", "complete"])
    assert result["completion"].status == "completed" and len(retrieval.calls) == 2
    assert {t["function"]["name"] for t in model.requests[-1][1]} == {"read_context", SUBMIT}


async def test_stale_search_cannot_execute_and_can_use_one_correction(settings):
    result, engine, _, retrieval = await run(settings, ["search", "search", "search", "complete"])
    assert result["completion"].status == "completed" and len(retrieval.calls) == 2
    assert any(e["error_code"] == "RAG_ATTEMPTS_EXHAUSTED" for e in engine.events)


@pytest.mark.parametrize(
    "text,outcome,code",
    [
        ("", "unavailable", "NO_RELEVANT_DOCUMENTS"),
        ("完全无关的合成文本", "insufficient", "EVIDENCE_INSUFFICIENT"),
    ],
)
async def test_empty_and_nonempty_insufficiency_have_distinct_terminal_reasons(
    settings, text, outcome, code
):
    result, _, _, _ = await run(settings, ["search", outcome], text=text)
    assert result["results"]["1:rag"].status == "unavailable"
    assert result["results"]["1:rag"].error.code == code
    assert result["completion"].status == "blocked"


async def test_irrelevant_nonempty_cannot_be_complete(settings):
    result, _, _, _ = await run(settings, ["search", "complete", "insufficient"], text="天气晴朗。")
    assert result["results"]["1:rag"].rag_completion.verdict == "insufficient"
    assert result["completion"].status == "blocked"


async def test_semantic_retrieval_can_complete_without_literal_keyword(settings):
    result, _, _, _ = await run(
        settings,
        ["search", "complete"],
        question="如何帮助新顾客学习软件？",
        text="入门培训是本合成文档的主题。",
        related=True,
        trusted_finite=True,
    )
    task = result["results"]["1:rag"]
    assert task.status == "succeeded" and task.rag_completion.verdict == "semantic_retrieval"
    assert task.rag_completion.relevant_chunk_ids == ["synthetic-chunk"]
    assert not task.rag_completion.business_conclusions_verified
    assert result["completion"].status == "completed"


async def test_related_semantic_goal_without_confirmation_is_not_self_approved(settings):
    result, engine, model, _ = await run(
        settings,
        ["search", "complete", "insufficient"],
        question="如何帮助新顾客学习软件？",
        related=True,
    )
    task = result["results"]["1:rag"]
    assert task.rag_completion.submission.outcome == "insufficient"
    assert result["completion"].status == "blocked"
    assert len(model.requests) == 3  # One existing correction, never automatic confirmation.
    assert engine.ledger.snapshot().calls == 4  # Includes the original Planner attempt.


async def test_recovery_probe_reuses_host_plan_without_extra_worker_decisions(monkeypatch):
    from pathlib import Path

    from langchain_core.messages import HumanMessage, SystemMessage

    from scripts.rag_recovery_probe import RagDecisions

    # The CLI normally has its sibling script directory on sys.path.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    question = "仅检索客户入门培训相关文档片段，保留实际来源引用"
    menu = [{"task_id": "rag", "worker": "rag", "instruction": question}]
    response = await RagDecisions("semantic").respond(
        [
            SystemMessage(content="REPORT_PLAN_JSON\nHOST_APPROVED_GOALS: " + json.dumps(menu)),
            HumanMessage(content=question),
        ],
        [],
    )
    plan = Plan.model_validate_json(response.content)
    assert [t.task_id for t in plan.tasks] == ["rag", "report"]
    assert plan.tasks[0].instruction == question
    assert plan.tasks[1].dependencies == ["rag"]
    assert response.usage_metadata == USAGE and not response.tool_calls


async def test_true_hash_and_nonempty_semantic_retrieval_do_not_prove_relevance(settings):
    result, _, _, _ = await run(
        settings,
        ["search", "complete", "insufficient"],
        question="如何帮助新顾客学习软件？",
        text="仪表盘响应速度提高。",
        related=False,
    )
    assert result["results"]["1:rag"].rag_completion.verdict == "insufficient"
    assert result["completion"].status == "blocked"


@pytest.mark.parametrize("question", ["分析客户为什么流失", "分析最近三个月客户流失的原因"])
async def test_successful_retrieval_is_separate_from_unverified_business_conclusion(
    settings,
    question,
):
    result, _, _, _ = await run(
        settings,
        ["search", "complete"],
        question=question,
        related=True,
        trusted_finite=True,
    )
    task = result["results"]["1:rag"]
    assert task.status == "succeeded" and task.rag_completion.verdict == "semantic_retrieval"
    assert not task.rag_completion.business_conclusions_verified
    assert result["verifications"]["1:rag"].status == "passed"
    assert result["completion"].status == "blocked"
    assert "P3_VERIFIED_EVIDENCE_REQUIRED" in result["completion"].reason_codes


async def test_quoted_locator_term_is_not_a_business_time_requirement(settings):
    result, _, _, _ = await run(
        settings,
        ["search", "complete"],
        question="定位包含“最新”的文档片段",
        text="最新一词出现在这个合成片段中。",
    )
    assert result["results"]["1:rag"].rag_completion.verdict == "literal_locator"


async def test_answer_exposes_only_qualifying_passages_but_retains_full_artifact(
    settings, monkeypatch
):
    original = RetrievalDouble.search

    async def search(self, query, top_k):
        result = await original(self, query, top_k)
        result.documents.append(
            Document(
                document_id="unrelated",
                source="other.md",
                version="1",
                text="UNRELATED PRIVATE CANDIDATE",
                sha256=text_hash("UNRELATED PRIVATE CANDIDATE"),
            )
        )
        return result

    monkeypatch.setattr(RetrievalDouble, "search", search)
    monkeypatch.setattr(
        RetrievalDouble,
        "qualifying_documents",
        lambda self, documents, goal: [d for d in documents if d.document_id == "synthetic-chunk"],
    )
    result, engine, _, _ = await run(
        settings,
        ["search", "complete"],
        question="如何帮助新顾客学习软件？",
        trusted_finite=True,
    )
    task = result["results"]["1:rag"]
    assert task.rag_completion.relevant_chunk_ids == ["synthetic-chunk"]
    assert "UNRELATED PRIVATE CANDIDATE" not in result["answer"]
    assert len(engine.store.get(task.evidence_refs[0]).documents.documents) == 2


@pytest.mark.parametrize(
    "question",
    [
        "至少两份文档说明新顾客学习软件的方案",
        "最近的新顾客学习软件文档",
        "所有新顾客学习软件文档",
    ],
)
async def test_task_requirements_are_not_replaced_by_relevance_alone(settings, question):
    result, _, _, _ = await run(
        settings,
        ["search", "complete", "insufficient"],
        question=question,
        related=True,
    )
    assert result["results"]["1:rag"].rag_completion.verdict == "insufficient"
    assert result["completion"].status == "blocked"


async def test_correction_obeys_existing_model_budget(settings):
    result, engine, model, _ = await run(settings, ["plain", "complete"], calls=2)
    assert result["results"]["1:rag"].error.code == "BUDGET_EXCEEDED"
    assert len(model.requests) == 1 and engine.ledger.snapshot().calls == 2


async def test_completion_receipt_is_idempotent_and_post_completion_tools_are_denied(settings):
    _, engine, model, retrieval = await run(settings, ["search", "complete"])
    reg = engine.contexts["1:rag"].registry
    args = reg.accepted.submission.model_dump()
    receipt = reg.accepted.model_dump(mode="json")
    for call_id in (reg.accepted.call_id, "repeat-submit"):
        assert (await reg.invoke(SUBMIT, args, call_id=call_id))["rag_completion"] == receipt
    assert len(retrieval.calls) == 1 and len(model.requests) == 2
    with pytest.raises(AgentFailure) as conflict:
        await reg.invoke(SUBMIT, args | {"outcome": "insufficient"}, call_id=reg.accepted.call_id)
    assert conflict.value.error.code == "RECOVERY_CONFLICT"
    with pytest.raises(AgentFailure) as closed:
        await reg.invoke("search_documents", {"query": "入门培训", "top_k": 1}, call_id="late")
    assert closed.value.error.code == "TOOL_FORBIDDEN"


async def test_phase_schema_cannot_be_arbitrarily_restored_or_removed(settings):
    _, engine, _, _ = await run(settings, ["search", "search", "complete"])
    manager = engine.contexts["1:rag"]
    reg = manager.registry
    with pytest.raises(AgentFailure, match="phase"):
        await manager.prepare(
            engine.transcripts["1:rag"], reg.schemas(initial=True), engine.gateway, "1:rag"
        )
    with pytest.raises(AgentFailure, match="phase"):
        reg.validate_phase([], manager.authority.allowed_tools)
    assert set(reg.active_tools()) == {SUBMIT}


async def test_real_artifact_from_sibling_task_is_not_completion_evidence(settings):
    from datapilot.orchestration.contracts import Artifact

    _, engine, _, _ = await run(settings, ["search", "complete"])
    reg = engine.contexts["1:rag"].registry
    source = engine.store.get(reg.refs[0])
    ref = engine.store.put(
        Artifact(
            run_id=engine.run_id,
            task_id="sibling",
            plan_version=1,
            kind="documents",
            source="synthetic",
            documents=source.documents,
        )
    )
    reg.refs.append(ref)  # Even a forged grant projection must not bypass task identity checks.
    with pytest.raises(AgentFailure) as denied:
        await reg.invoke(
            SUBMIT, {"artifact_ids": [ref.artifact_id], "outcome": "complete"}, call_id="sibling"
        )
    assert denied.value.error.code == "EVIDENCE_INVALID"


async def test_sql_worker_cannot_gain_rag_control_tool(settings):
    from datapilot.orchestration.contracts import BudgetLimits, TaskEnvelope
    from datapilot.orchestration.runtime import ArtifactStore
    from datapilot.orchestration.tools import CAPABILITIES, ToolRegistry

    env = TaskEnvelope(
        run_id="sql",
        parent_id="sql",
        plan_version=1,
        task=TaskSpec(task_id="sql", worker="sql", instruction="客户数"),
        allowed_tools=sorted(CAPABILITIES["sql"]),
        budget=BudgetLimits(),
    )
    reg = ToolRegistry(env, ArtifactStore("sql"), retrieval=RetrievalDouble())
    assert reg.retrieval is None and SUBMIT not in reg.allowed
    with pytest.raises(AgentFailure) as denied:
        await reg.invoke(SUBMIT, {"artifact_ids": ["f" * 64], "outcome": "complete"}, call_id="no")
    assert denied.value.error.code == "TOOL_FORBIDDEN"


async def test_verified_unchanged_rag_receipt_can_be_reused_but_not_forged(settings):
    result, engine, _, _ = await run(settings, ["search", "complete"])
    task = result["plan"].tasks[0]
    reused = result["results"]["1:rag"].model_copy(
        update={"plan_version": 2, "reused_from": "1:rag"}
    )
    state = {**result, "plan_version": 2}
    engine.reused["2:rag"] = "1:rag"
    assert engine.verify(state, task, reused).status == "passed"
    engine.reused.clear()
    assert engine.verify(state, task, reused).status == "failed"
