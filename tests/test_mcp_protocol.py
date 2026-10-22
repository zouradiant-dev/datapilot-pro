import pytest

from datapilot.contracts import AgentFailure
from datapilot.runtime.mcp_client import database_session


@pytest.mark.protocol
async def test_real_stdio_handshake_tool_listing_and_missing_database(settings):
    async with database_session(settings) as tools:
        listing = await tools.session.list_tools()
        assert {t.name for t in listing.tools} == {
            "health",
            "database_schema",
            "query_database",
            "list_datasets",
            "get_dataset_schema",
            "query_dataset",
            "get_metric_context",
            "recompute_metric",
            "get_evidence",
            "get_verification",
        }
        assert not any(
            t.name in {"import_file", "create_table", "activate_version"} for t in listing.tools
        )
        assert (await tools.call("health", {})) == {
            "protocol": "ready",
            "database_configured": False,
        }
        with pytest.raises(AgentFailure) as error:
            await tools.schema()
        assert error.value.error.code == "DATABASE_NOT_CONFIGURED"
        with pytest.raises(AgentFailure) as error:
            await tools.call("delete_file", {})
        assert error.value.error.code == "TOOL_FORBIDDEN"
