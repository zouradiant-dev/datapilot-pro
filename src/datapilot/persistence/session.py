"""Official graph recovery plus trusted reauthorization and durable domain services."""

import asyncio
import json
import sys
from contextlib import suppress
from urllib.parse import urlsplit
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command
from pydantic import BaseModel
from sqlalchemy.engine import make_url

from datapilot import contracts as core_contracts
from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding, DatasetScope
from datapilot.harness.budget import RunBudget
from datapilot.ingestion.common import digest
from datapilot.llm.fake import FakeModelClient
from datapilot.orchestration import context_contracts, contracts
from datapilot.orchestration.context_contracts import ContextScope, MetricBinding, P3Reference
from datapilot.orchestration.coordinator import Coordinator
from datapilot.orchestration.model import FakeTransport, live_transport
from datapilot.orchestration.runtime import Cancellation, Trace
from datapilot.orchestration.tools import CAPABILITIES
from datapilot.persistence.backend import Backend, DurableArtifacts, DurableLedger, execute
from datapilot.persistence.journal import Journal
from datapilot.rag import contracts as rag_contracts
from datapilot.runtime.mcp_client import database_session, dataset_session, metric_session
from datapilot.semantics import contracts as semantic_contracts


def serializer():
    allowed = []
    for module in (core_contracts, contracts, context_contracts, semantic_contracts, rag_contracts):
        allowed.extend(
            value
            for value in vars(module).values()
            if isinstance(value, type)
            and issubclass(value, BaseModel)
            and value.__module__ == module.__name__
        )
    return JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=allowed)


def encode(value):
    return json.loads(json.dumps(value, default=lambda v: v.model_dump(mode="json")))


async def check_versions(settings, metadata, owner="local-user"):
    for value in metadata.values():
        if set(value) - {"scope", "metrics", "p3_verified_refs"}:
            raise AgentFailure(
                "RECOVERY_FORBIDDEN", "Context metadata cannot replace host authority"
            )
        scope = ContextScope.model_validate_json(json.dumps(encode(value.get("scope", {}))))
        if scope.owner != owner:
            raise AgentFailure("RECOVERY_FORBIDDEN", "Source scope belongs to another owner")
        if scope.sources:
            binding = DatasetScope(
                bindings=[
                    DatasetBinding(dataset_id=s.dataset_id, version=s.version)
                    for s in scope.sources
                ]
            )
            async with dataset_session(settings, binding) as tools:
                for source in scope.sources:
                    actual = await tools.schema(source.dataset_id)
                    if (actual.version, actual.source_sha256) != (
                        source.version,
                        source.source_sha256,
                    ):
                        raise AgentFailure("RECOVERY_VERSION", "Dataset source/version changed")
        for raw in value.get("metrics", []):
            metric = MetricBinding.model_validate_json(json.dumps(encode(raw)))
            c = metric.context
            if (c.dataset_id, c.dataset_version, c.source_sha256) not in {
                (s.dataset_id, s.version, s.source_sha256) for s in scope.sources
            }:
                raise AgentFailure("RECOVERY_VERSION", "Metric is outside pinned source scope")
            request = metric.request
            binding = DatasetScope(
                bindings=[
                    DatasetBinding(dataset_id=request.dataset_id, version=request.dataset_version)
                ]
            )
            async with metric_session(settings, binding) as tools:
                actual = await tools.context(request)
                if actual != metric.context:
                    raise AgentFailure(
                        "RECOVERY_VERSION", "Confirmed metric/semantic context changed"
                    )
        if value.get("p3_verified_refs"):
            # Existing metadata-only Registry channel; never a model tool or business SQL.
            from datapilot.db.management import management_url
            from datapilot.semantics.registry import RegistryStore

            registry = RegistryStore(management_url("registry"))
            try:
                for raw in value["p3_verified_refs"]:
                    pin = P3Reference.model_validate_json(json.dumps(encode(raw)))
                    actual = P3Reference.from_verified(
                        registry.get_evidence(pin.evidence_id),
                        registry.get_verification(pin.verification_id),
                    )
                    if actual != pin:
                        raise AgentFailure("RECOVERY_VERSION", "P3 verified reference changed")
            finally:
                registry.close()


class PersistentCancellation(Cancellation):
    def __init__(self, backend):
        super().__init__()
        self.backend = backend

    def cancel(self):
        self.backend.cancel()
        super().cancel()

    def check(self):
        if self.backend.cancelled():
            self.event.set()
        super().check()

    async def watch(self):
        while not self.event.is_set():
            if self.backend.cancelled():
                self.event.set()
                return
            await asyncio.sleep(0.2)


