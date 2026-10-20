"""Day 1 graph: plan -> SQL over MCP -> supervisor verification -> deterministic answer."""

import time
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from datapilot.agents.sql import SQLAgent
from datapilot.agents.supervisor import Supervisor
from datapilot.config import Settings
from datapilot.contracts import AgentError, AgentFailure
from datapilot.harness.budget import RunBudget
from datapilot.harness.verification import verify_completion
from datapilot.llm.client import create_live_client
from datapilot.llm.fake import FakeModelClient
from datapilot.runtime.mcp_client import database_session
from datapilot.state import GraphState


def _cell(value) -> str:
    if value is None:
        return "NULL"
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "&#124;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace("`", "&#96;")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def build_graph(settings, client, tool, events):
    supervisor = Supervisor(client)
    worker = SQLAgent(client, tool, max_attempts=settings.max_sql_attempts)

    def guarded(name, fn):
        async def node(state: GraphState):
            started = time.monotonic()
            steps = state["steps"] + 1
            if steps > settings.max_steps:
                update = {
                    "status": "failed",
                    "error": AgentError(code="STEP_LIMIT", message="Graph step budget exhausted"),
                }
            else:
                try:
                    update = await fn(state)
                except AgentFailure as exc:
                    update = {"status": "failed", "error": exc.error}
                except ValidationError:
                    update = {
                        "status": "failed",
                        "error": AgentError(
                            code="VERIFICATION_ERROR", message="Agent contract validation failed"
                        ),
                    }
            events.append(
                {
                    "node": name,
                    "status": update.get("status", state["status"]),
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                    "error_code": update["error"].code if update.get("error") else None,
                }
            )
            return {**update, "steps": steps}

        return node

    async def plan(state):
        task = supervisor.delegate(state["question"], state["run_id"])
        return {"task": task, "status": "running" if task else "unsupported"}

    async def sql(state):
        return {"result": await worker.run(state["task"]), "status": "running"}

    async def review(state):
        result = state["result"]
        verify_completion(state["task"], result, settings.max_rows)
        if result.status == "failed":
            return {"status": "failed", "error": result.error}
        return {"status": "succeeded"}

    async def answer(state):
        if state["status"] == "unsupported":
            return {"answer": "当前仅支持 2025 年合成 SaaS 数据的 SQL 查询；该请求尚不支持。"}
        if state["status"] == "failed":
            error = state["error"]
            return {"answer": f"查询失败 [{_cell(error.code)}]：{_cell(error.message)}"}
        data = state["result"].result
        headers = "| " + " | ".join(_cell(x) for x in data.columns) + " |"
        separator = "| " + " | ".join("---" for _ in data.columns) + " |"
        rows = ["| " + " | ".join(_cell(x) for x in row) + " |" for row in data.rows]
        return {
            "answer": (
                "数据来源：PostgreSQL 17 合成 SaaS 数据（2025 年），经受控 MCP 查询。"
                "金额单位 CNY 分。\n\n"
                + "\n".join([headers, separator, *rows])
                + ("\n未找到匹配记录。" if not rows else "")
                + ("\n结果已截断，不能作为完整明细或全量统计。" if data.truncated else "")
            )
        }

    builder = StateGraph(GraphState)
    for name, fn in (
        ("supervisor_plan", plan),
        ("sql_worker", sql),
        ("supervisor_review", review),
        ("answer", answer),
    ):
        builder.add_node(name, guarded(name, fn))
    builder.add_edge(START, "supervisor_plan")
    builder.add_conditional_edges(
        "supervisor_plan",
        lambda s: "sql" if s["status"] == "running" else "answer",
        {"sql": "sql_worker", "answer": "answer"},
    )
    builder.add_conditional_edges(
        "sql_worker",
        lambda s: "review" if s["status"] == "running" else "answer",
        {"review": "supervisor_review", "answer": "answer"},
    )
    builder.add_edge("supervisor_review", "answer")
    builder.add_edge("answer", END)
    return builder.compile()


async def run_question(settings: Settings, question: str, *, scripted_sql=None) -> dict:
    budget = RunBudget(settings.max_model_calls, settings.max_total_tokens)
    initial: GraphState = {
        "run_id": str(uuid4()),
        "question": question,
        "status": "pending",
        "task": None,
        "result": None,
        "error": None,
        "steps": 0,
        "answer": "",
    }
    if not question.strip() or len(question) > 8000:
        initial.update(
            status="failed",
            error=AgentError(
                code="INPUT_INVALID", message="Question must contain 1–8000 characters"
            ),
        )
        return {**initial, "mode": settings.llm_mode, "trace": [], "usage": vars(budget)}
    if scripted_sql is not None and settings.llm_mode != "fake":
        raise ValueError("Scripted SQL is only available in explicitly fake mode")
    client = (
        FakeModelClient(settings, budget, scripted_sql=scripted_sql)
        if settings.llm_mode == "fake"
        else create_live_client(settings, budget)
    )
    events: list[dict] = []
    try:
        async with database_session(settings) as tool:
            graph = build_graph(settings, client, tool, events)
            result = await graph.ainvoke(
                initial, config={"recursion_limit": settings.max_steps + 5}
            )
    except Exception:
        # MCP task groups can wrap errors in ExceptionGroup; do not expose subprocess internals.
        result = {
            **initial,
            "status": "failed",
            "error": AgentError(
                code="MCP_CONNECTION_ERROR",
                message="Cannot establish or close MCP database session",
            ),
        }
    if result["status"] == "failed" and not result["answer"]:
        result["answer"] = f"查询失败 [{result['error'].code}]：{result['error'].message}"
    return {**result, "mode": settings.llm_mode, "trace": events, "usage": vars(budget)}
