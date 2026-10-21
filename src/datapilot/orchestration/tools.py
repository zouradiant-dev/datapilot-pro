"""Fixed capability registry; no shell, filesystem, management or model-created tools."""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Protocol

from pydantic import Field

from datapilot.contracts import AgentFailure, Contract, QueryResult
from datapilot.orchestration.context import tool_view
from datapilot.orchestration.contracts import Artifact, SearchResult
from datapilot.orchestration.runtime import Cancellation, text_hash


class Empty(Contract):
    pass


class SQLArguments(Contract):
    sql: str = Field(min_length=1, max_length=12000)


class SearchArguments(Contract):
    query: str = Field(min_length=1, max_length=512)
    top_k: int = Field(default=3, ge=1, le=5)


class RetrievalTools(Protocol):
    async def search(self, query: str, top_k: int) -> SearchResult: ...


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    arguments: type[Contract]
    description: str

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments.model_json_schema(),
            },
        }


DEFINITIONS = {
    "database_schema": ToolDefinition(
        "database_schema", Empty, "Read approved SaaS schema metadata"
    ),
    "query_database": ToolDefinition(
        "query_database", SQLArguments, "Read-only PostgreSQL SaaS SELECT; no write or file tools"
    ),
    "search_documents": ToolDefinition(
        "search_documents",
        SearchArguments,
        "Retrieve permitted documents and immutable source/version citations",
    ),
}
CAPABILITIES = {
    "sql": frozenset({"database_schema", "query_database"}),
    "rag": frozenset({"search_documents"}),
    "analysis": frozenset(),
    "report": frozenset(),
}


class ToolRegistry:
    def __init__(
        self,
        envelope,
        store,
        *,
        database=None,
        retrieval=None,
        cancellation=None,
        trace=None,
        timeout=10,
        max_sql_attempts=2,
        max_view_chars=4096,
    ):
        self.envelope, self.store = envelope, store
        self.database = database if envelope.task.worker == "sql" else None
        self.retrieval = retrieval if envelope.task.worker == "rag" else None
        approved = CAPABILITIES[envelope.task.worker]
        if not set(envelope.allowed_tools) <= approved:
            raise AgentFailure("TOOL_FORBIDDEN", "Child permissions exceed its worker capability")
        self.allowed = frozenset(envelope.allowed_tools)
        self.refs = []
        self.sql_attempts = 0
        self.cancel = cancellation or Cancellation()
        self.trace, self.timeout = trace, timeout
        self.max_sql_attempts, self.max_view_chars = max_sql_attempts, max_view_chars

    def schemas(self):
        return [DEFINITIONS[name].schema() for name in sorted(self.allowed)]

    async def invoke(self, name, arguments, *, call_id=None):
        """Sealed host lifecycle; there are no user callbacks that can override denial.

        Contract → delegated capability/bound MCP handle → cancellation/attempt budget/
        timeout → call → validated full artifact → bounded model view → redacted trace.
        DatasetScope/DB grants stay enforced inside the already-bound MCP session.
        """
        started, error = time.monotonic(), None
        before = len(self.refs)
        try:
            if name not in DEFINITIONS:
                raise AgentFailure("TOOL_FORBIDDEN", "Tool is outside delegated capability")
            try:
                if len(json.dumps(arguments, ensure_ascii=False)) > 13000:
                    raise ValueError("Arguments too large")
                args = DEFINITIONS[name].arguments.model_validate(arguments)
            except (ValueError, TypeError) as exc:
                raise AgentFailure("INPUT_INVALID", "Tool arguments failed their contract") from exc
            if name not in self.allowed:
                raise AgentFailure("TOOL_FORBIDDEN", "Tool is outside delegated capability")
            if (name in {"database_schema", "query_database"} and self.database is None) or (
                name == "search_documents" and self.retrieval is None
            ):
                raise AgentFailure("TOOL_FORBIDDEN", "No host-bound tool session was delegated")
            self.cancel.check()
            if name == "query_database" and self.sql_attempts >= self.max_sql_attempts:
                raise AgentFailure("SQL_ATTEMPTS_EXHAUSTED", "SQL attempt limit reached")
            if name == "query_database":
                # No await before reservation: simultaneous calls cannot both take the last slot.
                self.sql_attempts += 1
            return await self.cancel.wait_for(self._dispatch(name, args), self.timeout)
        except asyncio.CancelledError:
            error = AgentFailure("CANCELLED", "Tool coroutine was cancelled")
            raise
        except AgentFailure as exc:
            error = exc
            raise
        except Exception as exc:
            error = AgentFailure("TOOL_OUTPUT_INVALID", "Tool failed its validated output contract")
            raise error from exc
        finally:
            if self.trace:
                self.trace.emit(
                    "tool",
                    "failed" if error else "succeeded",
                    version=self.envelope.plan_version,
                    task_id=self.envelope.task.task_id,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                    error_code=error.error.code if error else None,
                    tool_name=name if name in DEFINITIONS else "undeclared",
                    tool_call_id=call_id,
                    refs=self.refs[before:] if not error else (),
                )

    async def _dispatch(self, name, args):
        if name == "database_schema":
            value = await self.database.schema()
            if not isinstance(value, str) or not 1 <= len(value) <= 12000:
                raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid schema response")
            # Schema is authoritative input: store it whole, never silently crop it.
            self.store.put(
                Artifact(
                    run_id=self.envelope.run_id,
                    task_id=self.envelope.task.task_id,
                    plan_version=self.envelope.plan_version,
                    kind="schema",
                    source="host-bound/MCP",
                    values={"schema": value},
                )
            )
            return {"schema": value}
        if name == "query_database":
            value = await self.database.execute(args.sql)
            value = QueryResult.model_validate_json(value.model_dump_json())
            artifact = Artifact(
                run_id=self.envelope.run_id,
                task_id=self.envelope.task.task_id,
                plan_version=self.envelope.plan_version,
                kind="query",
                source="saas/PostgreSQL",
                sql=args.sql,
                query=value,
            )
        else:
            value = await self.retrieval.search(args.query, args.top_k)
            value = SearchResult.model_validate_json(value.model_dump_json())
            if len(value.documents) > args.top_k or any(
                text_hash(d.text) != d.sha256 for d in value.documents
            ):
                raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid document source/hash contract")
            artifact = Artifact(
                run_id=self.envelope.run_id,
                task_id=self.envelope.task.task_id,
                plan_version=self.envelope.plan_version,
                kind="documents",
                source="retrieval-fixture" if value.fixture else "retrieval",
                documents=value,
            )
        ref = self.store.put(artifact)
        self.refs.append(ref)
        return tool_view(artifact, ref, self.max_view_chars)
