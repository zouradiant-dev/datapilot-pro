"""Cross-process P5B demo/fault probe. Host-only controls, no shell tool or live API by default."""

import argparse
import json
import os

from langchain_core.messages import AIMessage

from datapilot.cli import json_default
from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.orchestration.contracts import Plan, TaskSpec
from datapilot.persistence.session import run_async, run_durable


class LongDecisions:
    """Explicit deterministic decision fixture; data still comes from real MCP/PG."""

    async def respond(self, messages, tools):
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        if messages[0].content.startswith("CONTEXT_SUMMARY_JSON"):
            content = json.loads(messages[-1].content)["expected"]
            content["decisions"] = []
            return AIMessage(content=json.dumps(content), usage_metadata=usage)
        ids = [
            int(c["id"].split("_")[-1])
            for m in messages
            if m.type == "ai"
            for c in m.tool_calls
            if c["id"].startswith("long_")
        ]
        n = max(ids, default=-1) + 1
        if messages[-1].type == "tool":
            payload = json.loads(messages[-1].content)
            if payload.get("artifact_refs"):
                return AIMessage(
                    content=json.dumps(
                        {"artifact_ids": [payload["artifact_refs"][0]["artifact_id"]]}
                    ),
                    usage_metadata=usage,
                )
        name, args = (
            ("database_schema", {})
            if n < 4
            else ("query_database", {"sql": "SELECT COUNT(*) AS n FROM customers"})
        )
        return AIMessage(
            content="Synthetic non-authoritative observation. " + "x" * (1800 if n >= 2 else 0),
            tool_calls=[{"id": f"long_{n}", "name": name, "args": args}],
            usage_metadata=usage,
        )


class ParallelDecisions:
    async def respond(self, messages, tools):
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        if messages[0].content.startswith("PLAN_JSON"):
            return AIMessage(
                content=Plan(
                    tasks=[
                        TaskSpec(task_id="good", worker="sql", instruction="count"),
                        TaskSpec(task_id="denied", worker="sql", instruction="deny"),
                    ]
                ).model_dump_json(),
                usage_metadata=usage,
            )
        if messages[-1].type == "tool":
            payload = json.loads(messages[-1].content)
            return AIMessage(
                content=json.dumps({"artifact_ids": [payload["artifact_refs"][0]["artifact_id"]]}),
                usage_metadata=usage,
            )
        denied = "deny" in messages[1].content.split("\nSCHEMA", 1)[0]
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "parallel_query",
                    "name": "query_database",
                    "args": {
                        "sql": "DELETE FROM customers"
                        if denied
                        else "SELECT COUNT(*) AS n FROM customers"
                    },
                }
            ],
            usage_metadata=usage,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "resume"))
    parser.add_argument("run_id")
    parser.add_argument(
        "--cut",
        choices=(
            "model_issued",
            "model_response",
            "model_committed",
            "tool_issued",
            "tool_artifact",
            "tool_committed",
        ),
    )
    parser.add_argument("--occurrence", type=int, default=1)
    parser.add_argument("--pause-after", choices=("planner", "worker", "scheduler", "verifier"))
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--approve", action="store_true", default=None)
    parser.add_argument("--long", action="store_true")
    parser.add_argument("--parallel", action="store_true")
    parser.add_argument("--live", action="store_true", help="Opt-in paid provider request")
    args = parser.parse_args()
    if args.live and (args.cut or args.long or args.parallel):
        parser.error("Crash/long fixtures cannot be combined with paid live inference")
    count = 0

    def fault(point):
        nonlocal count
        if point == args.cut:
            count += 1
            if count == args.occurrence:
                os._exit(91)  # Genuine loss of Python state; PG releases the session lease.

    settings = Settings(llm_mode="live" if args.live else "fake")
    if args.long:
        settings = settings.model_copy(
            update={
                "max_model_calls": 20,
                "max_worker_turns": 20,
                "max_total_tokens": 100000,
                "max_context_tokens": 24000,
                "max_input_chars": 11000,
            }
        )
    try:
        result = run_async(
            run_durable(
                settings,
                args.run_id,
                None
                if args.action == "resume"
                else "parallel safety fixture"
                if args.parallel
                else "查询客户总数",
                resume=args.action == "resume",
                approve=args.approve,
                require_review=args.review,
                transport=LongDecisions()
                if args.long
                else ParallelDecisions()
                if args.parallel
                else None,
                fault=fault if args.cut else None,
                interrupt_after=[args.pause_after] if args.pause_after else None,
            )
        )
        print(json.dumps(result, default=json_default, ensure_ascii=False))
    except AgentFailure as exc:
        print(
            json.dumps({"status": "blocked", "error": exc.error.model_dump()}, ensure_ascii=False)
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