class DurableTrace(Trace):
    def __init__(self, backend, events):
        super().__init__(backend.run_id, events)
        self.backend = backend

    def emit(self, *args, **kwargs):
        super().emit(*args, **kwargs)
        self.backend.event(self.events[-1])


def fingerprint(settings, question, owner, schema, metadata, review):
    endpoint = urlsplit(settings.base_url)
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise ValueError("Model endpoint must not contain embedded credentials or query parameters")
    policy = settings.model_dump(
        exclude={
            "api_key",
            "reader_database_url",
            "upload_reader_database_url",
            "runtime_database_url",
            "rag_reader_database_url",
        }
    )
    reader = make_url(settings.reader_database_url.get_secret_value())
    return {
        "owner": owner,
        "question": question,
        "schema_hash": digest({"schema": schema}),
        "reader": {
            "host": reader.host,
            "port": reader.port,
            "database": reader.database,
            "role": reader.username,
        },
        "policy": policy,
        "capabilities": {k: sorted(v) for k, v in CAPABILITIES.items()},
        "context_metadata": encode(metadata),
        "review_required": review,
        "protocol": "P5B-1",
    }


async def run_durable(
    settings,
    run_id,
    question=None,
    *,
    owner="local-user",
    resume=False,
    approve=None,
    require_review=False,
    transport=None,
    context_metadata=None,
    interrupt_before=None,
    interrupt_after=None,
    fault=None,
    ttl_seconds=86400,
    rag_scope=None,
):
    if approve is not None and type(approve) is not bool:
        raise ValueError("Approval must be a trusted host boolean")
    if str(UUID(run_id)) != run_id or not owner or len(owner) > 64:
        raise ValueError("Use a canonical UUID and a trusted local owner identity")
    if not settings.runtime_database_url or not settings.reader_database_url:
        raise ValueError("Configure runtime and read-only business connections")
    metadata = context_metadata or {}
    backend = Backend(settings.runtime_database_url.get_secret_value(), run_id, owner, fault=fault)
    monitor = None
    try:
        with backend.lease():
            if resume:
                with backend.transaction() as conn:
                    stored = backend.authorize(conn)["manifest"]
                if question is not None and question != stored["question"]:
                    raise AgentFailure(
                        "RECOVERY_IDENTITY", "Requested goal differs from original run"
                    )
                question, require_review = stored["question"], stored["review_required"]
            elif not question or not question.strip() or len(question) > 8000:
                raise ValueError("A bounded question is required")
            await check_versions(settings, metadata, owner)
            from datapilot.rag.mcp import rag_session

            if rag_scope is not None and rag_scope.owner != owner:
                raise AgentFailure("RECOVERY_FORBIDDEN", "RAG scope belongs to another owner")
            async with (
                database_session(settings) as tools,
                rag_session(settings, rag_scope, goal=question) as retrieval,
            ):
                schema = (
                    await tools.schema()
                )  # Fresh trusted connection, role and schema validation.
                manifest = fingerprint(settings, question, owner, schema, metadata, require_review)
                if rag_scope is not None:
                    manifest["rag_completion_protocol"] = "rag-submit-v1"
                    from datapilot.orchestration.rag_completion import retrieval_goal

                    manifest["rag_completion_goal"] = retrieval_goal(question)
                    manifest["rag_scope"] = rag_scope.model_dump(mode="json")
                    manifest["rag_sources"] = retrieval.context_scope().model_dump(mode="json")
                limits = contracts.BudgetLimits(
                    calls=settings.max_model_calls, tokens=settings.max_total_tokens
                )
                if resume:
                    with backend.transaction() as conn:
                        backend.authorize(conn, manifest)
                else:
                    backend.register(manifest, limits, ttl_seconds)
                ledger = DurableLedger(backend, limits)
                store = DurableArtifacts(backend)
                store.export()  # Fail on missing/corrupt content before resuming any model work.
                journal = Journal(backend, ledger, store)
                journal.require_review = require_review
                if resume:
                    journal.recover()
                cancel = PersistentCancellation(backend)
                if backend.cancelled():
                    raise AgentFailure("CANCELLED", "Cancelled runs cannot resume execution")
                monitor = asyncio.create_task(cancel.watch())
                transport = transport or (
                    FakeTransport(
                        FakeModelClient(
                            settings, RunBudget(settings.max_model_calls, settings.max_total_tokens)
                        )
                    )
                    if settings.llm_mode == "fake"
                    else live_transport(settings)
                )
                url = make_url(settings.runtime_database_url.get_secret_value()).set(
                    drivername="postgresql"
                )
                async with AsyncPostgresSaver.from_conn_string(
                    url.render_as_string(hide_password=False), serde=serializer()
                ) as saver:
                    # No setup here: missing deployment is a hard error, never hidden DDL.
                    engine = Coordinator(
                        settings,
                        transport,
                        database=tools,
                        retrieval=retrieval,
                        run_id=run_id,
                        checkpointer=saver,
                        durability=journal,
                        cancellation=cancel,
                        context_metadata=metadata,
                        interrupt_before=interrupt_before,
                        interrupt_after=interrupt_after,
                    )
                    with backend.transaction() as conn:
                        events = [
                            r[0]
                            for r in execute(
                                conn,
                                "SELECT payload FROM execution.events "
                                "WHERE run_id=:run ORDER BY event_id",
                                run=run_id,
                            ).all()
                        ]
                    engine.events[:] = events
                    engine.trace = DurableTrace(backend, engine.events)
                    engine.gateway.trace = engine.trace
                    engine.question = question
                    config = {
                        "configurable": {"thread_id": run_id},
                        "recursion_limit": settings.max_steps * 3 + 10,
                        "max_concurrency": settings.max_parallel_workers,
                    }
                    state = await engine.graph.aget_state(config)
                    if resume and not state.values:
                        raise AgentFailure("RECOVERY_MISSING", "Official checkpoint is missing")
                    if state.values:
                        if not resume:
                            raise AgentFailure(
                                "RECOVERY_EXISTS", "Use resume for an existing thread"
                            )
                        if (
                            state.values.get("run_id") != run_id
                            or state.values.get("question") != question
                        ):
                            raise AgentFailure(
                                "RECOVERY_IDENTITY", "Checkpoint belongs to another goal"
                            )
                        engine.plans = {
                            int(k): v for k, v in state.values.get("plan_history", {}).items()
                        }
                        engine.reused = dict(state.values.get("reuse_origins", {}))
                        for task_result in state.values.get("results", {}).values():
                            if task_result.run_id != run_id:
                                raise AgentFailure(
                                    "RECOVERY_IDENTITY", "Checkpoint task belongs to another run"
                                )
                            for ref in task_result.evidence_refs:
                                store.get(ref)
                            if task_result.status == "succeeded":
                                plan = engine.plans.get(task_result.plan_version)
                                task = (
                                    next(
                                        (t for t in plan.tasks if t.task_id == task_result.task_id),
                                        None,
                                    )
                                    if plan
                                    else None
                                )
                                if (
                                    task is None
                                    or engine.verify(
                                        {**state.values, "plan_version": task_result.plan_version},
                                        task,
                                        task_result,
                                    ).status
                                    != "passed"
                                ):
                                    raise AgentFailure(
                                        "RECOVERY_IDENTITY", "Restored task failed revalidation"
                                    )
                        backend.event({"node": "recovery", "status": "resumed", "run_id": run_id})
                    initial = {
                        "run_id": run_id,
                        "question": question,
                        "status": "pending",
                        "results": {},
                        "verifications": {},
                        "steps": 0,
                        "replans": 0,
                        "error": None,
                        "answer": "",
                    }
                    if resume and not state.next:
                        result = dict(state.values)
                    else:
                        value = Command(resume=approve) if approve is not None else None
                        result = await engine.graph.ainvoke(
                            value if resume else initial, config=config, durability="sync"
                        )
                    current = await engine.graph.aget_state(config)
                    if current.next:
                        result = {
                            **result,
                            "status": "awaiting_review" if current.interrupts else "paused",
                        }
                    result.pop("__interrupt__", None)
                    result["interrupts"] = [
                        {"id": item.id, "value": item.value} for item in current.interrupts
                    ]
                    backend.event(
                        {
                            "node": "recovery",
                            "status": result["status"],
                            "run_id": run_id,
                            "usage": ledger.snapshot().model_dump(),
                        }
                    )
                    return {
                        **result,
                        "mode": settings.llm_mode,
                        "run_id": run_id,
                        "usage": ledger.snapshot().model_dump(),
                        "trace": engine.events,
                        "cost": {
                            "amount": None,
                            "currency": None,
                            "status": "invoice_not_available",
                        },
                    }
    finally:
        if monitor:
            monitor.cancel()
            with suppress(asyncio.CancelledError):
                await monitor
        backend.close()


def run_async(operation):
    # psycopg async explicitly does not support Windows ProactorEventLoop.
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(operation)
    return asyncio.run(operation)
