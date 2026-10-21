"""Real MCP/PostgreSQL execution; the RAG backend and model decisions are labelled fixtures."""

import json
from pathlib import Path

import pytest

from datapilot.graph import run_question
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Document, SearchResult
from datapilot.orchestration.runtime import text_hash

pytestmark = pytest.mark.integration


class RetrievalFixture:
    async def search(self, query, top_k):
        text = "Synthetic document, no real embedding or causal evidence."
        return SearchResult(
            fixture=True,
            documents=[
                Document(
                    document_id="fixture",
                    source="fixture://product",
                    version="1",
                    text=text,
                    sha256=text_hash(text),
                )
            ],
        )


@pytest.mark.parametrize("with_rag", [False, True])
async def test_new_dag_real_pg_mcp_and_trace_bundle(pg_settings, with_rag):
    question = "查询客户总数并检索产品文档" if with_rag else "查询客户总数，并计算2025-10收入"
    result = await run_question(
        pg_settings,
        question,
        retrieval=RetrievalFixture() if with_rag else None,
        include_artifacts=True,
    )
    assert result["status"] == "succeeded", result.get("error")
    queries = [a for a in result["artifacts"].values() if a.kind == "query"]
    assert any(a.query.rows == [[240]] for a in queries)
    assert len(queries) == (1 if with_rag else 2)
    for artifact_id, artifact in result["artifacts"].items():
        assert digest(artifact) == artifact_id
    assert all(v.status == "passed" for v in result["verifications"].values())
    assert result["usage"]["calls"] == 5 and result["usage"]["reported_tokens"] == 0
    assert any(e["node"] == "scheduler" for e in result["trace"])
    serialized = json.dumps(result["trace"])
    assert "SELECT" not in serialized and "Synthetic document" not in serialized
    path = (
        Path(__file__).resolve().parents[1]
        / "artifacts/p4"
        / ("pg-rag-fixture.json" if with_rag else "pg-two-sql.json")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            result, default=lambda x: x.model_dump(mode="json"), ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
