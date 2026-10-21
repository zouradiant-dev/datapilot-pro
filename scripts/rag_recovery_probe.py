"""Real RAG/PG cross-process probe. Model decisions are explicitly deterministic, not live."""

import argparse
import json
import os

from langchain_core.messages import AIMessage

from datapilot.cli import json_default
from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.orchestration.contracts import Plan, TaskSpec
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.cli import read_scope


class RagDecisions:
    def __init__(self, scenario="normal"):
        self.scenario = scenario

    async def respond(self, messages, tools):
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        if messages[0].content.startswith("PLAN_JSON"):
            return AIMessage(
                content=Plan(
                    tasks=[
                        TaskSpec(
                            task_id="rag",
                            worker="rag",
                            instruction="客户首次使用怎样更快体会产品价值？",
                        )
                    ]
                ).model_dump_json(),
                usage_metadata=usage,
            )
        observations = [json.loads(m.content) for m in messages if m.type == "tool"]
        searches = sum(m.type == "tool" and m.name == "search_documents" for m in messages)
        corrected = any(getattr(m, "name", None) == "rag_completion_gate" for m in messages)
        search_more = self.scenario in {"two-search", "closed-search"} and searches < 2
        if self.scenario == "closed-search" and searches == 2 and not corrected:
            search_more = True
        if observations and not search_more:
            if self.scenario == "plain" and not corrected:
                return AIMessage(content="已找到片段。", usage_metadata=usage)
            if self.scenario == "malformed" and not corrected:
                return AIMessage(
                    content="",
                    invalid_tool_calls=[
                        {
                            "id": "invalid-submit",
                            "name": "submit_rag_result",
                            "args": "{bad",
                            "error": "parse error",
                        }
                    ],
                    usage_metadata=usage,
                )
            value = next(o for o in reversed(observations) if o.get("artifact_refs"))
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "submit_rag",
                        "name": "submit_rag_result",
                        "args": {
                            "artifact_ids": [value["artifact_refs"][0]["artifact_id"]],
                            "outcome": "unavailable"
                            if value.get("document_count") == 0
                            else "complete",
                        },
                    }
                ],
                usage_metadata=usage,
            )
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": f"rag_search_{searches}",
                    "name": "search_documents",
                    "args": {"query": "客户首次使用怎样更快体会产品价值？", "top_k": 3},
                }
            ],
            usage_metadata=usage,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "resume"))
    parser.add_argument("run_id")
    parser.add_argument("scope")
    parser.add_argument("--pause", action="store_true")
    parser.add_argument("--cut-tool-committed", action="store_true")
    parser.add_argument("--cut-point")
    parser.add_argument(
        "--scenario",
        choices=("normal", "plain", "malformed", "two-search", "closed-search", "semantic"),
        default="normal",
    )
    args = parser.parse_args()

    def fault(point):
        if (args.cut_tool_committed and point == "tool_committed") or point == args.cut_point:
            os._exit(91)

    try:
        result = run_async(
            run_durable(
                Settings(llm_mode="fake"),
                args.run_id,
                (
                    "仅检索客户入门培训相关文档片段，保留实际来源引用"
                    if args.scenario == "semantic"
                    else "检索包含“入门培训”的文档片段，保留实际来源引用"
                )
                if args.action == "start"
                else None,
                resume=args.action == "resume",
                rag_scope=read_scope(args.scope),
                transport=RagDecisions(args.scenario),
                interrupt_after=["worker"] if args.pause else None,
                fault=fault,
            )
        )
    except AgentFailure as exc:
        print(json.dumps({"status": "failed", "error": exc.error.model_dump()}, ensure_ascii=False))
        raise SystemExit(2) from None
    print(json.dumps(result, default=json_default, ensure_ascii=False))


if __name__ == "__main__":
    main()
