"""Original, offline API probes for the pinned LangGraph runtime; no model or DB calls."""

import argparse
import json
import platform
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt


def merge_results(left: dict[str, str], right: dict[str, str]) -> dict[str, str]:
    """Accept repeated identical results, reject conflicting writes for one task."""
    merged = dict(left)
    for key, value in right.items():
        if key in merged and merged[key] != value:
            raise ValueError(f"Conflicting task result: {key}")
        merged[key] = value
    return merged


class Results(TypedDict):
    results: Annotated[dict[str, str], merge_results]


class TaskInput(TypedDict):
    task_id: str
    value: int


class Plan(Results):
    tasks: list[TaskInput]
    supervisor_note: str
    completed: bool


def send_and_command() -> dict:
    observed_inputs = []

    def schedule(state: Plan):
        return [Send("worker", dict(task)) for task in state["tasks"]]

    def worker(task: TaskInput):
        assert set(task) == {"task_id", "value"}
        observed_inputs.append(sorted(task))
        return {"results": {task["task_id"]: str(task["value"] * 2)}}

    def finish(state: Plan) -> Command[Literal["__end__"]]:
        assert len(state["results"]) == 2
        return Command(update={"completed": True}, goto=END)

    builder = StateGraph(Plan)
    builder.add_node("worker", worker, input_schema=TaskInput)
    builder.add_node("finish", finish)
    builder.add_conditional_edges(START, schedule, ["worker"])
    builder.add_edge("worker", "finish")
    result = builder.compile().invoke(
        {
            "tasks": [{"task_id": "a", "value": 2}, {"task_id": "b", "value": 3}],
            "results": {},
            "supervisor_note": "parent-only context",
            "completed": False,
        },
        {"max_concurrency": 2},
    )
    assert result["results"] == {"a": "4", "b": "6"} and result["completed"]
    return {
        "results": result["results"],
        "worker_input_keys": observed_inputs,
        "command_completed": result["completed"],
    }


class Approval(TypedDict):
    approved: bool
    report: str


def interrupt_resume() -> dict:
    entries = []

    def approval(state: Approval) -> Command[Literal["publish", "__end__"]]:
        entries.append("entered")  # Deliberately expose replay before interrupt().
        decision = interrupt({"kind": "offline_probe_approval"})
        return Command(
            update={"approved": decision["approved"]},
            goto="publish" if decision["approved"] else END,
        )

    builder = StateGraph(Approval)
    builder.add_node("approval", approval)
    builder.add_node("publish", lambda _: {"report": "approved offline artifact"})
    builder.add_edge(START, "approval")
    builder.add_edge("publish", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "probe-interrupt"}}
    paused = graph.invoke({"approved": False, "report": ""}, config)
    assert len(paused["__interrupt__"]) == 1 and len(entries) == 1
    resumed = graph.invoke(Command(resume={"approved": True}), config)
    assert resumed["approved"] and resumed["report"] and len(entries) == 2
    return {"node_entries": len(entries), "resumed": True, "pre_interrupt_logic_replayed": True}


def partial_failure_resume() -> dict:
    saver = InMemorySaver()
    config = {"configurable": {"thread_id": "probe-pending-writes"}, "max_concurrency": 2}
    calls = {"left": 0, "right": 0}

    def left(_):
        calls["left"] += 1
        return {"results": {"left": "ok"}}

    def right(_):
        calls["right"] += 1
        if calls["right"] == 1:
            # Wait on the public saver API instead of relying on thread timing.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                saved = saver.get_tuple(config)
                if saved and any(
                    item[1] == "results" and item[2] == {"left": "ok"}
                    for item in saved.pending_writes or []
                ):
                    break
                time.sleep(0.01)
            else:
                raise AssertionError("Successful sibling write was not checkpointed")
            raise RuntimeError("injected-right-failure")
        return {"results": {"right": "ok"}}

    builder = StateGraph(Results)
    builder.add_node("left", left)
    builder.add_node("right", right)
    builder.add_edge(START, "left")
    builder.add_edge(START, "right")
    builder.add_edge("left", END)
    builder.add_edge("right", END)
    graph = builder.compile(checkpointer=saver)
    try:
        graph.invoke({"results": {}}, config)
    except RuntimeError as exc:
        assert str(exc) == "injected-right-failure"
    else:
        raise AssertionError("Injected failure was not propagated")
    result = graph.invoke(None, config)
    assert result["results"] == {"left": "ok", "right": "ok"}
    assert calls == {"left": 1, "right": 2}
    return {"calls": calls, "successful_sibling_reused": True}


class WorkerState(TypedDict):
    prepared: str
    result: str


def subgraph_resume() -> dict:
    calls = {"prepare": 0, "tool": 0}

    def prepare(_):
        calls["prepare"] += 1
        return {"prepared": "deterministic proposal"}

    def tool(state: WorkerState):
        calls["tool"] += 1
        if calls["tool"] == 1:
            raise RuntimeError("injected-tool-failure")
        return {"result": state["prepared"] + ": verified"}

    inner = StateGraph(WorkerState)
    inner.add_node("prepare", prepare)
    inner.add_node("tool", tool)
    inner.add_edge(START, "prepare")
    inner.add_edge("prepare", "tool")
    inner.add_edge("tool", END)
    outer = StateGraph(WorkerState)
    outer.add_node("worker", inner.compile())
    outer.add_edge(START, "worker")
    outer.add_edge("worker", END)
    graph = outer.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "probe-subgraph"}}
    try:
        graph.invoke({"prepared": "", "result": ""}, config)
    except RuntimeError as exc:
        assert str(exc) == "injected-tool-failure"
    else:
        raise AssertionError("Injected tool failure was not propagated")
    result = graph.invoke(None, config)
    assert result["result"] == "deterministic proposal: verified"
    assert calls == {"prepare": 1, "tool": 2}
    return {"calls": calls, "completed_inner_node_reused": True}


def command_with_static_edge() -> dict:
    def route(_) -> Command[Literal["dynamic"]]:
        return Command(goto="dynamic")

    builder = StateGraph(Results)
    builder.add_node("route", route)
    builder.add_node("dynamic", lambda _: {"results": {"dynamic": "ran"}})
    builder.add_node("static", lambda _: {"results": {"static": "ran"}})
    builder.add_edge(START, "route")
    builder.add_edge("route", "static")  # Deliberate architecture pitfall.
    builder.add_edge("dynamic", END)
    builder.add_edge("static", END)
    result = builder.compile().invoke({"results": {}})
    assert result["results"] == {"dynamic": "ran", "static": "ran"}
    return {"both_routes_executed": True, "results": result["results"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    assert version("langgraph") == "1.2.16", "Review the baseline before using a different version"
    probes = [
        send_and_command,
        interrupt_resume,
        partial_failure_resume,
        subgraph_resume,
        command_with_static_edge,
    ]
    results = [
        {"name": probe.__name__, "status": "passed", "observed": probe()} for probe in probes
    ]
    report = {
        "research_date": "2026-10-21",
        "executed_at_utc": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "versions": {name: version(name) for name in ("langgraph", "langgraph-checkpoint")},
        "upstream_commit": "41c9c22fdc83d68a2859d0c9a2b627c8615a792f",
        "scope": (
            "Offline synthetic API probes; InMemorySaver in one process. "
            "No model, MCP, database, process-crash durability or performance benchmark."
        ),
        "passed": len(results),
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
