"""The existing Qwen stdio session's bounded model cache, not a resident service."""

import asyncio
import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path

import anyio
import sqlalchemy as sa

from datapilot.contracts import AgentFailure

STARTUP_SECONDS = 60
RESOURCE_LOCK = (7512, 6001)  # One Qwen per authorized deployment database, all profiles.


def available_ram():
    if sys.platform == "win32":

        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong)
                for name in (
                    "total",
                    "available",
                    "page",
                    "available_page",
                    "virtual",
                    "available_virtual",
                    "extended",
                )
            ]

        value = Memory()
        value.length = ctypes.sizeof(value)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            raise OSError("Memory status unavailable")
        return value.available
    fields = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    free = int(fields["MemAvailable"].split()[0]) * 1024
    group = Path("/sys/fs/cgroup")
    if (group / "memory.max").exists():
        limit = (group / "memory.max").read_text().strip()
        if limit != "max":
            free = min(free, max(0, int(limit) - int((group / "memory.current").read_text())))
    return free


class ModelCache:
    def __init__(self, repository, profile, factory, *, exit_process=os._exit):
        self.repository, self.profile, self.factory = repository, profile, factory
        self.exit_process = exit_process
        self.model = self.loading = self.heartbeat = self.lease = None
        self.state, self.error, self.active, self.loads = "not_started", None, False, 0
        self.events, self.started = [], time.monotonic()
        self.guard_mutex = threading.Lock()
        try:
            from datapilot.rag.qwen_runtime import verify

            if any(
                k in os.environ
                for k in (
                    "DATAPILOT_API_KEY",
                    "OPENAI_API_KEY",
                    "DEEPSEEK_API_KEY",
                    "DATAPILOT_ADMIN_DATABASE_URL",
                    "DATAPILOT_REGISTRY_DATABASE_URL",
                    "DATAPILOT_RUNTIME_DATABASE_URL",
                    "DATAPILOT_RAG_INGEST_DATABASE_URL",
                )
            ):
                raise AgentFailure("EMBEDDING_VERSION", "Unsafe Qwen MCP credential environment")
            self.binding = verify()
            self.binding["environment_isolated"] = True
        except AgentFailure as exc:
            self.binding, self.state, self.error = None, "failed", exc.error
        self.mark("process_protocol_start")

    def mark(self, phase, **fields):
        event = {
            "phase": phase,
            "elapsed_ms": (time.monotonic() - self.started) * 1000,
            "pid": os.getpid(),
            **fields,
        }
        self.events.append(event)
        self.events[:] = self.events[-32:]
        print(json.dumps({"component": "qwen_lifecycle", **event}), file=sys.stderr, flush=True)

    def status(self):
        from datapilot.ingestion.common import digest
        from datapilot.rag.qwen import policy, specification

        return {
            "profile": self.profile,
            "model_sha256": digest(specification(self.profile)),
            "policy_sha256": digest(policy(self.profile)),
            "state": self.state,
            "loads": self.loads,
            "active": self.active,
            "runtime": self.binding,
            "events": list(self.events),
            "error": self.error.model_dump() if self.error else None,
        }

    def acquire(self):
        try:
            self.lease = self.repository.engine.connect()
            self.lease.exec_driver_sql("SET SESSION statement_timeout='1000ms'")
            granted = self.lease.execute(
                sa.text("SELECT pg_try_advisory_lock(:a,:b)"),
                {"a": RESOURCE_LOCK[0], "b": RESOURCE_LOCK[1]},
            ).scalar_one()
            self.lease.commit()
            if not granted:
                raise AgentFailure("EMBEDDING_BUSY", "Another Qwen session owns model capacity")
            free = available_ram()
            floor = (4 if self.profile == "qwen3-cpu-v1" else 3) * 1024**3
            self.mark("resource_check", available_ram=free, required_ram=floor)
            if free < floor:
                raise AgentFailure("EMBEDDING_RESOURCE_LIMIT", "Insufficient RAM for fixed profile")
            self.mark("resource_acquired")
        except sa.exc.SQLAlchemyError:
            raise AgentFailure("EMBEDDING_NOT_READY", "Model capacity guard unavailable") from None

    def check_lease(self):
        with self.guard_mutex:
            self.lease.exec_driver_sql("SELECT 1")
            self.lease.commit()

    async def monitor(self):
        while True:
            await asyncio.sleep(0.5)
            try:
                await anyio.to_thread.run_sync(self.check_lease, abandon_on_cancel=True)
            except Exception:
                self.stop("resource_guard_lost", 117)

    def stop(self, reason, code):
        self.state = "stopping"
        self.mark(reason, exit_code=code)
        # This process has ONLY an isolated reader/model. No Journal/Registry writer.
        # Exiting releases blocked native threads, GPU allocations and PG session locks.
        self.exit_process(code)

    async def prepare(self):
        if self.state != "not_started":
            return self.status()
        self.state = "loading"
        try:
            self.repository.manifests()  # Scope/source authorization precedes resource/model work.
            self.acquire()
        except AgentFailure as exc:
            self.state, self.error = "failed", exc.error
            return self.status()
        self.heartbeat = asyncio.create_task(self.monitor())
        self.loading = asyncio.create_task(self.load())
        return self.status()

    async def load(self):
        try:
            self.loads += 1
            self.mark("model_loading")
            self.model = await anyio.to_thread.run_sync(
                lambda: self.factory(self.profile, observer=self.mark), abandon_on_cancel=True
            )
            from datapilot.rag.models import validate_vectors
            from datapilot.rag.qwen import specification

            if self.model.spec != specification(self.profile):
                raise AgentFailure("EMBEDDING_VERSION", "Initialized model differs from profile")
            self.mark("warmup_started")
            vectors, usage = await anyio.to_thread.run_sync(
                lambda: self.model.encode(["Public SaaS operational policy."], query=True),
                abandon_on_cancel=True,
            )
            validate_vectors(vectors, 1, self.model.spec.dimensions)
            if usage.mode != "local_torch":
                raise AgentFailure("EMBEDDING_INVALID", "Expected actual Qwen warmup provenance")
            self.mark("warmup_complete", usage=usage.model_dump())
            self.state = "ready"
            self.mark("model_ready")
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, AgentFailure)
                else AgentFailure("EMBEDDING_NOT_READY", "Explicit model startup failed")
            )
            self.state, self.error = "failed", error.error
            self.mark("model_failed", code=self.error.code)

    async def search(self, query, top_k):
        if self.state != "ready":
            raise AgentFailure("EMBEDDING_NOT_READY", "Complete explicit model readiness first")
        if self.active:
            raise AgentFailure("EMBEDDING_BUSY", "One bounded search per Qwen session")
        self.active = True
        try:
            self.mark("search_started")
            result = await anyio.to_thread.run_sync(
                lambda: self.repository.search(query, top_k, self.model), abandon_on_cancel=True
            )
            self.mark("search_complete")
            return result
        except asyncio.CancelledError:
            self.stop("inflight_cancelled", 116)
            raise
        finally:
            self.active = False

    async def close(self):
        self.mark("shutdown_started")
        # The OS-verified parent owns the hard 2s cleanup deadline, including GIL stalls.
        if self.active or (self.loading is not None and not self.loading.done()):
            self.stop("shutdown_inflight", 116)
        if self.heartbeat:
            self.heartbeat.cancel()
        # The OS closes read-only pooled connections, native threads and GPU handles.
        # No blocking SDK/thread-pool finalizer can extend this process's lifetime.
        self.stop("shutdown_complete", 0)
