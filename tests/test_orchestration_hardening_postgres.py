"""P4.1 uses genuine MCP/PG; only model decisions are Fake. No schema/data mutations."""

import pytest

from datapilot.graph import run_question

pytestmark = pytest.mark.integration


async def test_p41_real_pg_fast_path_preserves_two_decisions_and_completion(pg_settings):
    result = await run_question(pg_settings, "查询客户总数", include_artifacts=True)
    assert result["status"] == "succeeded" and result["result"].result.rows == [[240]]
    assert result["completion"].status == "completed"
    assert result["usage"]["calls"] == 2 and result["usage"]["reported_tokens"] == 0
    schemas = [a for a in result["artifacts"].values() if a.kind == "schema"]
    assert schemas and "customers" in schemas[0].values["schema"]


async def test_p41_real_invoice_query_is_not_p3_verified_business_completion(pg_settings):
    result = await run_question(pg_settings, "计算2025-10收入")
    assert result["status"] == "succeeded" and result["result"].result.row_count == 1
    assert result["completion"].status == "blocked"
    assert "P3_VERIFIED_EVIDENCE_REQUIRED" in result["completion"].reason_codes


@pytest.mark.parametrize(
    "statements,code,attempts",
    [
        (["DELETE FROM customers"], "SQL_UNSAFE", 1),
        (["SELECT missing_p41_field FROM customers"] * 2, "SQL_EXECUTION_ERROR", 2),
    ],
)
async def test_p41_real_mcp_denial_and_compiler_errors_stay_bounded(
    pg_settings,
    statements,
    code,
    attempts,
):
    result = await run_question(pg_settings, "查询客户总数", scripted_sql=statements)
    assert result["status"] == "failed" and result["error"].code == code
    assert result["result"].attempts == attempts and result["replans"] == 0
    assert result["completion"].status == "blocked"
    assert any(e["node"] == "tool" and e["error_code"] == code for e in result["trace"])


async def test_p41_real_pg_truncation_prevents_full_completion(pg_settings):
    result = await run_question(
        pg_settings.model_copy(update={"max_rows": 1}),
        "查询客户总数",
        scripted_sql=["SELECT customer_id FROM customers ORDER BY customer_id"],
    )
    assert result["status"] == "succeeded" and result["result"].result.row_count == 1
    assert result["result"].result.truncated
    assert result["completion"].status == "incomplete"
    assert "RESULT_TRUNCATED" in result["completion"].reason_codes
