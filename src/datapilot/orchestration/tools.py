"""Fixed capability registry; no shell, filesystem, management or model-created tools."""

import json
from dataclasses import dataclass
from typing import Protocol

from pydantic import Field

from datapilot.contracts import AgentFailure, Contract, QueryResult
from datapilot.orchestration.contracts import Artifact, SearchResult
from datapilot.orchestration.runtime import text_hash


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
    def __init__(self, envelope, store, *, database=None, retrieval=None):
        self.envelope, self.store = envelope, store
        self.database = database if envelope.task.worker == "sql" else None
        self.retrieval = retrieval if envelope.task.worker == "rag" else None
        approved = CAPABILITIES[envelope.task.worker]
        if not set(envelope.allowed_tools) <= approved:
            raise AgentFailure("TOOL_FORBIDDEN", "Child permissions exceed its worker capability")
        self.allowed = frozenset(envelope.allowed_tools)
        self.refs = []
        self.sql_attempts = 0

    def schemas(self):
        return [DEFINITIONS[name].schema() for name in sorted(self.allowed)]

    async def invoke(self, name, arguments):
        if name not in self.allowed or name not in DEFINITIONS:
            raise AgentFailure("TOOL_FORBIDDEN", "Tool is outside delegated capability")
        # Strict input validation occurs before dispatch, never replace malformed JSON with {}.
        if len(json.dumps(arguments, ensure_ascii=False)) > 13000:
            raise AgentFailure("INPUT_INVALID", "Tool arguments exceed their limit")
        try:
            args = DEFINITIONS[name].arguments.model_validate(arguments)
        except ValueError as exc:
            raise AgentFailure("INPUT_INVALID", "Tool arguments failed their contract") from exc
        if name == "database_schema":
            value = await self.database.schema()
            if not isinstance(value, str) or not 1 <= len(value) <= 12000:
                raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid schema response")
            return {"schema": value}
        if name == "query_database":
            self.sql_attempts += 1
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
            payload = {
                "row_count": value.row_count,
                "columns": value.columns,
                "truncated": value.truncated,
            }
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
            # Only bounded excerpts are fed back to this RAG worker, never to sibling SQL context.
            payload = {
                "document_count": len(value.documents),
                "fixture": value.fixture,
                "documents": [d.model_dump() for d in value.documents],
            }
        ref = self.store.put(artifact)
        self.refs.append(ref)
        return {**payload, "artifact_refs": [ref.model_dump()]}
