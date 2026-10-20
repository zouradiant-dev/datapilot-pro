"""Real SDK stdio transport; fixed tools, timeouts and validation of untrusted responses."""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Protocol

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import ValidationError

from datapilot.config import Settings
from datapilot.contracts import AgentError, AgentFailure, QueryResult


class DatabaseTools(Protocol):
    async def schema(self) -> str: ...
    async def execute(self, sql: str) -> QueryResult: ...


class MCPDatabaseTools:
    def __init__(self, session: ClientSession, timeout: float):
        self.session = session
        self.timeout = timeout

    async def call(self, name: str, arguments: dict) -> dict:
        if name not in {"health", "database_schema", "query_database"}:
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


@asynccontextmanager
async def database_session(settings: Settings):
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
    if settings.reader_database_url:
        env["DATAPILOT_READER_DATABASE_URL"] = settings.reader_database_url.get_secret_value()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "datapilot.runtime.mcp_server"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=settings.mcp_timeout_seconds)
        ) as session:
            await session.initialize()
            yield MCPDatabaseTools(session, settings.mcp_timeout_seconds)
