"""Reader-only MCP server. Management/seed/file/shell capabilities are never registered."""

import os

from mcp.server.fastmcp import FastMCP

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetScope
from datapilot.datasets.repository import DatasetRepository
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
    datasets = None
    if settings.upload_reader_database_url:
        datasets = DatasetRepository(
            settings.upload_reader_database_url.get_secret_value(),
            DatasetScope.model_validate_json(os.environ.get("DATAPILOT_DATASET_SCOPE", "{}")),
            max_rows=settings.max_rows,
            timeout_seconds=settings.query_timeout_seconds,
        )

    @server.tool()
    def health() -> dict:
        """Report MCP protocol readiness; this is not a database health check."""
        return {
            "protocol": "ready",
            "database_configured": repository is not None or datasets is not None,
        }

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

    def dataset_repository():
        if datasets is None:
            raise AgentFailure("DATABASE_NOT_CONFIGURED", "Upload reader DSN is not configured")
        return datasets

    @server.tool()
    def list_datasets() -> dict:
        """List only datasets/versions bound by the trusted host to this session."""
        try:
            return {"listing": dataset_repository().listing().model_dump(), "error": None}
        except AgentFailure as exc:
            return {"listing": None, "error": exc.error.model_dump()}

    @server.tool()
    def get_dataset_schema(dataset_id: str) -> dict:
        """Return physical tables and original column mappings of a server-authorized dataset."""
        try:
            return {"schema": dataset_repository().schema(dataset_id).model_dump(), "error": None}
        except AgentFailure as exc:
            return {"schema": None, "error": exc.error.model_dump()}

    @server.tool()
    def query_dataset(dataset_id: str, sql: str) -> dict:
        """Execute one read-only SELECT inside this dataset's server-bound physical-table scope."""
        try:
            return {
                "result": dataset_repository().execute(dataset_id, sql).model_dump(),
                "error": None,
            }
        except AgentFailure as exc:
            return {"result": None, "error": exc.error.model_dump()}

    return server


if __name__ == "__main__":
    try:
        create_server().run(transport="stdio")
    except ValueError:
        raise SystemExit(
            "Invalid MCP server configuration; check role and scope settings"
        ) from None
