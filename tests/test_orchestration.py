"""Actual LangGraph execution with explicit async model/tool component mocks."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from datapilot.contracts import AgentFailure, QueryResult
from datapilot.harness.budget import RunBudget
from datapilot.llm.fake import FakeModelClient
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.contracts import BudgetLimits, Document, Plan, SearchResult, TaskSpec
from datapilot.orchestration.coordinator import Coordinator
from datapilot.orchestration.model import FakeTransport, NativeTransport
from datapilot.orchestration.runtime import Cancellation, text_hash
from datapilot.state import merge_results


class DatabaseMock:
    def __init__(self, barrier=None):
        self.queries = []
        self.barrier = barrier

    async def schema(self):
        return "saas.customers(customer_id INTEGER)"

    async def execute(self, sql):
        self.queries.append(sql)
        if self.barrier:
            await self.barrier()
        if "bad_field" in sql:
            raise AgentFailure(
                "SQL_EXECUTION_ERROR", "column bad_field does not exist", retryable=True
            )
        if "DELETE" in sql:
            raise AgentFailure("SQL_UNSAFE", "Only SELECT is allowed", retryable=True)
        return QueryResult(columns=["n"], rows=[[5]], row_count=1, truncated=False, elapsed_ms=0)


class RetrievalMock:
    def __init__(self, barrier=None, *, fail_once=False, empty=False):
        self.calls = 0
        self.barrier = barrier
        self.fail_once = fail_once
        self.empty = empty

    async def search(self, query, top_k):
        self.calls += 1
        if self.barrier:
            await self.barrier()
        if self.fail_once and self.calls == 1:
            raise AgentFailure("TOOL_TIMEOUT", "Retrieval fixture timeout", retryable=True)
        text = "Synthetic product release: dashboard improvements."
        return SearchResult(
            fixture=True,
            documents=[]
            if self.empty
            else [
                Document(
                    document_id="demo",
                    source="fixture://release",
                    version="1",
                    text=text,
                    sha256=text_hash(text),
                )
            ],
        )


class ScriptTransport:
    def __init__(self, plan=None, *, first_calls=None, finish_id=None):
        self.plan = plan
        self.first_calls = first_calls
        self.finish_id = finish_id
        self.messages = []

    async def respond(self, messages, tools):
        self.messages.append(messages)
        await asyncio.sleep(0)
        if not tools:
            content = (
                self.plan.model_dump_json()
                if isinstance(self.plan, Plan)
                else json.dumps(self.plan)
            )
            return AIMessage(content=content)
        if messages[-1].type == "tool":
            payload = json.loads(messages[-1].content)
            if payload.get("artifact_refs"):
                refs = (
                    [self.finish_id]
                    if self.finish_id
                    else [r["artifact_id"] for r in payload["artifact_refs"]]
                )
                return AIMessage(content=json.dumps({"artifact_ids": refs}))
        calls = self.first_calls or [
            {
                "id": "one",
                "name": "query_database",
                "args": {"sql": "SELECT COUNT(*) AS n FROM customers"},
            }
        ]
        return AIMessage(content="", tool_calls=calls)


def initial(question="查询客户总数"):
    return {
        "run_id": "unit-run",
        "question": question,
        "status": "pending",
        "steps": 0,
        "error": None,
        "answer": "",
        "results": {},
        "verifications": {},
        "replans": 0,
    }


def fake(settings, scripted_sql=None):
    return FakeTransport(
        FakeModelClient(settings, RunBudget(20, 100000), scripted_sql=scripted_sql)
    )


def assert_paired(messages):
    expected = []
    for message in messages:
        if message.type == "ai":
            assert not expected
            expected = [c["id"] for c in message.tool_calls]
        elif message.type == "tool":
            assert message.tool_call_id in expected
            expected.remove(message.tool_call_id)
        else:
            assert not expected
    assert not expected


@pytest.mark.parametrize(
    "raw",
    [
        {
            "tasks": [
                {"task_id": "a", "worker": "sql", "instruction": "x", "dependencies": ["missing"]}
            ]
        },
        {
            "tasks": [
                {"task_id": "a", "worker": "sql", "instruction": "x", "dependencies": ["b"]},
                {"task_id": "b", "worker": "rag", "instruction": "y", "dependencies": ["a"]},
            ]
        },
        {"tasks": [{"task_id": "a", "worker": "sql", "instruction": "x"}] * 2},
        {"tasks": [{"task_id": "a", "worker": "sql", "instruction": "x", "dependencies": ["a"]}]},
        {
            "tasks": [
                {
                    "task_id": "a",
                    "worker": "sql",
                    "instruction": "x",
                    "allowed_tools": ["run_shell"],
                }
            ]
        },
        {"tasks": [], "unsupported": False},
        {
            "tasks": [
                {
                    "task_id": "a",
                    "worker": "analysis",
                    "instruction": "x",
                    "columns": ["n"],
                    "operation": "sum",
                }
            ]
        },
    ],
)
def test_dag_contract_rejects_invalid_references_cycles_and_authority(raw):
    with pytest.raises(ValidationError):
        Plan.model_validate_json(json.dumps(raw))


async def test_simple_sql_uses_two_model_decisions_and_evidence(settings):
    db = DatabaseMock()
    engine = Coordinator(settings, fake(settings), database=db)
    result = await engine.graph.ainvoke(initial())
    assert result["status"] == "succeeded" and result["result"].result.rows == [[5]]
    assert result["result"].attempts == 1
    assert engine.ledger.snapshot().calls == 2
    assert result["verifications"]["1:sql"].status == "passed"
    assert result["results"]["1:sql"].evidence_refs[0].artifact_id in result["answer"]
    assert_paired(engine.transcripts["1:sql"])


async def test_sql_rag_really_overlap_then_report_and_contexts_are_isolated(settings):
    started = set()
    both = asyncio.Event()

    async def arrive(name):
        started.add(name)
        if len(started) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 1)

    db = DatabaseMock(lambda: arrive("sql"))
    rag = RetrievalMock(lambda: arrive("rag"))
    engine = Coordinator(settings, fake(settings), database=db, retrieval=rag)
    result = await engine.graph.ainvoke(
        initial("查询客户总数并检索产品文档"), config={"max_concurrency": 2}
    )
    assert result["status"] == "succeeded", result.get("error")
    assert started == {"sql", "rag"} and len(db.queries) == rag.calls == 1
    assert len([r for r in result["results"].values() if r.status == "succeeded"]) == 3
    sql_text = " ".join(str(m.content) for m in engine.transcripts["1:sql"])
    rag_text = " ".join(str(m.content) for m in engine.transcripts["1:rag"])
    assert "fixture://release" not in sql_text and "saas.customers" not in rag_text
    for messages in engine.transcripts.values():
        assert_paired(messages)
    sources = [
        e["sequence"]
        for e in engine.events
        if e["node"] == "worker" and e["status"] == "succeeded" and e["task_id"] in {"sql", "rag"}
    ]
    report_start = next(
        e["sequence"]
        for e in engine.events
        if e["node"] == "worker" and e["status"] == "started" and e["task_id"] == "report"
    )
    assert report_start > max(sources)
    assert "组件检索替身" in result["answer"]


@pytest.mark.parametrize(
    "operation,columns,expected", [("sum", ["n"], "5"), ("ratio", ["n", "n"], "1.000000000000")]
)
async def test_deterministic_analysis_follows_verified_sql(settings, operation, columns, expected):
    plan = Plan(
        tasks=[
            TaskSpec(task_id="q", worker="sql", instruction="query"),
            TaskSpec(
                task_id="a",
                worker="analysis",
                instruction="exact computation",
                dependencies=["q"],
                operation=operation,
                columns=columns,
            ),
        ]
    )
    engine = Coordinator(settings, ScriptTransport(plan), database=DatabaseMock())
    result = await engine.graph.ainvoke(initial("Analyze supplied data"))
    assert result["status"] == "succeeded", result.get("error")
    artifact = engine.store.get(result["results"]["1:a"].evidence_refs[0])
    assert artifact.values["value"] == expected
    assert artifact.parents == result["results"]["1:q"].evidence_refs
    assert result["results"]["1:a"].usage.calls == 0


async def test_invalid_plan_never_runs_workers_or_rebuilds_graph(settings):
    raw = {
        "tasks": [
            {"task_id": "x", "worker": "sql", "instruction": "query", "dependencies": ["missing"]}
        ]
    }
    db = DatabaseMock()
    engine = Coordinator(settings, ScriptTransport(raw), database=db)
    result = await engine.graph.ainvoke(initial("complex"))
    assert result["status"] == "failed" and result["error"].code == "PLAN_INVALID"
    assert not db.queries and not engine.transcripts


async def test_capability_and_task_quotas_are_host_limits(settings):
    for plan, code in [
        (
            Plan(tasks=[TaskSpec(task_id="r", worker="rag", instruction="search")]),
            "CAPABILITY_UNAVAILABLE",
        ),
        (
            Plan(
                tasks=[
                    TaskSpec(task_id=f"q{i}", worker="sql", instruction="query") for i in range(3)
                ]
            ),
            "PLAN_INVALID",
        ),
    ]:
        config = settings.model_copy(update={"max_tasks": 2})
        engine = Coordinator(config, ScriptTransport(plan), database=DatabaseMock())
        result = await engine.graph.ainvoke(initial("complex"))
        assert result["status"] == "failed" and result["error"].code == code


@pytest.mark.parametrize(
    "calls,code",
    [
        (
            [
                {"id": "denied", "name": "run_shell", "args": {"command": "whoami"}},
                {"id": "remaining", "name": "query_database", "args": {"sql": "SELECT 1"}},
            ],
            "TOOL_FORBIDDEN",
        ),
        (
            [
                {
                    "id": "badargs",
                    "name": "query_database",
                    "args": {"sql": "SELECT 1", "admin": True},
                }
            ],
            "INPUT_INVALID",
        ),
        (
            [{"id": "delete", "name": "query_database", "args": {"sql": "DELETE FROM customers"}}],
            "SQL_UNSAFE",
        ),
    ],
)
async def test_denial_closes_every_tool_id_and_never_replans(settings, calls, code):
    db = DatabaseMock()
    engine = Coordinator(settings, ScriptTransport(first_calls=calls), database=db)
    result = await engine.graph.ainvoke(initial())
    assert result["status"] == "failed" and result["error"].code == code
    assert not result["replans"]
    assert_paired(engine.transcripts["1:sql"])
    if code != "SQL_UNSAFE":
        assert not db.queries


async def test_sql_compiler_repair_is_local_and_bounded(settings):
    for statements, expected in [
        (["SELECT bad_field FROM customers", "SELECT COUNT(*) AS n FROM customers"], "succeeded"),
        (["SELECT bad_field FROM customers"] * 2, "failed"),
    ]:
        db = DatabaseMock()
        engine = Coordinator(settings, fake(settings, statements), database=db)
        result = await engine.graph.ainvoke(initial())
        assert result["status"] == expected and result["result"].attempts == 2
        assert not result["replans"] and len(db.queries) == 2
        assert_paired(engine.transcripts["1:sql"])


async def test_replan_reuses_only_verified_sources_with_fixed_graph(settings):
    config = settings.model_copy(update={"max_model_calls": 12})
    db, rag = DatabaseMock(), RetrievalMock(fail_once=True)
    engine = Coordinator(config, fake(config), database=db, retrieval=rag)
    outer, inner = engine.graph, engine.loop
    result = await outer.ainvoke(initial("查询客户总数并检索产品文档"))
    assert result["status"] == "succeeded", result.get("error")
    assert result["replans"] == 1 and result["plan_version"] == 2
    assert len(db.queries) == 1 and rag.calls == 2
    assert result["results"]["2:sql"].reused_from == "1:sql"
    assert engine.graph is outer and engine.loop is inner


async def test_budget_exhaustion_preserves_error_and_blocks_children(settings):
    config = settings.model_copy(update={"max_model_calls": 1})
    engine = Coordinator(config, fake(config), database=DatabaseMock())
    result = await engine.graph.ainvoke(initial())
    assert result["status"] == "failed" and result["error"].code == "BUDGET_EXCEEDED"
    assert result["results"]["1:sql"].error.category == "budget"
    assert engine.ledger.snapshot().calls == 1 and not engine.ledger.pending
    assert_paired(engine.transcripts["1:sql"])


def test_atomic_parent_child_reservations_and_unknown_usage():
    ledger = BudgetLedger(BudgetLimits(calls=1, tokens=10000))
    for name in ("a", "b"):
        ledger.fork(name, BudgetLimits(calls=1, tokens=10000))

    def reserve(name):
        try:
            return ledger.reserve(name, "x", 100)
        except AgentFailure:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        tickets = list(pool.map(reserve, ["a", "b"]))
    assert sum(t is not None for t in tickets) == 1
    ticket = next(t for t in tickets if t)
    ledger.settle(ticket, None)
    assert not ledger.snapshot().usage_complete and ledger.snapshot().total_tokens > 0
    with pytest.raises(AgentFailure):
        ledger.settle(ticket, 0)
    with pytest.raises(AgentFailure):
        ledger.fork("escape", BudgetLimits(calls=2, tokens=10000))


@pytest.mark.parametrize("during", ["model", "tool"])
async def test_parent_cancellation_reaches_children_and_settles_unknown_usage(settings, during):
    entered = asyncio.Event()

    async def block():
        entered.set()
        await asyncio.Event().wait()

    class Model(ScriptTransport):
        async def respond(self, messages, tools):
            if during == "model":
                await block()
            return await super().respond(messages, tools)

    db = DatabaseMock(block if during == "tool" else None)
    cancel = Cancellation()
    engine = Coordinator(settings, Model(), database=db, cancellation=cancel)
    run = asyncio.create_task(engine.graph.ainvoke(initial()))
    await asyncio.wait_for(entered.wait(), 1)
    cancel.cancel()
    result = await asyncio.wait_for(run, 2)
    assert result["status"] == "cancelled" and result["error"].code == "CANCELLED"
    assert not engine.ledger.pending
    if during == "model":
        assert not engine.ledger.snapshot().usage_complete
    for messages in engine.transcripts.values():
        assert_paired(messages)


async def test_forged_evidence_and_reducer_conflict_fail_closed(settings):
    engine = Coordinator(settings, ScriptTransport(finish_id="0" * 64), database=DatabaseMock())
    result = await engine.graph.ainvoke(initial())
    assert result["status"] == "failed" and result["error"].code == "EVIDENCE_INVALID"
    value = result["results"]["1:sql"]
    assert merge_results({"1:sql": value}, {"1:sql": value}) == {"1:sql": value}
    with pytest.raises(ValueError):
        merge_results({"1:sql": value}, {"1:sql": value.model_copy(update={"attempts": 3})})


async def test_empty_retrieval_explains_unavailable(settings):
    engine = Coordinator(settings, fake(settings), retrieval=RetrievalMock(empty=True))
    # Exercise the real RAG loop with an explicit scoped task (not a fake successful report).
    plan = Plan(tasks=[TaskSpec(task_id="rag", worker="rag", instruction="search")])
    engine.gateway.transport = ScriptTransport(
        plan, first_calls=[{"id": "r", "name": "search_documents", "args": {"query": "no data"}}]
    )
    # The final mock must explicitly mark empty results as unavailable.
    transport = engine.gateway.transport
    original = transport.respond

    async def response(messages, tools):
        reply = await original(messages, tools)
        if messages[-1].type == "tool":
            raw = json.loads(reply.content)
            raw["outcome"] = "unavailable"
            return AIMessage(content=json.dumps(raw))
        return reply

    transport.respond = response
    result = await engine.graph.ainvoke(initial("documents only"))
    assert result["status"] == "unavailable" and "No retrieved evidence" in result["answer"]


async def test_real_async_langchain_http_tool_association_and_redacted_trace(settings):
    requests = []

    async def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if payload["messages"][-1]["role"] == "tool":
            tool = payload["messages"][-1]
            assistant = payload["messages"][-2]
            assert (
                assistant["role"] == "assistant"
                and assistant["tool_calls"][0]["id"] == tool["tool_call_id"]
            )
            ref = json.loads(tool["content"])["artifact_refs"][0]["artifact_id"]
            message = {"role": "assistant", "content": json.dumps({"artifact_ids": [ref]})}
        else:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "native-call",
                        "type": "function",
                        "function": {
                            "name": "query_database",
                            "arguments": json.dumps({"sql": "SELECT COUNT(*) AS n FROM customers"}),
                        },
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "id": "mock",
                "object": "chat.completion",
                "created": 0,
                "model": "test",
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        chat = ChatOpenAI(
            model="test",
            api_key="mock-only",
            base_url="https://model.invalid/v1",
            http_async_client=http,
            max_retries=0,
            max_tokens=100,
            stream_usage=False,
        )
        engine = Coordinator(settings, NativeTransport(chat), database=DatabaseMock())
        result = await engine.graph.ainvoke(initial())
    assert result["status"] == "succeeded" and len(requests) == 2
    assert engine.ledger.snapshot().reported_tokens == 16
    serialized = json.dumps(engine.events)
    assert "SELECT COUNT" not in serialized and "SCHEMA" not in serialized
    assert any(e["tool_call_id"] == "native-call" for e in engine.events)


async def test_external_task_cancel_preserves_all_tool_pairing(settings):
    entered = asyncio.Event()

    async def block():
        entered.set()
        await asyncio.Event().wait()

    calls = [
        {"id": "a", "name": "query_database", "args": {"sql": "SELECT 1"}},
        {"id": "b", "name": "query_database", "args": {"sql": "SELECT 2"}},
    ]
    engine = Coordinator(settings, ScriptTransport(first_calls=calls), database=DatabaseMock(block))
    run = asyncio.create_task(engine.graph.ainvoke(initial()))
    await asyncio.wait_for(entered.wait(), 1)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert engine.cancel.event.is_set() and not engine.ledger.pending
    assert_paired(engine.transcripts["1:sql"])


async def test_blocked_dependents_never_execute_after_source_failure(settings):
    plan = Plan(
        tasks=[
            TaskSpec(task_id="q", worker="sql", instruction="query"),
            TaskSpec(task_id="r", worker="report", instruction="summarize", dependencies=["q"]),
        ]
    )
    engine = Coordinator(
        settings,
        ScriptTransport(plan, first_calls=[{"id": "deny", "name": "run_shell", "args": {}}]),
        database=DatabaseMock(),
    )
    result = await engine.graph.ainvoke(initial("complex"))
    assert result["status"] == "failed" and result["results"]["1:r"].status == "blocked"
    assert not any(e["node"] == "worker" and e["task_id"] == "r" for e in engine.events)


async def test_native_async_adapter_overlaps_two_requests(settings):
    """Real LangChain/SDK async HTTP transport under mock HTTP; no real model inference."""
    both = asyncio.Event()
    arrivals = 0
    plan = Plan(
        tasks=[
            TaskSpec(task_id="one", worker="sql", instruction="first query"),
            TaskSpec(task_id="two", worker="sql", instruction="second query"),
        ]
    )

    async def respond(request):
        nonlocal arrivals
        payload = json.loads(request.content)
        messages = payload["messages"]
        if messages[0]["content"].startswith("PLAN_JSON"):
            message = {"role": "assistant", "content": plan.model_dump_json()}
        elif messages[-1]["role"] == "tool":
            ref = json.loads(messages[-1]["content"])["artifact_refs"][0]["artifact_id"]
            message = {"role": "assistant", "content": json.dumps({"artifact_ids": [ref]})}
        else:
            arrivals += 1
            if arrivals == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 4)
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "native_" + str(arrivals),
                        "type": "function",
                        "function": {
                            "name": "query_database",
                            "arguments": json.dumps({"sql": "SELECT COUNT(*) AS n FROM customers"}),
                        },
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "id": "mock",
                "object": "chat.completion",
                "created": 0,
                "model": "test",
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        chat = ChatOpenAI(
            model="test",
            api_key="mock-only",
            base_url="https://model.invalid/v1",
            http_async_client=http,
            max_retries=0,
            stream_usage=False,
        )
        engine = Coordinator(settings, NativeTransport(chat), database=DatabaseMock())
        result = await engine.graph.ainvoke(initial("two independent SQL questions"))
    assert result["status"] == "succeeded" and arrivals == 2
    assert engine.ledger.snapshot().calls == 5 and engine.ledger.snapshot().reported_tokens == 40
