"""Reader-only MCP server. Management/seed/file/shell capabilities are never registered."""

from mcp.server.fastmcp import FastMCP

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.tools.sql import SQLRepository


def create_server() -> FastMCP:
    settings = Settings(llm_mode="fake", _env_file=None)
    repository = None
    if settings.reader_database_url:
        repository = SQLRepository(
            settings.reader_database_url.get_secret_value(),
            max_rows=settings.max_rows,
            timeout_seconds=settings.query_timeout_seconds,
        )
    server = FastMCP("datapilot-database")

    @server.tool()
    def health() -> dict:
        """Report MCP protocol readiness; this is not a database health check."""
        return {"protocol": "ready", "database_configured": repository is not None}

    @server.tool()
    def database_schema() -> dict:
        """Return approved PostgreSQL table metadata and metric definitions."""
        try:
            if repository is None:
                raise AgentFailure("DATABASE_NOT_CONFIGURED", "Reader DSN is not configured")
            return {"schema": repository.schema(), "error": None}
        except AgentFailure as exc:
            return {"schema": None, "error": exc.error.model_dump()}

    @server.tool()
    def query_database(sql: str) -> dict:
        """Execute one policy-checked read-only business SELECT with strict resource limits."""
        try:
            if repository is None:
                raise AgentFailure("DATABASE_NOT_CONFIGURED", "Reader DSN is not configured")
            return {"result": repository.execute(sql).model_dump(), "error": None}
        except AgentFailure as exc:
            return {"result": None, "error": exc.error.model_dump()}

    return server


if __name__ == "__main__":
    create_server().run(transport="stdio")
