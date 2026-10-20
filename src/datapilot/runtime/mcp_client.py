"""Real SDK stdio transport; fixed tools, timeouts and validation of untrusted responses."""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta
from functools import partial
from typing import Protocol

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import ValidationError

from datapilot.config import Settings
from datapilot.contracts import AgentError, AgentFailure, QueryResult
from datapilot.datasets.contracts import (
    DatasetListing,
    DatasetQueryResult,
    DatasetSchema,
    DatasetScope,
)
from datapilot.ingestion.common import digest


class DatabaseTools(Protocol):
    async def schema(self) -> str: ...
    async def execute(self, sql: str) -> QueryResult: ...


class MCPDatabaseTools:
    allowed = frozenset({"health", "database_schema", "query_database"})

    def __init__(self, session: ClientSession, timeout: float):
        self.session = session
        self.timeout = timeout

    async def call(self, name: str, arguments: dict) -> dict:
        if name not in self.allowed:
            raise AgentFailure("TOOL_FORBIDDEN", "Tool is not allowed for the SQL worker")
        try:
            async with asyncio.timeout(self.timeout):
                result = await self.session.call_tool(name, arguments)
        except TimeoutError as exc:
            raise AgentFailure("TOOL_TIMEOUT", "MCP call exceeded its time limit") from exc
        except Exception as exc:
            raise AgentFailure("TOOL_ERROR", "MCP request failed") from exc
        if result.isError:
            raise AgentFailure("TOOL_ERROR", "MCP server rejected the tool call")
        payload = result.structuredContent
        if payload is None:
            try:
                payload = json.loads(next(c.text for c in result.content if c.type == "text"))
            except (ValueError, StopIteration) as exc:
                raise AgentFailure("TOOL_OUTPUT_INVALID", "MCP response was not JSON") from exc
        if not isinstance(payload, dict):
            raise AgentFailure("TOOL_OUTPUT_INVALID", "MCP response must be an object")
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 3 * 1024**2:
            raise AgentFailure("TOOL_OUTPUT_INVALID", "MCP response exceeds the byte limit")
        if payload.get("error"):
            try:
                error = AgentError.model_validate(payload["error"])
            except ValidationError as exc:
                raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid MCP error contract") from exc
            raise AgentFailure(error.code, error.message, retryable=error.retryable)
        return payload

    async def schema(self) -> str:
        data = (await self.call("database_schema", {})).get("schema")
        if not isinstance(data, str) or not data or len(data) > 12000:
            raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid database schema response")
        return data

    async def execute(self, sql: str) -> QueryResult:
        payload = await self.call("query_database", {"sql": sql})
        try:
            return QueryResult.model_validate(payload.get("result"))
        except ValidationError as exc:
            raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid MCP query result") from exc


class MCPDatasetTools(MCPDatabaseTools):
    allowed = frozenset({"health", "list_datasets", "get_dataset_schema", "query_dataset"})

    def __init__(self, session, timeout, *, scope: DatasetScope):
        super().__init__(session, timeout)
        self.bindings = {b.dataset_id: b.version for b in scope.bindings}
        self.pinned = {}

    def _check_binding(self, value):
        if value.dataset_id not in self.bindings:
            raise ValueError("Unexpected dataset")
        expected = self.bindings[value.dataset_id]
        if expected is not None and value.version != expected:
            raise ValueError("Unexpected version")
        identity = (value.version, value.source_sha256)
        if self.pinned.setdefault(value.dataset_id, identity) != identity:
            raise ValueError("Session dataset version changed")

    async def listing(self) -> DatasetListing:
        try:
            result = DatasetListing.model_validate(
                (await self.call("list_datasets", {})).get("listing")
            )
            if {d.dataset_id for d in result.datasets} != set(self.bindings):
                raise ValueError("Incomplete or unexpected listing")
            for value in result.datasets:
                self._check_binding(value)
            return result
        except (ValidationError, ValueError) as exc:
            raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid dataset listing") from exc

    async def schema(self, dataset_id: str) -> DatasetSchema:
        payload = await self.call("get_dataset_schema", {"dataset_id": dataset_id})
        try:
            result = DatasetSchema.model_validate(payload.get("schema"))
            if result.dataset_id != dataset_id:
                raise ValueError("Mismatched dataset")
            self._check_binding(result)
            return result
        except (ValidationError, ValueError) as exc:
            raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid dataset schema") from exc

    async def execute(self, dataset_id: str, sql: str) -> DatasetQueryResult:
        payload = await self.call("query_dataset", {"dataset_id": dataset_id, "sql": sql})
        try:
            result = DatasetQueryResult.model_validate(payload.get("result"))
            if result.dataset_id != dataset_id:
                raise ValueError("Mismatched dataset")
            self._check_binding(result)
            if result.result_sha256 != digest(
                result.result.model_dump(mode="json", exclude={"elapsed_ms"})
            ):
                raise ValueError("Mismatched query result hash")
            return result
        except (ValidationError, ValueError) as exc:
            raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid dataset query result") from exc


def server_environment(settings: Settings) -> dict[str, str]:
    # No provider API key, admin/owner/seed URL, or arbitrary parent environment inheritance.
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PYTHONPATH"}
    }
    env.update(
        {
            "PYTHONUTF8": "1",
            "DATAPILOT_LLM_MODE": "fake",
            "DATAPILOT_MAX_ROWS": str(settings.max_rows),
            "DATAPILOT_QUERY_TIMEOUT_SECONDS": str(settings.query_timeout_seconds),
        }
    )
    return env


@asynccontextmanager
async def _connection(settings, env, tool_class):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "datapilot.runtime.mcp_server"],
        env=env,
    )
    caller_error = None
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=settings.mcp_timeout_seconds)
            ) as session:
                await session.initialize()
                try:
                    yield tool_class(session, settings.mcp_timeout_seconds)
                except Exception as exc:
                    # Close SDK TaskGroups normally before rethrowing a caller/domain failure.
                    # Otherwise AnyIO wraps a normal SQL rejection inside ExceptionGroup.
                    caller_error = exc
    except Exception:
        raise AgentFailure(
            "TOOL_ERROR", "MCP transport could not initialize or close cleanly"
        ) from None
    if caller_error is not None:
        raise caller_error


@asynccontextmanager
async def database_session(settings: Settings):
    env = server_environment(settings)
    if settings.reader_database_url:
        env["DATAPILOT_READER_DATABASE_URL"] = settings.reader_database_url.get_secret_value()
    async with _connection(settings, env, MCPDatabaseTools) as tools:
        yield tools


@asynccontextmanager
async def dataset_session(settings: Settings, scope: DatasetScope):
    # This is a trusted host API, never part of an LLM/MCP tool argument schema.
    scope = DatasetScope.model_validate_json(scope.model_dump_json())
    env = server_environment(settings)
    env["DATAPILOT_DATASET_SCOPE"] = scope.model_dump_json()
    if settings.upload_reader_database_url:
        env["DATAPILOT_UPLOAD_READER_DATABASE_URL"] = (
            settings.upload_reader_database_url.get_secret_value()
        )
    async with _connection(settings, env, partial(MCPDatasetTools, scope=scope)) as tools:
        yield tools
