"""An isolated read-only RAG profile in the existing MCP server/client transport."""

import asyncio
import hashlib
import json
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import SearchResult
from datapilot.orchestration.rag_completion import RELEVANCE_POLICY, RELEVANCE_THRESHOLD
from datapilot.rag.contracts import IndexManifest, RagScope
from datapilot.rag.models import create_embedding
from datapilot.rag.storage import Repository, validate_manifest_profile, verify_result
from datapilot.runtime.mcp_client import MCPDatabaseTools, _connection, server_environment

QWEN_SESSION_SLOTS = threading.BoundedSemaphore(2)


def create_rag_server(settings, scope: RagScope, *, goal=None):
    if goal is not None and (not isinstance(goal, str) or not 1 <= len(goal) <= 8000):
        raise ValueError("Use a bounded host retrieval goal")
    repository = Repository(
        settings.rag_reader_database_url.get_secret_value(),
        scope,
        timeout=settings.query_timeout_seconds,
        goal=goal,
    )
    cache = None
    if scope.embedding_profile:
        from datapilot.rag.lifecycle import ModelCache

        cache = ModelCache(repository, scope.embedding_profile, create_embedding)

    @asynccontextmanager
    async def lifespan(_):
        try:
            yield {}
        finally:
            if cache is not None:
                await cache.close()
            repository.close()

    server = FastMCP("datapilot-rag-readonly", lifespan=lifespan)
    lock, loaded = threading.Lock(), []

    @server.tool()
    def health() -> dict:
        value = {"protocol": "ready", "profile": "rag-readonly"}
        if cache is not None:
            value["embedding"] = cache.status()
        return value

    if cache is not None:

        @server.tool()
        async def prepare_embedding() -> dict:
            """Trusted host startup only; no source/model/permission arguments."""
            return {"embedding": await cache.prepare(), "error": None}

    @server.tool()
    def get_rag_manifest() -> dict:
        """Host preflight: only explicit immutable indexes, no source bodies or vectors."""
        try:
            value = {
                "manifests": {
                    k: v.model_dump(mode="json") for k, v in repository.manifests().items()
                },
                "error": None,
            }
            if cache is not None:
                value["runtime"] = cache.binding
                value["pid"] = os.getpid()
                value["session_token"] = os.environ.get("DATAPILOT_MCP_SESSION_TOKEN")
            return value
        except AgentFailure as exc:
            return {"manifests": None, "error": exc.error.model_dump()}

    def search_legacy(query: str, top_k: int = 3) -> dict:
        """Retrieve authorized immutable fragments. query/top_k cannot authorize any source."""
        try:
            # One session shares the cached goal vector. Do not expose an in-flight
            # initialization as missing relevance metadata to another worker.
            with lock:
                if scope.corpora:
                    if not loaded:
                        # Validate the host pin before allocating a model or reading chunks.
                        repository.manifests()
                        loaded.append(create_embedding(scope.embedding_profile))
                result = repository.search(query, top_k, loaded[0] if loaded else None)
            return {"result": result.model_dump(mode="json"), "error": None}
        except AgentFailure as exc:
            return {"result": None, "error": exc.error.model_dump()}

    async def search_qwen(query: str, top_k: int = 3) -> dict:
        """Retrieve authorized immutable fragments after explicit host readiness."""
        try:
            result = (
                await cache.search(query, top_k)
                if any(p.document_ids for p in scope.corpora)
                else repository.search(query, top_k, None)
            )
            return {"result": result.model_dump(mode="json"), "error": None}
        except AgentFailure as exc:
            return {"result": None, "error": exc.error.model_dump()}

    # Preserve the BGE SDK's original synchronous-tool thread offload.
    server.add_tool(search_qwen if cache is not None else search_legacy, name="search_documents")
    return server


