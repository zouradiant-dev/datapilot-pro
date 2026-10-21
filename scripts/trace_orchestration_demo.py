"""Real SQL/MCP with fixture decisions; optional RAG component fixture, never real RAG/LLM."""

import argparse
import asyncio
import json
from pathlib import Path

from datapilot.config import Settings
from datapilot.graph import run_question
from datapilot.orchestration.contracts import Document, SearchResult
from datapilot.orchestration.runtime import text_hash


class FixtureRetrieval:
    async def search(self, query: str, top_k: int) -> SearchResult:
        await asyncio.sleep(0)
        text = (
            "Synthetic release note: dashboard performance improvements. "
            "No customer causal evidence."
        )
        return SearchResult(
            fixture=True,
            documents=[
                Document(
                    document_id="synthetic-release",
                    source="fixture://saas/release",
                    version="fixture-1",
                    text=text,
                    sha256=text_hash(text),
                )
            ],
        )


async def main(args):
    question = (
        "查询客户总数并检索产品文档" if args.with_rag_fixture else "查询客户总数，并计算2025-10收入"
    )
    result = await run_question(
        Settings(llm_mode="fake"),
        question,
        retrieval=FixtureRetrieval() if args.with_rag_fixture else None,
        include_artifacts=True,
    )
    root = Path(__file__).resolve().parents[1] / "artifacts"
    output = args.output.resolve()
    if not output.is_relative_to(root) or output.exists():
        raise ValueError("Use a new output file inside repository artifacts/")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(
            result,
            stream,
            default=lambda value: value.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
    print(
        json.dumps(
            {
                "status": result["status"],
                "mode": "fake model decisions + real SQL/MCP",
                "rag": "fixture" if args.with_rag_fixture else "disabled",
                "trace": str(output),
                "usage": result["usage"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["status"] == "succeeded" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-rag-fixture", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
