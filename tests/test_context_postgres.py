"""Genuine PG/MCP long loop; explicit deterministic model decisions, no supplier inference."""

import json

import pytest
from langchain_core.messages import AIMessage

from datapilot.graph import run_question

pytestmark = pytest.mark.integration


class LongSchemaDecisions:
    def __init__(self):
        self.turns = 0

    async def respond(self, messages, tools):
        self.turns += 1
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        if self.turns <= 11:
            name, args = "database_schema", {}
        elif self.turns == 12:
            name, args = "query_database", {"sql": "SELECT COUNT(*) AS n FROM customers"}
        else:
            ref = json.loads(messages[-1].content)["artifact_refs"][0]["artifact_id"]
            return AIMessage(content=json.dumps({"artifact_ids": [ref]}), usage_metadata=usage)
        return AIMessage(
            content="synthetic non-authoritative note " + "x" * 1800,
            tool_calls=[{"id": f"schema_{self.turns}", "name": name, "args": args}],
            usage_metadata=usage,
        )


@pytest.mark.parametrize("enabled", [False, True])
async def test_long_real_mcp_sql_loop_preserves_pg_results_and_safety(pg_settings, enabled):
    config = pg_settings.model_copy(
        update={
            "max_model_calls": 20,
            "max_worker_turns": 20,
            "max_total_tokens": 100000,
            "max_context_tokens": 24000 if enabled else 100000,
            "max_input_chars": 14000 if enabled else 64000,
            "context_compression": enabled,
            "context_keep_batches": 1,
            "context_allow_summary": False,
        }
    )
    result = await run_question(
        config, "查询客户总数", transport=LongSchemaDecisions(), include_artifacts=True
    )
    assert result["status"] == "succeeded", result.get("error")
    assert result["completion"].status == "completed"
    assert result["result"].result.rows == [[240]] and result["result"].attempts == 1
    assert result["usage"]["calls"] == 13 and result["usage"]["reported_tokens"] == 0
    compression = [e["compression"] for e in result["trace"] if e["compression"]]
    if enabled:
        assert compression and any("L3" in e["levels"] for e in compression)
        assert all(not e["irreversible_source_loss"] for e in compression)
        archives = [a for a in result["artifacts"].values() if a.kind == "context"]
        assert archives and any("schema_10" in a.values["messages"] for a in archives)
    else:
        assert not compression
    assert "SELECT COUNT" not in json.dumps(result["trace"])
