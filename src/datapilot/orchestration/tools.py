"""Fixed capability registry; no shell, filesystem, management or model-created tools."""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Protocol

from pydantic import Field

from datapilot.contracts import AgentFailure, Contract, QueryResult
from datapilot.orchestration.context import tool_view
from datapilot.orchestration.contracts import Artifact, Digest, SearchResult
from datapilot.orchestration.runtime import Cancellation, text_hash


class Empty(Contract):
    pass


class SQLArguments(Contract):
    sql: str = Field(min_length=1, max_length=12000)


class SearchArguments(Contract):
    query: str = Field(min_length=1, max_length=512)
    top_k: int = Field(default=3, ge=1, le=5)


class ContextReadArguments(Contract):
    artifact_id: Digest
    start: int = Field(default=0, ge=0, le=16 * 1024**2)
    max_chars: int = Field(default=512, ge=64, le=2048)
    document_id: str | None = Field(default=None, min_length=1, max_length=128)


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
    "read_context": ToolDefinition(
        "read_context",
        ContextReadArguments,
        "Read bounded task-owned context/schema/documents; no paths, SQL rows or siblings",
    ),
}
CAPABILITIES = {
    "sql": frozenset({"database_schema", "query_database", "read_context"}),
    "rag": frozenset({"search_documents", "read_context"}),
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
        durability=None,
    ):
        self.envelope, self.store = envelope, store
        self.database = database if envelope.task.worker == "sql" else None
        self.retrieval = retrieval if envelope.task.worker == "rag" else None
        approved = CAPABILITIES[envelope.task.worker]
        if not set(envelope.allowed_tools) <= approved:
            raise AgentFailure("TOOL_FORBIDDEN", "Child permissions exceed its worker capability")
        self.allowed = frozenset(envelope.allowed_tools)
        self.refs = []
        self.context_refs = []
        self.sql_attempts = 0
        self.cancel = cancellation or Cancellation()
        self.trace, self.timeout = trace, timeout
        self.max_sql_attempts, self.max_view_chars = max_sql_attempts, max_view_chars
        self.durability = durability
        if durability:
            durability.hydrate_tools(self)

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
        call_key, replayed = None, False
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
            if self.durability:
                call_key, cached = self.durability.begin_tool(
                    self.envelope, name, arguments, call_id
                )
                if cached is not None:
                    replayed = True
                    self.durability.adopt_payload(self, cached)
                    if cached.get("error"):
                        item = cached["error"]
                        raise AgentFailure(
                            item["code"], item["message"], retryable=item["retryable"]
                        )
                    return cached
            if name == "query_database" and self.sql_attempts >= self.max_sql_attempts:
                raise AgentFailure("SQL_ATTEMPTS_EXHAUSTED", "SQL attempt limit reached")
            if name == "query_database":
                # No await before reservation: simultaneous calls cannot both take the last slot.
                self.sql_attempts += 1
            payload = await self.cancel.wait_for(self._dispatch(name, args), self.timeout)
            if self.durability:
                self.durability.backend.hit("tool_artifact")
                self.durability.finish_tool(call_key, payload, (time.monotonic() - started) * 1000)
            return payload
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
            if self.durability and call_key and error and not replayed:
                self.durability.finish_tool(
                    call_key,
                    {"error": error.error.model_dump()},
                    (time.monotonic() - started) * 1000,
                    uncertain=error.error.code
                    in {"CANCELLED", "TOOL_TIMEOUT", "TOOL_ERROR", "TOOL_OUTPUT_INVALID"},
                )
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
            ref = self.store.put(
                Artifact(
                    run_id=self.envelope.run_id,
                    task_id=self.envelope.task.task_id,
                    plan_version=self.envelope.plan_version,
                    kind="schema",
                    source="host-bound/MCP",
                    values={"schema": value},
                )
            )
            self.context_refs.append(ref)
            return {"schema": value, "context_refs": [ref.model_dump()]}
        if name == "read_context":
            ref = next(
                (r for r in [*self.context_refs, *self.refs] if r.artifact_id == args.artifact_id),
                None,
            )
            if ref is None:
                raise AgentFailure(
                    "TOOL_FORBIDDEN", "Context reference was not delegated to this task"
                )
            item = self.store.get(ref)
            if (item.run_id, item.task_id, item.plan_version) != (
                self.envelope.run_id,
                self.envelope.task.task_id,
                self.envelope.plan_version,
            ) or item.kind not in {"context", "schema", "documents"}:
                raise AgentFailure("TOOL_FORBIDDEN", "Context reference belongs to another task")
            if item.kind == "documents":
                if self.envelope.task.worker != "rag":
                    raise AgentFailure(
                        "TOOL_FORBIDDEN", "Only its RAG worker can read document text"
                    )
                doc = next(
                    (d for d in item.documents.documents if d.document_id == args.document_id), None
                )
                if doc is None:
                    raise AgentFailure("INPUT_INVALID", "Choose an actual retrieved document ID")
                text = doc.text
            else:
                if args.document_id is not None:
                    raise AgentFailure(
                        "INPUT_INVALID", "Document selection does not apply to this artifact"
                    )
                text = item.values["messages" if item.kind == "context" else "schema"]
            if args.start > len(text):
                raise AgentFailure("INPUT_INVALID", "Page offset is beyond the artifact")
            size = min(args.max_chars, max(64, self.max_view_chars - 512))
            payload = {
                "context_refs": [ref.model_dump()],
                "text": text[args.start : args.start + size],
                "start": args.start,
                "untrusted_data": True,
            }
            while True:
                end = args.start + len(payload["text"])
                payload["next_offset"] = end if end < len(text) else None
                if len(json.dumps(payload, ensure_ascii=False)) <= self.max_view_chars:
                    return payload
                payload["text"] = payload["text"][: len(payload["text"]) // 2]
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
