"""Nonpaid subprocess acceptance helper, using the original Durable/MCP execution path."""

import argparse
import json
import os
from pathlib import Path

from report_recovery_probe import ReportDecisions

from datapilot.cli import json_default
from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import ReportScope


class InsufficientDecisions(ReportDecisions):
    async def respond(self, messages, tools):
        reply = await super().respond(messages, tools)
        for call in reply.tool_calls:
            if call["name"] == "search_documents":
                call["args"]["top_k"] = 5
            if call["name"] == "submit_rag_result":
                call["args"]["outcome"] = "insufficient"
        return reply


class NoModel:
    async def respond(self, *_):
        raise AssertionError("Recovery must reuse all settled model calls")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "resume", "approve"))
    parser.add_argument("run_id")
    parser.add_argument("config")
    parser.add_argument("--cut")
    parser.add_argument("--pause", action="store_true")
    parser.add_argument("--review", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_bytes())
    scope = ReportScope.model_validate_json(json.dumps(config["report_scope"]))
    rag = RagScope.model_validate_json(json.dumps(config["rag_scope"]))

    def fault(point):
        if point == args.cut:
            os._exit(91)

    try:
        result = run_async(
            run_durable(
                Settings(llm_mode="fake", api_key=None, max_model_calls=8),
                args.run_id,
                scope.question if args.action == "start" else None,
                owner=scope.owner,
                resume=args.action != "start",
                approve=True if args.action == "approve" else None,
                require_review=args.review,
                report_scope=scope,
                rag_scope=rag,
                transport=InsufficientDecisions(scope.document_goal.question)
                if args.action != "resume"
                else NoModel(),
                interrupt_after=["worker"] if args.pause else None,
                fault=fault,
            )
        )
    except AgentFailure as exc:
        print(json.dumps({"error": exc.error.model_dump()}))
        raise SystemExit(2) from None
    print(json.dumps(result, ensure_ascii=False, default=json_default))


if __name__ == "__main__":
    main()
