"""Real SDK stdio transport; fixed tools, timeouts and validation of untrusted responses."""

import asyncio
import json
import os
import sys
import time
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
from datapilot.semantics.contracts import Evidence, MetricContext, MetricProof


class DatabaseTools(Protocol):
    async def schema(self) -> str: ...
    async def execute(self, sql: str) -> QueryResult: ...


class MCPDatabaseTools:
    allowed = frozenset({"health", "database_schema", "query_database"})

    def __init__(self, session: ClientSession, timeout: float):
        self.session = session
        self.timeout = timeout
        self.process_owner = None

    async def call(self, name: str, arguments: dict) -> dict:
        if name not in self.allowed:
            raise AgentFailure("TOOL_FORBIDDEN", "Tool is not allowed for the SQL worker")
        try:
            async with asyncio.timeout(self.timeout):
                result = await self.session.call_tool(name, arguments)
        except asyncio.CancelledError:
            if self.process_owner:
                self.process_owner.arm()
            raise
        except TimeoutError as exc:
            if self.process_owner:
                self.process_owner.arm()
            raise AgentFailure("TOOL_TIMEOUT", "MCP call exceeded its time limit") from exc
        except Exception as exc:
            if self.process_owner:
                self.process_owner.arm()
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


class MCPMetricTools(MCPDatasetTools):
    allowed = MCPDatasetTools.allowed | {
        "get_metric_context",
        "recompute_metric",
        "get_evidence",
        "get_verification",
    }

    def _check_source(self, value):
        expected = self.bindings.get(value.dataset_id)
        if value.dataset_id not in self.bindings or expected != value.dataset_version:
            raise ValueError("Metric sources must be explicitly version-pinned by the host")
        identity = (value.dataset_version, value.source_sha256)
        if self.pinned.setdefault(value.dataset_id, identity) != identity:
            raise ValueError("Source identity changed")

    async def context(self, request):
        payload = await self.call(
            "get_metric_context", {"request": request.model_dump(mode="json")}
        )
        try:
            result = MetricContext.model_validate_json(json.dumps(payload.get("context")))
            self._check_source(result)
            if (
                digest(result.model_dump(mode="json", exclude={"context_sha256"}))
                != result.context_sha256
            ):
                raise ValueError("Invalid context hash")
            from datapilot.semantics.recipes import request_missing

            request_missing(result, request)
            return result
        except (ValidationError, ValueError) as exc:
            raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid metric context") from exc

    async def recompute(self, request):
        payload = await self.call("recompute_metric", {"request": request.model_dump(mode="json")})
        try:
            result = MetricProof.model_validate_json(json.dumps(payload.get("proof")))
            if result.request_sha256 != digest(request):
                raise ValueError("Proof request mismatch")
            return result
        except (ValidationError, ValueError) as exc:
            raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid independent proof") from exc

    async def evidence(self, dataset_id, evidence_id):
        payload = await self.call(
            "get_evidence", {"dataset_id": dataset_id, "evidence_id": evidence_id}
        )
        try:
            result = Evidence.model_validate_json(json.dumps(payload.get("evidence")))
            self._check_source(result)
            if result.evidence_id != evidence_id or result.dataset_id != dataset_id:
                raise ValueError("Evidence reference mismatch")
            return result
        except (ValidationError, ValueError) as exc:
            raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid evidence reference") from exc

    async def verification(self, dataset_id, verification_id):
        from datapilot.semantics.contracts import VerificationRecord

        payload = await self.call(
            "get_verification", {"dataset_id": dataset_id, "verification_id": verification_id}
        )
        try:
            value = VerificationRecord.model_validate_json(json.dumps(payload.get("verification")))
            if value.dataset_id != dataset_id or value.verification_id != verification_id:
                raise ValueError("Verification reference mismatch")
            if self.bindings.get(dataset_id) != value.dataset_version:
                raise ValueError("Verification version outside scope")
            return value
        except (ValueError, TypeError) as exc:
            raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid verification reference") from exc


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
async def _connection(settings, env, tool_class, *, executable=None, isolated=False):
    args = ["-m", "datapilot.runtime.mcp_server"]
    if isolated:
        from datapilot.rag.models import ROOT

        # -I ignores PYTHONHOME/PYTHONPATH, user site and current-directory modules.
        args = [
            "-I",
            "-c",
            (
                "import sys,time,os,json,runpy\n"
                # Linux has no Windows venv redirector to reap a hard-exited parent's
                # native/GIL-stalled child. Bind before imports/model work; fail closed.
                "if sys.platform=='linux':\n"
                " import ctypes,signal\n"
                " parent=os.getppid()\n"
                " if ctypes.CDLL(None).prctl(1,signal.SIGKILL,0,0,0)!=0 "
                "or os.getppid()!=parent: raise RuntimeError('MCP parent binding failed')\n"
                "print(json.dumps({'component':'qwen_lifecycle','phase':'python_boot',"
                "'wall_time':time.time(),'pid':os.getpid()}),file=sys.stderr,flush=True);"
                "sys.path.insert(0,sys.argv[1]);"
                "runpy.run_module('datapilot.runtime.mcp_server',run_name='__main__')"
            ),
            str(ROOT / "src"),
        ]
    params = StdioServerParameters(
        command=executable or sys.executable,
        args=args,
        env=env,
    )
    caller_error, tools = None, None
    started, wall_started = time.monotonic(), time.time()
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=settings.mcp_timeout_seconds)
            ) as session:
                await session.initialize()
                tools = tool_class(session, settings.mcp_timeout_seconds)
                tools.transport_seconds = time.monotonic() - started
                tools.spawn_wall_started = wall_started
                try:
                    yield tools
                except Exception as exc:
                    # Close SDK TaskGroups normally before rethrowing a caller/domain failure.
                    # Otherwise AnyIO wraps a normal SQL rejection inside ExceptionGroup.
                    caller_error = exc
                finally:
                    if getattr(tools, "process_owner", None):
                        tools.process_owner.arm()
    except Exception:
        raise AgentFailure(
            "TOOL_ERROR", "MCP transport could not initialize or close cleanly"
        ) from None
    finally:
        if tools is not None and getattr(tools, "process_owner", None):
            tools.process_owner.close()
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


@asynccontextmanager
async def metric_session(settings: Settings, scope: DatasetScope):
    scope = DatasetScope.model_validate_json(scope.model_dump_json())
    if any(b.version is None for b in scope.bindings):
        raise ValueError("Metric sessions require explicit dataset versions")
    env = server_environment(settings)
    env["DATAPILOT_DATASET_SCOPE"] = scope.model_dump_json()
    if settings.upload_reader_database_url:
        env["DATAPILOT_UPLOAD_READER_DATABASE_URL"] = (
            settings.upload_reader_database_url.get_secret_value()
        )
    async with _connection(settings, env, partial(MCPMetricTools, scope=scope)) as tools:
        yield tools
