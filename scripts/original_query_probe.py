"""Nonpaid scripted transport acceptance, original Gateway/Journal/MCP only."""

import argparse
import json
import os
from pathlib import Path

from langchain_core.messages import AIMessage
from partial_evidence_probe import NoModel
from report_recovery_probe import ReportDecisions

from datapilot.cli import json_default
from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import ReportScope


class Script(ReportDecisions):
    """Choose the first query before returning an AIMessage to the real Gateway."""

    def __init__(
        self, query, *, ignore=False, insufficient=False, finish_only=False, second_query=None
    ):
        super().__init__(query)
        self.ignore, self.insufficient, self.finish_only = ignore, insufficient, finish_only
        self.second_query = second_query

    async def respond(self, messages, tools):
        observations = [m for m in messages if m.type == "tool"]
        if self.finish_only and (
            messages[0].content.startswith("REPORT_PLAN_JSON")
            or not any(
                m.type == "tool" and json.loads(m.content).get("artifact_refs") for m in messages
            )
        ):
            raise AssertionError(
                "Resume must reuse the planner/search decision, not request it again"
            )
        if not self.finish_only and self.second_query is not None and len(observations) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "followup_1",
                        "name": "search_documents",
                        "args": {"query": self.second_query, "top_k": 5},
                    }
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        reply = await super().respond(messages, tools)
        for call in reply.tool_calls:
            if call["name"] == "search_documents":
                if self.finish_only:
                    raise AssertionError("Resume may submit once, never search again")
                call["args"]["top_k"] = 5
                for schema in tools:
                    if schema["function"]["name"] != "search_documents":
                        continue
                    description = schema["function"]["parameters"]["properties"]["query"].get(
                        "description", ""
                    )
                    if not self.ignore and "HOST_FIRST_QUERY_JSON: " in description:
                        call["args"]["query"] = json.loads(
                            description.split("HOST_FIRST_QUERY_JSON: ", 1)[1]
                        )
            elif call["name"] == "submit_rag_result" and self.insufficient:
                call["args"]["outcome"] = "insufficient"
        return reply


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "resume"))
    parser.add_argument("run_id")
    parser.add_argument("config")
    parser.add_argument("--cut")
    parser.add_argument("--pause", action="store_true")
    parser.add_argument("--ignore", action="store_true")
    parser.add_argument("--insufficient", action="store_true")
    parser.add_argument("--finish", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_bytes())
    scope = ReportScope.model_validate_json(json.dumps(config["report_scope"]))
    rag = RagScope.model_validate_json(json.dumps(config["rag_scope"]))
    committed_models = committed_tools = 0

    def fault(point):
        nonlocal committed_models, committed_tools
        if point == "model_committed":
            committed_models += 1
        if point == "tool_committed":
            committed_tools += 1
        if (
            point == args.cut
            or args.cut == "worker_model_committed"
            and point == "model_committed"
            and committed_models == 2
            or args.cut == "second_search_committed"
            and point == "tool_committed"
            and committed_tools == 2
        ):
            os._exit(91)

    transport = Script(
        config.get("model_query", "Explain the requested policy in English"),
        ignore=args.ignore,
        insufficient=args.insufficient,
        finish_only=args.finish,
        second_query=config.get("second_query"),
    )
    try:
        result = run_async(
            run_durable(
                Settings(llm_mode="fake", api_key=None, max_model_calls=8),
                args.run_id,
                scope.question if args.action == "start" else None,
                owner=scope.owner,
                resume=args.action == "resume",
                report_scope=scope,
                rag_scope=rag,
                transport=transport if args.action == "start" or args.finish else NoModel(),
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
