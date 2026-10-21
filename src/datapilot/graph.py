"""Public facade for a reusable Planner/Scheduler/Worker/Verifier/Replan topology."""

import asyncio
from uuid import uuid4

from datapilot.config import Settings
from datapilot.contracts import AgentError, AgentFailure
from datapilot.harness.budget import RunBudget
from datapilot.llm.fake import FakeModelClient
from datapilot.orchestration.contracts import CompletionDecision
from datapilot.orchestration.coordinator import Coordinator
from datapilot.orchestration.model import FakeTransport, live_transport
from datapilot.runtime.mcp_client import database_session


def build_graph(settings, client, tool, events):
    """Compatibility entry for explicit Fake component tests. Compile once per logical run."""
    if not isinstance(client, FakeModelClient):
        raise ValueError("Use Coordinator with an async transport for real models")
    return Coordinator(settings, FakeTransport(client), database=tool, events=events).graph


async def run_question(
    settings: Settings,
    question: str,
    *,
    scripted_sql=None,
    retrieval=None,
    transport=None,
    cancellation=None,
    include_artifacts=False,
) -> dict:
    initial = {
        "run_id": str(uuid4()),
        "question": question,
        "status": "pending",
        "task": None,
        "result": None,
        "error": None,
        "steps": 0,
        "answer": "",
        "results": {},
        "verifications": {},
        "replans": 0,
    }
    if not question.strip() or len(question) > 8000:
        error = AgentError(code="INPUT_INVALID", message="Question must contain 1–8000 characters")
        return {
            **initial,
            "status": "failed",
            "error": error,
            "answer": error.message,
            "mode": settings.llm_mode,
            "trace": [],
            "usage": {},
            "completion": CompletionDecision(status="blocked", reason_codes=["INPUT_INVALID"]),
        }
    if scripted_sql is not None and settings.llm_mode != "fake":
        raise ValueError("Scripted SQL is only available in explicitly fake mode")
    if transport is None:
        transport = (
            FakeTransport(
                FakeModelClient(
                    settings,
                    RunBudget(settings.max_model_calls, settings.max_total_tokens),
                    scripted_sql=scripted_sql,
                )
            )
            if settings.llm_mode == "fake"
            else live_transport(settings)
        )
    events = []
    coordinator = None
    try:
        async with database_session(settings) as tools:
            coordinator = Coordinator(
                settings,
                transport,
                database=tools,
                retrieval=retrieval,
                events=events,
                cancellation=cancellation,
                run_id=initial["run_id"],
            )
            result = await coordinator.graph.ainvoke(
                initial,
                config={
                    "recursion_limit": settings.max_steps * 3 + 10,
                    "max_concurrency": settings.max_parallel_workers,
                },
            )
    except asyncio.CancelledError:
        if coordinator:
            coordinator.cancel.cancel()
        raise
    except AgentFailure as exc:
        error = exc.error
        result = {
            **initial,
            "status": "failed",
            "error": error,
            "answer": f"执行失败 [{error.code}]：{error.message}",
        }
    except Exception:
        code = "MCP_CONNECTION_ERROR" if coordinator is None else "INTERNAL_ERROR"
        error = AgentError(
            code=code,
            message="Cannot initialize MCP transport"
            if coordinator is None
            else "Run failed safely; inspect redacted trace",
        )
        result = {**initial, "status": "failed", "error": error, "answer": error.message}
    return {
        **result,
        "mode": settings.llm_mode,
        "trace": events,
        "usage": coordinator.ledger.snapshot().model_dump() if coordinator else {},
        "completion": result.get("completion")
        or CompletionDecision(status="blocked", reason_codes=["RUN_NOT_SUCCESSFUL"]),
        **({"artifacts": coordinator.store.export()} if coordinator and include_artifacts else {}),
    }
