"""Reader-only MCP server. Management/seed/file/shell capabilities are never registered."""

import json
import os

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetScope
from datapilot.datasets.repository import DatasetRepository
from datapilot.semantics.contracts import MetricRequest
from datapilot.semantics.repository import MetricRepository
from datapilot.tools.sql import SQLRepository


def create_server() -> FastMCP:
    settings = Settings(llm_mode="fake", _env_file=None)
    if settings.rag_reader_database_url:
        from datapilot.rag.contracts import RagScope
        from datapilot.rag.mcp import create_rag_server

        if settings.reader_database_url or settings.upload_reader_database_url:
            raise ValueError("RAG and SQL credentials must use different MCP processes")
        return create_rag_server(
            settings,
            RagScope.model_validate_json(os.environ.get("DATAPILOT_RAG_SCOPE", "{}")),
            goal=os.environ.get("DATAPILOT_RAG_GOAL"),
        )
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

    def metric_request(raw):
        try:
            return MetricRequest.model_validate_json(json.dumps(raw, allow_nan=False))
        except (ValidationError, ValueError, TypeError) as exc:
            raise AgentFailure("INPUT_INVALID", "Invalid bounded metric request") from exc

    @server.tool()
    def get_metric_context(request: dict) -> dict:
        """Read minimum confirmed metric mapping; source authorization is injected by host."""
        try:
            value = MetricRepository(dataset_repository()).context(metric_request(request))
            return {"context": value.model_dump(mode="json"), "error": None}
        except AgentFailure as exc:
            return {"context": None, "error": exc.error.model_dump()}

    @server.tool()
    def recompute_metric(request: dict) -> dict:
        """Independently recompute a closed metric from bounded raw projections; no custom code."""
        try:
            value = MetricRepository(dataset_repository()).proof(metric_request(request))
            return {"proof": value.model_dump(mode="json"), "error": None}
        except AgentFailure as exc:
            return {"proof": None, "error": exc.error.model_dump()}

    @server.tool()
    def get_evidence(dataset_id: str, evidence_id: str) -> dict:
        """Read an immutable evidence record only inside the host-bound dataset version."""
        try:
            value = MetricRepository(dataset_repository()).evidence(dataset_id, evidence_id)
            return {"evidence": value.model_dump(mode="json"), "error": None}
        except AgentFailure as exc:
            return {"evidence": None, "error": exc.error.model_dump()}

    return server


if __name__ == "__main__":
    try:
        create_server().run(transport="stdio")
    except ValueError:
        raise SystemExit(
            "Invalid MCP server configuration; check role and scope settings"
        ) from None
