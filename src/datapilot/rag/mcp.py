"""An isolated read-only RAG profile in the existing MCP server/client transport."""

import json
import threading
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import SearchResult
from datapilot.rag.contracts import IndexManifest, RagScope
from datapilot.rag.models import LocalEmbedding, specification
from datapilot.rag.storage import Repository, verify_result
from datapilot.runtime.mcp_client import MCPDatabaseTools, _connection, server_environment


def create_rag_server(settings, scope: RagScope):
    repository = Repository(
        settings.rag_reader_database_url.get_secret_value(),
        scope,
        timeout=settings.query_timeout_seconds,
    )
    server = FastMCP("datapilot-rag-readonly")
    lock, loaded = threading.Lock(), []

    @server.tool()
    def health() -> dict:
        return {"protocol": "ready", "profile": "rag-readonly"}

    @server.tool()
    def get_rag_manifest() -> dict:
        """Host preflight: only explicit immutable indexes, no source bodies or vectors."""
        try:
            return {
                "manifests": {
                    k: v.model_dump(mode="json") for k, v in repository.manifests().items()
                },
                "error": None,
            }
        except AgentFailure as exc:
            return {"manifests": None, "error": exc.error.model_dump()}

    @server.tool()
    def search_documents(query: str, top_k: int = 3) -> dict:
        """Retrieve authorized immutable fragments. query/top_k cannot authorize any source."""
        try:
            if scope.corpora:
                with lock:
                    if not loaded:
                        loaded.append(LocalEmbedding())
            result = repository.search(query, top_k, loaded[0] if loaded else None)
            return {"result": result.model_dump(mode="json"), "error": None}
        except AgentFailure as exc:
            return {"result": None, "error": exc.error.model_dump()}

    return server


class MCPRetrievalTools(MCPDatabaseTools):
    max_search_attempts = 2
    allowed = frozenset({"health", "get_rag_manifest", "search_documents"})

    def __init__(self, session, timeout, *, scope):
        super().__init__(session, timeout)
        self.scope = RagScope.model_validate_json(scope.model_dump_json())
        self.manifests = {}

    async def preflight(self):
        payload = await self.call("get_rag_manifest", {})
        try:
            manifests = {
                k: IndexManifest.model_validate_json(json.dumps(v))
                for k, v in payload["manifests"].items()
            }
            if set(manifests) != {p.corpus_id for p in self.scope.corpora}:
                raise ValueError("Incomplete corpus scope")
            for pin in self.scope.corpora:
                m = manifests[pin.corpus_id]
                if (
                    digest(m) != pin.index_version
                    or m.target.corpus_id != pin.corpus_id
                    or not self.scope.permits(m.target)
                    or m.model != specification()
                    or set(pin.document_ids) != {s.document_id for s in m.sources}
                ):
                    raise ValueError("Index/source/model/scope differs")
            self.manifests = manifests
        except (ValueError, KeyError, TypeError):
            raise AgentFailure(
                "DOCUMENT_NOT_AUTHORIZED", "Fresh RAG manifest failed host validation"
            ) from None

    def authority_context(self):
        return {
            "rag_scope_sha256": digest(self.scope),
            "index_versions": {p.corpus_id: p.index_version for p in self.scope.corpora},
            "retrieved_text_is_untrusted": True,
        }

    def context_scope(self):
        return self.source_scope.model_copy(deep=True)

    def validate_result(self, result):
        verify_result(result, self.scope, self.manifests)

    async def search(self, query, top_k):
        # Closed argument contract, even for host Python callers; model has no scope parameter.
        from datapilot.orchestration.tools import SearchArguments

        try:
            args = SearchArguments(query=query, top_k=top_k)
            value = await self.call("search_documents", args.model_dump())
            result = SearchResult.model_validate_json(json.dumps(value["result"]))
            if result.requested_top_k != top_k:
                raise ValueError("top_k differs")
            self.validate_result(result)
            return result
        except (ValueError, KeyError, TypeError):
            raise AgentFailure(
                "TOOL_OUTPUT_INVALID", "Retrieved source contract failed validation"
            ) from None


@asynccontextmanager
async def rag_session(settings, scope: RagScope | None):
    if scope is None:
        yield None
        return
    if not settings.rag_reader_database_url:
        raise AgentFailure("DATABASE_NOT_CONFIGURED", "Configure the isolated RAG reader")
    scope = RagScope.model_validate_json(scope.model_dump_json())
    from datapilot.orchestration.context_contracts import ContextScope, SourcePin

    sources = []
    if scope.datasets.bindings:
        from datapilot.runtime.mcp_client import dataset_session

        async with dataset_session(settings, scope.datasets) as dataset_tools:
            for binding in scope.datasets.bindings:
                schema = await dataset_tools.schema(binding.dataset_id)
                sources.append(
                    SourcePin(
                        dataset_id=schema.dataset_id,
                        version=schema.version,
                        source_sha256=schema.source_sha256,
                    )
                )
    env = server_environment(settings)
    env["DATAPILOT_RAG_READER_DATABASE_URL"] = settings.rag_reader_database_url.get_secret_value()
    env["DATAPILOT_RAG_SCOPE"] = scope.model_dump_json()
    from functools import partial

    async with _connection(settings, env, partial(MCPRetrievalTools, scope=scope)) as tools:
        await tools.preflight()
        tools.source_scope = ContextScope(
            owner=scope.owner, profile="dataset" if sources else "saas", sources=tuple(sources)
        )
        yield tools