class MCPRetrievalTools(MCPDatabaseTools):
    completion_protocol = "rag-submit-v1"
    max_search_attempts = 2
    allowed = frozenset({"health", "get_rag_manifest", "search_documents"})

    def __init__(self, session, timeout, *, scope, goal=None, session_token=None):
        super().__init__(session, timeout)
        self.scope = RagScope.model_validate_json(scope.model_dump_json())
        self.manifests = {}
        self.goal_sha256 = hashlib.sha256(goal.encode()).hexdigest() if goal else None
        self.session_token, self.startup_trace = session_token, None
        self.relevance_policy, self.goal_threshold = RELEVANCE_POLICY, RELEVANCE_THRESHOLD
        if scope.embedding_profile:
            self.allowed = self.allowed | {"prepare_embedding"}
            from datapilot.rag.qwen import policy

            p = policy(scope.embedding_profile)
            self.relevance_policy, self.goal_threshold = p["goal_policy"], p["goal_threshold"]

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
                    or set(pin.document_ids) != {s.document_id for s in m.sources}
                ):
                    raise ValueError("Index/source/model/scope differs")
                validate_manifest_profile(m, self.scope)
            self.manifests = manifests
            if self.scope.embedding_profile:
                from datapilot.rag.qwen_runtime import expected, source_hash
                from datapilot.runtime.owned_process import OwnedProcess

                binding, sha = expected()
                runtime = payload.get("runtime")
                if (
                    not self.session_token
                    or payload.get("session_token") != self.session_token
                    or not runtime
                    or runtime["manifest_sha256"] != sha
                    or runtime["source_sha256"] != source_hash()
                    or runtime["python"] != binding["python"]
                    or runtime["lock_sha256"] != binding["lock_sha256"]
                    or runtime.get("environment_isolated") is not True
                ):
                    raise AgentFailure("EMBEDDING_VERSION", "MCP runtime binding differs")
                if self.process_owner is None:
                    self.process_owner = OwnedProcess(
                        payload["pid"],
                        self.spawn_wall_started,
                        {binding["executable_sha256"], binding["base_executable_sha256"]},
                    )
        except (ValueError, KeyError, TypeError):
            raise AgentFailure(
                "DOCUMENT_NOT_AUTHORIZED", "Fresh RAG manifest failed host validation"
            ) from None

    async def prepare(self):
        from datapilot.rag.lifecycle import STARTUP_SECONDS

        begin = time.monotonic()
        try:
            async with asyncio.timeout(STARTUP_SECONDS):
                state = (await self.call("prepare_embedding", {}))["embedding"]
                polls = 0
                while state["state"] != "ready":
                    if state["state"] == "failed":
                        from datapilot.contracts import AgentError

                        error = AgentError.model_validate(state["error"])
                        raise AgentFailure(error.code, error.message)
                    await asyncio.sleep(0.25)
                    state = (await self.call("health", {}))["embedding"]
                    polls += 1
                    if polls > 256:
                        raise AgentFailure(
                            "EMBEDDING_STARTUP_TIMEOUT", "Readiness poll quota exceeded"
                        )
                from datapilot.rag.models import specification
                from datapilot.rag.storage import policy_hash

                if (
                    state["profile"] != self.scope.embedding_profile
                    or state["model_sha256"] != digest(specification(self.scope.embedding_profile))
                    or state["policy_sha256"] != policy_hash(self.scope)
                    or state["loads"] != 1
                ):
                    raise AgentFailure(
                        "EMBEDDING_VERSION", "Ready model does not match host profile"
                    )
                self.startup_trace = {
                    "startup_seconds": time.monotonic() - begin,
                    "transport_seconds": self.transport_seconds,
                    "polls": polls,
                    "embedding": state,
                }
        except asyncio.CancelledError:
            self.process_owner.arm()
            raise
        except TimeoutError:
            self.process_owner.arm()
            raise AgentFailure(
                "EMBEDDING_STARTUP_TIMEOUT", "Explicit model startup timed out"
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
        if any(d.citation.goal_sha256 != self.goal_sha256 for d in result.documents):
            raise AgentFailure("DOCUMENT_CORRUPT", "Retrieval goal binding changed")

    def qualifying_documents(self, documents, goal):
        if (
            goal["question_sha256"] != self.goal_sha256
            or goal["relevance_policy"] != self.relevance_policy
            or goal["minimum_goal_score"] != self.goal_threshold
        ):
            return []
        return [
            d
            for d in documents
            if d.citation
            and d.citation.goal_sha256 == self.goal_sha256
            and d.citation.goal_score is not None
            and d.citation.goal_score >= max(self.goal_threshold, self.scope.min_score)
        ]

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
async def rag_session(settings, scope: RagScope | None, *, goal=None):
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
    if goal:
        env["DATAPILOT_RAG_GOAL"] = goal
    from functools import partial

    executable = None
    session_token = None
    if scope.embedding_profile:
        from datapilot.rag.qwen import interpreter

        executable = interpreter()
        session_token = secrets.token_hex(16)
        env["DATAPILOT_MCP_SESSION_TOKEN"] = session_token
        # Fixed source tree, not caller-controlled arbitrary modules from PYTHONPATH.
        from datapilot.rag.models import ROOT

        env["PYTHONPATH"] = str(ROOT / "src")
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    connection_options = {"executable": executable, "isolated": True} if executable else {}
    acquired = scope.embedding_profile is not None
    if acquired and not QWEN_SESSION_SLOTS.acquire(blocking=False):
        raise AgentFailure("EMBEDDING_BUSY", "Qwen process admission is full; no queued retry")
    try:
        async with _connection(
            settings,
            env,
            partial(MCPRetrievalTools, scope=scope, goal=goal, session_token=session_token),
            **connection_options,
        ) as tools:
            await tools.preflight()
            if scope.embedding_profile and any(p.document_ids for p in scope.corpora):
                await tools.prepare()
            tools.source_scope = ContextScope(
                owner=scope.owner, profile="dataset" if sources else "saas", sources=tuple(sources)
            )
            yield tools
    finally:
        if acquired:
            QWEN_SESSION_SLOTS.release()
