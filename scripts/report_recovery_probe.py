"""Synthetic decisions only; business SQL, PG/RAG/MCP and durable runtime are real."""

import argparse
import json
import os
from pathlib import Path

from langchain_core.messages import AIMessage

from datapilot.cli import json_default
from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.orchestration.contracts import Plan, TaskSpec
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.cli import read_scope
from datapilot.reporting.contracts import ReportScope


class ReportDecisions:
    """An explicit test script, not an assertion about any model's analysis ability."""

    def __init__(self, query, *, attack=False):
        self.query, self.attack = query, attack

    async def respond(self, messages, tools):
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        if messages[0].content.startswith("REPORT_PLAN_JSON"):
            menu = json.loads(messages[0].content.split("HOST_APPROVED_GOALS: ", 1)[1])
            plan = Plan(
                tasks=[
                    *[TaskSpec(**m) for m in menu],
                    TaskSpec(
                        task_id="report",
                        worker="report",
                        instruction="发布已验证指标及文档引述",
                        dependencies=[m["task_id"] for m in menu],
                    ),
                ]
            )
            return AIMessage(content=plan.model_dump_json(), usage_metadata=usage)
        observations = [json.loads(m.content) for m in messages if m.type == "tool"]
        if not observations:
            name, args, id_ = "search_documents", {"query": self.query, "top_k": 3}, "retrieve"
        elif self.attack:
            name, args, id_ = "query_database", {"sql": "DELETE FROM invoices"}, "injected"
        else:
            observed = next(o for o in reversed(observations) if o.get("artifact_refs"))
            insufficient = any(
                o.get("error", {}).get("code") == "EVIDENCE_INSUFFICIENT" for o in observations
            )
            name, args, id_ = (
                "submit_rag_result",
                {
                    "artifact_ids": [observed["artifact_refs"][0]["artifact_id"]],
                    "outcome": (
                        "insufficient"
                        if insufficient
                        else "complete"
                        if observed.get("document_count")
                        else "unavailable"
                    ),
                },
                "submit",
            )
        return AIMessage(
            content="",
            tool_calls=[{"id": f"{id_}_{len(observations)}", "name": name, "args": args}],
            usage_metadata=usage,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "resume"))
    parser.add_argument("run_id")
    parser.add_argument("scope")
    parser.add_argument("--rag-scope")
    parser.add_argument("--pause-after", choices=("worker", "verifier"))
    parser.add_argument("--cut")
    args = parser.parse_args()
    scope = ReportScope.model_validate_json(Path(args.scope).read_bytes())

    def fault(point):
        if point == args.cut:
            os._exit(91)

    try:
        result = run_async(
            run_durable(
                Settings(llm_mode="fake", max_model_calls=8),
                args.run_id,
                scope.question if args.action == "start" else None,
                resume=args.action == "resume",
                report_scope=scope,
                rag_scope=read_scope(args.rag_scope) if args.rag_scope else None,
                transport=ReportDecisions(
                    scope.document_goal.question if scope.document_goal else ""
                ),
                interrupt_after=[args.pause_after] if args.pause_after else None,
                fault=fault,
            )
        )
    except AgentFailure as exc:
        print(json.dumps({"status": "failed", "error": exc.error.model_dump()}, ensure_ascii=False))
        raise SystemExit(2) from None
    print(json.dumps(result, ensure_ascii=False, default=json_default))


if __name__ == "__main__":
    main()
