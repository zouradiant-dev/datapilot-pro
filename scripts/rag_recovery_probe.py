"""Real RAG/PG cross-process probe. Model decisions are explicitly deterministic, not live."""

import argparse
import json
import os

from langchain_core.messages import AIMessage

from datapilot.cli import json_default
from datapilot.config import Settings
from datapilot.orchestration.contracts import Plan, TaskSpec
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.cli import read_scope


class RagDecisions:
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
        if messages[-1].type == "tool":
            value = json.loads(messages[-1].content)
            return AIMessage(
                content=json.dumps(
                    {
                        "artifact_ids": [value["artifact_refs"][0]["artifact_id"]],
                        "outcome": "unavailable"
                        if value.get("document_count") == 0
                        else "complete",
                    }
                ),
                usage_metadata=usage,
            )
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "rag_search",
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
    args = parser.parse_args()

    def fault(point):
        if args.cut_tool_committed and point == "tool_committed":
            os._exit(91)

    result = run_async(
        run_durable(
            Settings(llm_mode="fake"),
            args.run_id,
            "检索客户培训文档" if args.action == "start" else None,
            resume=args.action == "resume",
            rag_scope=read_scope(args.scope),
            transport=RagDecisions(),
            interrupt_after=["worker"] if args.pause else None,
            fault=fault,
        )
    )
    print(json.dumps(result, default=json_default, ensure_ascii=False))


if __name__ == "__main__":
    main()
