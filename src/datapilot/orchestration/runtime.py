"""Trusted run services: cancellation, bounded provenance and redacted trace events."""

import asyncio
import hashlib
from collections.abc import Awaitable

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact, EvidenceRef, ExecutionError, TraceEvent


def execution_error(error: AgentFailure) -> ExecutionError:
    code = error.error.code
    category = (
        "budget"
        if code.startswith("BUDGET")
        else "cancelled"
        if code == "CANCELLED"
        else "permission"
        if code in {"TOOL_FORBIDDEN", "SQL_UNSAFE", "DATASET_NOT_AUTHORIZED", "ROLE_UNSAFE"}
        else "plan"
        if code.startswith("PLAN") or code == "CAPABILITY_UNAVAILABLE"
        else "model"
        if code.startswith("MODEL")
        else "verification"
        if code.startswith(("VERIFICATION", "EVIDENCE"))
        else "input"
        if code in {"INPUT_INVALID", "CONTEXT_LIMIT"}
        else "tool"
    )
    retryable = error.error.retryable and category not in {
        "permission",
        "budget",
        "cancelled",
        "input",
        "verification",
        "plan",
    }
    return ExecutionError(
        code=code,
        message=error.error.message[:256],
        retryable=retryable,
        category=category,
    )


class Cancellation:
    def __init__(self):
        self.event = asyncio.Event()

    def cancel(self):
        self.event.set()

    def check(self):
        if self.event.is_set():
            raise AgentFailure("CANCELLED", "Parent run was cancelled")

    async def wait_for(self, operation: Awaitable, timeout: float):
        job = asyncio.ensure_future(operation)
        stopped = asyncio.create_task(self.event.wait())
        try:
            self.check()
            done, _ = await asyncio.wait(
                {job, stopped}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            self.check()
            if job not in done:
                raise AgentFailure(
                    "TOOL_TIMEOUT", "Bounded async operation timed out", retryable=True
                )
            return await job
        finally:
            for task in (job, stopped):
                if not task.done():
                    task.cancel()
            await asyncio.gather(job, stopped, return_exceptions=True)


class ArtifactStore:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._items = {}
        self._bytes = 0

    def put(self, artifact: Artifact) -> EvidenceRef:
        artifact = Artifact.model_validate_json(artifact.model_dump_json())
        if artifact.run_id != self.run_id:
            raise AgentFailure("EVIDENCE_INVALID", "Artifact belongs to another run")
        sha = digest(artifact)
        if sha not in self._items:
            size = len(artifact.model_dump_json().encode())
            if self._bytes + size > 16 * 1024**2 or len(self._items) >= 96:
                raise AgentFailure("EVIDENCE_LIMIT", "Run artifact quota reached")
            self._items[sha] = artifact
            self._bytes += size
        return EvidenceRef(artifact_id=sha, kind=artifact.kind, sha256=sha)

    def get(self, ref: EvidenceRef) -> Artifact:
        item = self._items.get(ref.artifact_id)
        if item is None or digest(item) != ref.sha256 or item.kind != ref.kind:
            raise AgentFailure("EVIDENCE_INVALID", "Missing or inconsistent evidence reference")
        return item.model_copy(deep=True)

    def export(self):
        """Explicit local debug bundle; raw source values are never added to the trace itself."""
        return {key: value.model_copy(deep=True) for key, value in self._items.items()}


class Trace:
    def __init__(self, run_id: str, events: list[dict]):
        self.run_id, self.events = run_id, events

    def emit(
        self,
        node: str,
        status: str,
        *,
        version=1,
        task_id=None,
        elapsed_ms=0,
        error_code=None,
        tool_name=None,
        tool_call_id=None,
        refs=(),
        usage=None,
    ):
        if len(self.events) >= 1024:
            raise AgentFailure("TRACE_LIMIT", "Run trace quota reached")
        event = TraceEvent(
            sequence=len(self.events) + 1,
            run_id=self.run_id,
            plan_version=version,
            task_id=task_id,
            node=node,
            status=status,
            elapsed_ms=round(elapsed_ms, 3),
            error_code=error_code,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            evidence_ids=[r.artifact_id for r in refs],
            usage=usage,
        )
        self.events.append(event.model_dump())


def text_hash(text: str):
    return hashlib.sha256(text.encode()).hexdigest()
