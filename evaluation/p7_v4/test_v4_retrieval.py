"""Explicit nonpaid PG/MCP checks on a new public Dev corpus, never Live data."""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation/p7_v3"))

from v3_common import clean_settings, infrastructure  # noqa: E402

from datapilot.contracts import AgentFailure  # noqa: E402
from datapilot.persistence.session import run_async  # noqa: E402
from datapilot.rag.contracts import RagScope  # noqa: E402
from datapilot.rag.mcp import rag_session  # noqa: E402

QUERIES = [
    "青栈离线清单下载地址多久后失效？",
    "宇宙微波背景辐射功率谱声学峰与原初引力波偏振",
]
GOAL = "查找青栈清单下载有效期与协作授权的公开说明。"


@pytest.fixture(scope="module")
def observed():
    assert os.environ.get("DATAPILOT_RUN_DB_TESTS") == "1", "Explicit real PG test only"
    bindings = json.loads((ROOT / "artifacts/p7/scorer-v4/dev/bindings.json").read_bytes())
    values = infrastructure(ROOT / "artifacts/p7/unified-regression/private/environment.json")
    settings = clean_settings(values)
    scope = RagScope.model_validate_json(json.dumps(bindings["scope"]))

    async def retrieve():
        async with rag_session(settings, scope, goal=GOAL) as tools:
            return [await tools.search(q, top_k=5) for q in QUERIES]

    rows = run_async(retrieve())
    return rows, bindings["manifest"], settings, scope


def test_real_pg_mcp_known_dev_document_and_exact_pins(observed):
    rows, manifest, _, scope = observed
    expected = next(s["document_id"] for s in manifest["sources"] if s["name"] == "process.md")
    assert expected in {d.citation.document_id for d in rows[0].documents}
    for document in rows[0].documents:
        citation = document.citation
        assert citation.index_version == scope.corpora[0].index_version
        assert citation.document_id in scope.corpora[0].document_ids
        assert citation.score >= 0.55 and citation.end > citation.start


def test_real_pg_mcp_empty_retrieval_is_not_fake_success(observed):
    rows, _, _, _ = observed
    assert rows[1].documents == [] and rows[1].unavailable_reason == "no_matches"


def test_real_pg_mcp_unauthorized_index_is_denied(observed):
    _, _, settings, scope = observed
    changed = scope.model_dump(mode="json")
    changed["corpora"][0]["index_version"] = "0" * 64

    async def refuse():
        async with rag_session(settings, RagScope.model_validate_json(json.dumps(changed))):
            raise AssertionError("Unauthorized scope was accepted")

    with pytest.raises(AgentFailure) as failure:
        run_async(refuse())
    assert failure.value.error.code == "DOCUMENT_NOT_AUTHORIZED"
