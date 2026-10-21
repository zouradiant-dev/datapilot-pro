"""Small synthetic-source retrieval measurements; paid chat inference is explicit opt-in.

Exports no source bodies, vectors, prompts or connection credentials.
"""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from datapilot.config import Settings
from datapilot.persistence.backend import Backend, DurableArtifacts, execute
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.cli import read_scope
from datapilot.rag.mcp import rag_session

ROOT = Path(__file__).resolve().parents[1]
GOLD = [
    ("客户首次使用怎样更快体会产品价值？", "onboarding.md"),
    ("有哪些改善顾客续订意愿的候选措施？", "onboarding.md"),
    ("已付款账单和经常性订阅金额有什么区别？", "billing.md"),
    ("新版本如何改善仪表板的响应？", "release.md"),
]


async def measure(scope, live):
    output = {
        "corpus": "explicitly approved synthetic sources",
        "embedding": "real local BGE CPU",
        "chat_api_calls": 0,
        "retrieval": [],
        "cost": {"amount": None, "status": "no_invoice"},
    }
    settings = Settings(llm_mode="fake")
    async with rag_session(settings, scope) as tools:
        for n, (query, expected) in enumerate(GOLD):
            started = time.perf_counter()
            result = await tools.search(query, 2)
            assert (
                result.documents and result.documents[0].source == expected and not result.fixture
            )
            c = result.documents[0].citation
            output["retrieval"].append(
                {
                    "gold_id": n + 1,
                    "top_source": expected,
                    "score": c.score,
                    "source_sha256": c.source_sha256,
                    "chunk_id": c.chunk_id,
                    "index_version": c.index_version,
                    "span": [c.start, c.end],
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    "embedding_usage": result.embedding_usage.model_dump(),
                }
            )
    if live:
        settings = Settings(llm_mode="live")
        id_ = str(uuid4())
        started = time.perf_counter()
        result = await run_durable(
            settings, id_, "仅检索客户入门培训相关文档片段，保留实际来源引用", rag_scope=scope
        )
        repeated = None
        if result["status"] == "succeeded":
            repeated = await run_durable(settings, id_, resume=True, rag_scope=scope)
            assert repeated["usage"] == result["usage"] and repeated["results"] == result["results"]
        b = Backend(settings.runtime_database_url.get_secret_value(), id_, "local-user")
        try:
            store = DurableArtifacts(b)
            docs = [a.documents for a in store.export().values() if a.kind == "documents"]
            found = bool(docs) and any(
                d.source == "onboarding.md" for batch in docs for d in batch.documents
            )
            with b.transaction() as conn:
                calls = (
                    execute(
                        conn,
                        "SELECT usage,elapsed_ms FROM execution.calls "
                        "WHERE run_id=:run AND kind='model' ORDER BY call_key",
                        run=id_,
                    )
                    .mappings()
                    .all()
                )
            output["live"] = {
                "provider": settings.model_provider,
                "model": settings.model,
                "status": result["status"],
                "completion": result["completion"].status,
                "accepted": result["status"] == "succeeded"
                and result["completion"].status == "completed"
                and found,
                "error_codes": [r.error.code for r in result["results"].values() if r.error],
                "usage": result["usage"],
                "elapsed_ms_including_repeat_resume": round(
                    (time.perf_counter() - started) * 1000, 3
                ),
                "calls": [dict(c) for c in calls],
                "repeat_resume_extra_calls": 0 if repeated is not None else None,
                "corpus_documents": [
                    {
                        "source": d.source,
                        "chunk_id": d.citation.chunk_id,
                        "source_sha256": d.citation.source_sha256,
                    }
                    for batch in docs
                    for d in batch.documents
                ],
            }
            output["chat_api_calls"] = result["usage"]["calls"]
        finally:
            b.close()
    destination = ROOT / "artifacts/p6a/measurements.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"artifact": str(destination), "gold_cases": len(GOLD), "live": output.get("live")},
            ensure_ascii=False,
        )
    )
    if live and not output["live"]["accepted"]:
        raise SystemExit(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    run_async(measure(read_scope(args.scope), args.live))


if __name__ == "__main__":
    main()
