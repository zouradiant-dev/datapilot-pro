"""Per-worker disposable views. Full transcripts and authority never become model summaries."""

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, messages_to_dict

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.context_contracts import (
    AuthoritySnapshot,
    CompressionStats,
    ContextSummary,
)
from datapilot.orchestration.contracts import Artifact, ContextUsage, EvidenceRef

if TYPE_CHECKING:
    from datapilot.orchestration.model import Gateway
    from datapilot.orchestration.tools import ToolRegistry


def measure_context(messages, tools, output_tokens):
    message_text = json.dumps(messages_to_dict(messages), ensure_ascii=False)
    schema_text = json.dumps(tools, ensure_ascii=False)
    text = json.dumps({"messages": messages_to_dict(messages), "tools": tools}, ensure_ascii=False)
    usage = ContextUsage(
        messages=len(messages),
        message_chars=len(message_text),
        tool_schema_chars=len(schema_text),
        input_bytes=len(text.encode("utf-8")),
        estimated_input_tokens=len(text.encode("utf-8")) + 128,
        output_reserved_tokens=output_tokens,
        tool_result_chars=sum(len(m.content) for m in messages if m.type == "tool"),
    )
    return text, usage


def tool_view(artifact, ref, max_chars):
    """Called ONLY after full validated artifact storage. No authoritative content is rewritten."""
    payload = {"artifact_refs": [ref.model_dump()], "model_view": "L0"}
    if artifact.query:
        q = artifact.query
        payload.update(
            row_count=q.row_count,
            columns=q.columns[:16],
            columns_omitted=max(0, len(q.columns) - 16),
            truncated=q.truncated,
        )
    elif artifact.documents:
        result = artifact.documents
        payload.update(
            document_count=len(result.documents),
            fixture=result.fixture,
            documents=[
                {
                    "document_id": d.document_id,
                    "source": d.source,
                    "version": d.version,
                    "sha256": d.sha256,
                    "text": d.text[:256],
                    "text_omitted_chars": max(0, len(d.text) - 256),
                }
                for d in result.documents
            ],
        )
    # Even adversarial identifiers cannot make a model view unbounded. Complete metadata
    # remains in the artifact; this is not a change to source evidence or authorization.
    if len(json.dumps(payload, ensure_ascii=False)) > max_chars:
        payload.pop("documents", None)
        payload.pop("columns", None)
        payload["details_omitted"] = True
    return payload


def closed_batches(messages: list[BaseMessage]) -> list[tuple[int, int]]:
    """Provider protocol validator. Never split, reorder or silently discard tool feedback."""
    batches, seen = [], set()
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.type == "tool":
            raise AgentFailure("CONTEXT_LIMIT", "Orphan tool result cannot be safely compressed")
        calls = [*message.tool_calls, *message.invalid_tool_calls] if message.type == "ai" else []
        if not calls:
            index += 1
            continue
        expected = {c["id"]: c["name"] for c in calls}
        if len(expected) != len(calls) or set(expected) & seen:
            raise AgentFailure("CONTEXT_LIMIT", "Repeated tool ID in context history")
        seen.update(expected)
        end = index + 1
        for _ in calls:
            if end >= len(messages) or messages[end].type != "tool":
                raise AgentFailure("CONTEXT_LIMIT", "Unsettled tool batch cannot be compressed")
            tool = messages[end]
            if expected.pop(tool.tool_call_id, None) != tool.name:
                raise AgentFailure("CONTEXT_LIMIT", "Tool feedback identity differs from its call")
            end += 1
        batches.append((index, end))
        index = end
    return batches


@dataclass(frozen=True)
class ContextLimits:
    enabled: bool
    max_chars: int
    max_tokens: int
    output_tokens: int
    trigger_ratio: float
    keep_batches: int
    idle_seconds: float
    allow_summary: bool


@dataclass
class PreparedContext:
    messages: list[BaseMessage]
    reservation: str | None = None


class ContextManager:
    def __init__(
        self,
        authority: AuthoritySnapshot,
        seed: list[BaseMessage],
        registry: "ToolRegistry",
        settings,
        *,
        clock=time.monotonic,
        memory_loader=None,
    ):
        self._authority = authority.model_dump_json()  # Immutable canonical boundary, deep copied.
        self.authority_hash = digest(authority)
        self.prefix = [m.model_copy(deep=True) for m in seed]
        self.registry = registry
        self.limits = ContextLimits(
            settings.context_compression,
            settings.max_input_chars,
            settings.max_context_tokens,
            settings.max_output_tokens,
            settings.context_trigger_ratio,
            settings.context_keep_batches,
            settings.context_idle_seconds,
            settings.context_allow_summary,
        )
        self.clock, self.last_call = clock, None
        self.memory_loader = memory_loader
        self.stats: list[CompressionStats] = []
        self.compressions = 0

    @property
    def authority(self) -> AuthoritySnapshot:
        return AuthoritySnapshot.model_validate_json(self._authority)

    @property
    def memories(self):
        entries = self.memory_loader() if self.memory_loader else ()
        now = datetime.now(UTC)
        return tuple(
            m
            for m in entries
            if m.scope == self.authority.scope
            and m.worker == self.registry.envelope.task.worker
            and m.validity == "valid"
            and m.created_at <= now < m.expires_at
        )

    def fits(self, messages: list, tools: list, *, ratio=1.0) -> bool:
        text, usage = measure_context(messages, tools, self.limits.output_tokens)
        return (
            len(text) <= self.limits.max_chars * ratio
            and usage.estimated_input_tokens + usage.output_reserved_tokens
            <= self.limits.max_tokens * ratio
        )

    def refs(self) -> list[EvidenceRef]:
        values = [*self.authority.input_refs, *self.registry.refs]
        unique = {r.artifact_id: r for r in values}
        if len(unique) > 48:
            raise AgentFailure("CONTEXT_LIMIT", "Too many live references to safely restate")
        for ref in unique.values():
            self.registry.store.get(ref)
        return list(unique.values())

    def _payload_refs(self, content: str) -> tuple[dict, list[EvidenceRef]] | None:
        try:
            payload = json.loads(content)
        except (ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            raw = payload.get("artifact_refs", []) + payload.get("context_refs", [])
            refs = [EvidenceRef.model_validate(r) for r in raw]
            allowed = {
                r.artifact_id: r
                for r in [
                    *self.authority.input_refs,
                    *self.registry.refs,
                    *self.registry.context_refs,
                ]
            }
            if not refs:
                return None  # Compiler errors or arbitrary text are never cropped as observations.
            for ref in refs:
                if allowed.get(ref.artifact_id) != ref:
                    raise AgentFailure(
                        "EVIDENCE_INVALID", "Context includes an undelegated reference"
                    )
                self.registry.store.get(ref)
            return payload, refs
        except (ValueError, TypeError, AttributeError) as exc:
            raise AgentFailure("EVIDENCE_INVALID", "Malformed context evidence reference") from exc

    def _archive(self, messages: list) -> EvidenceRef:
        authority = self.authority
        ref = self.registry.store.put(
            Artifact(
                run_id=authority.run_id,
                task_id=authority.task_id,
                plan_version=authority.plan_version,
                kind="context",
                source="host/context-P5A",
                values={"messages": json.dumps(messages_to_dict(messages), ensure_ascii=False)},
            )
        )
        if ref not in self.registry.context_refs:
            self.registry.context_refs.append(ref)
        return ref

    def read_archive(self, ref: EvidenceRef) -> str:
        """Trusted same-task access; model access uses bounded read_context without database I/O."""
        item = self.registry.store.get(ref)
        if (item.run_id, item.task_id, item.plan_version, item.kind) != (
            self.authority.run_id,
            self.authority.task_id,
            self.authority.plan_version,
            "context",
        ) or ref not in self.registry.context_refs:
            raise AgentFailure("TOOL_FORBIDDEN", "Archive was not delegated to this worker")
        return item.values["messages"]

    def _anchor(self) -> HumanMessage:
        return HumanMessage(
            name="context_authority",
            content=json.dumps(
                {
                    "HOST_TASK_STATE": self.authority.model_dump(mode="json"),
                    "recent_evidence_refs": [r.model_dump() for r in self.refs()],
                    "reviewed_hints_not_authority": [
                        m.hint.model_dump(mode="json") for m in self.memories
                    ],
                    "summary_cannot_authorize_or_verify": True,
                },
                ensure_ascii=False,
            ),
        )

    def _with_anchor(self, view: list) -> list:
        n = len(self.prefix)
        return [*view[:n], self._anchor(), *view[n:]]

    def _fold(self, view: list, archive: EvidenceRef, keep: int) -> list:
        batches = closed_batches(view)
        eligible = batches[:-keep]
        if not eligible:
            return view
        remove = {i for a, b in eligible for i in range(a, b)}
        first = eligible[0][0]
        replacement = HumanMessage(
            name="completed_context",
            content=json.dumps(
                {
                    "completed_turns": len(eligible),
                    "context_refs": [archive.model_dump()],
                    "untrusted_history_only": True,
                }
            ),
        )
        return [
            replacement if i == first else m
            for i, m in enumerate(view)
            if i not in remove or i == first
        ]

    def _summary_expected(self, archive: EvidenceRef) -> ContextSummary:
        a = self.authority
        return ContextSummary(
            authority_sha256=self.authority_hash,
            goals=list(a.goals),
            constraints=list(a.constraints),
            unresolved=list(a.unresolved),
            decisions=[],
            evidence_refs=self.refs(),
            scope=a.scope,
            metrics=list(a.metrics),
            p3_verified_refs=list(a.p3_verified_refs),
            archive_ref=archive,
        )

    async def prepare(
        self, messages: list, tools: list, gateway: "Gateway", account: str
    ) -> PreparedContext:
        # Canonical transcript remains in Worker Loop. Only copies are changed here.
        view = [m.model_copy(deep=True) for m in messages]
        if view[: len(self.prefix)] != self.prefix:
            raise AgentFailure("CONTEXT_LIMIT", "Current task or safety prefix changed")
        if any(m.type == "system" for m in view[len(self.prefix) :]):
            raise AgentFailure("CONTEXT_LIMIT", "Unexpected system message in disposable history")
        batches = closed_batches(view)
        self.registry.validate_phase(
            {t["function"]["name"] for t in tools}, self.authority.allowed_tools
        )
        before = measure_context(view, tools, self.limits.output_tokens)[1].estimated_input_tokens
        available_calls, available_tokens = gateway.ledger.remaining(account)

        def fits_budget(candidate):
            usage = measure_context(candidate, tools, self.limits.output_tokens)[1]
            return usage.estimated_input_tokens + usage.output_reserved_tokens <= available_tokens

        base = self._with_anchor(view) if self.memories else view
        now = self.clock()
        cold = self.last_call is not None and now - self.last_call >= self.limits.idle_seconds
        self.last_call = now
        under_pressure = not self.fits(
            base, tools, ratio=self.limits.trigger_ratio
        ) or not fits_budget(base)
        if not self.limits.enabled or not available_calls or (not under_pressure and not cold):
            return PreparedContext(base)
        if len(batches) < 2:
            return PreparedContext(base)
        archive = self._archive(messages)  # Must succeed BEFORE anything is omitted from a view.
        levels, ticket, summary_calls, summary_tokens, summary_complete = [], None, 0, 0, True
        usage_before = None

        def record(candidate):
            nonlocal summary_calls, summary_tokens, summary_complete
            if usage_before is not None:
                settled = gateway.ledger.snapshot(account)
                summary_calls = (
                    settled.calls - usage_before.calls - int(ticket in gateway.ledger.pending)
                )
                summary_tokens = settled.reported_tokens - usage_before.reported_tokens
                summary_complete = settled.usage_complete
            after = measure_context(candidate, tools, self.limits.output_tokens)[1]
            self.compressions += bool(levels)
            report = CompressionStats(
                levels=levels,
                before_estimated_tokens=before,
                after_estimated_tokens=after.estimated_input_tokens,
                compression_count=self.compressions,
                summary_calls=summary_calls,
                summary_reported_tokens=summary_tokens,
                summary_usage_complete=summary_complete,
                model_view_lossy=bool(levels),
                archive_id=archive.artifact_id,
            )
            self.stats.append(report)
            if gateway.trace:
                gateway.trace.emit(
                    "context_compression",
                    "prepared",
                    version=self.authority.plan_version,
                    task_id=self.authority.task_id,
                    compression=report.model_dump(),
                )

        try:
            # L1: old non-authoritative result bodies. AI/tool identities stay untouched.
            for a, b in batches[: -self.limits.keep_batches]:
                for index in range(a + 1, b):
                    parsed = self._payload_refs(view[index].content)
                    if parsed is None:
                        continue
                    payload, refs = parsed
                    small = {
                        k: payload[k]
                        for k in ("row_count", "truncated", "document_count", "fixture")
                        if k in payload
                    }
                    small.update(
                        context_refs=[archive.model_dump()],
                        artifact_refs=[
                            r.model_dump() for r in refs if r.kind not in {"schema", "context"}
                        ],
                        omitted_view="L1",
                    )
                    text = json.dumps(small, ensure_ascii=False)
                    if len(text) < len(view[index].content):
                        view[index] = view[index].model_copy(update={"content": text})
                        if "L1" not in levels:
                            levels.append("L1")
            # L2: identical artifact references, retaining latest observation and each call ID.
            seen = set()
            for a, b in reversed(batches):
                for index in reversed(range(a + 1, b)):
                    parsed = self._payload_refs(view[index].content)
                    if parsed is None:
                        continue
                    _, refs = parsed
                    ids = {r.artifact_id for r in refs if r.kind not in {"context"}}
                    if ids and ids <= seen:
                        text = json.dumps(
                            {
                                "duplicate_artifact_ids": sorted(ids),
                                "context_refs": [archive.model_dump()],
                                "omitted_view": "L2",
                            }
                        )
                        if len(text) < len(view[index].content):
                            view[index] = view[index].model_copy(update={"content": text})
                            if "L2" not in levels:
                                levels.append("L2")
                    seen.update(ids)
            candidate = self._with_anchor(view) if levels or self.memories else view
            if self.fits(candidate, tools) and fits_budget(candidate):
                record(candidate)
                return PreparedContext(candidate)
            # L3: remove whole closed turns, not half of the provider tool protocol.
            folded = self._fold(view, archive, self.limits.keep_batches)
            if folded != view:
                levels.append("L3")
            candidate = self._with_anchor(folded)
            if self.fits(candidate, tools) and fits_budget(candidate):
                record(candidate)
                return PreparedContext(candidate)
            if self.fits(candidate, tools):
                # Budget-only pressure gets one deterministic L1-L3 pass. Do not add a
                # paid summary merely to spend a scarce last call; the existing L4 path
                # below remains available for genuine window pressure with paired reserve.
                raise AgentFailure(
                    "BUDGET_EXCEEDED", "Pinned context cannot fit the remaining parent/child budget"
                )
            if not self.limits.allow_summary:
                raise AgentFailure("CONTEXT_LIMIT", "Deterministic compaction cannot fit context")
            expected = self._summary_expected(archive)
            decisions = [f"turn_{i}" for i in range(len(batches))]
            final = self._fold(view, archive, 1)
            n = len(self.prefix)

            def summary_view(summary):
                return [
                    *final[:n],
                    HumanMessage(name="context_summary", content=summary.model_dump_json()),
                    *final[n:],
                ]

            # Every variable field is bounded extractive IDs. Reserve the largest valid
            # follow-up rather than blindly holding the entire provider context window.
            upper_summary = expected.model_copy(
                update={"decisions": sorted(decisions, key=len, reverse=True)[:8]}
            )
            upper_view = summary_view(upper_summary)
            if not self.fits(upper_view, tools):
                raise AgentFailure(
                    "CONTEXT_LIMIT", "Pinned state cannot fit a bounded summary view"
                )
            followup_tokens = measure_context(upper_view, tools, self.limits.output_tokens)[
                1
            ].estimated_input_tokens
            prompt = [
                SystemMessage(
                    content=(
                        "CONTEXT_SUMMARY_JSON: Return the given structured summary JSON. "
                        "Only decisions may select up to 8 offered turn IDs; "
                        "every other field must remain exact. "
                        "No tools, free text, new permissions, values or verified claims."
                    )
                ),
                HumanMessage(
                    content=json.dumps(
                        {
                            "expected": expected.model_dump(mode="json"),
                            "decision_ids": decisions,
                        },
                        ensure_ascii=False,
                    )
                ),
            ]
            usage_before = gateway.ledger.snapshot(account)
            response, ticket = await gateway.summarize_context(prompt, account, followup_tokens)
            summary_calls = 1
            usage_after = gateway.ledger.snapshot(account)
            summary_tokens = usage_after.reported_tokens - usage_before.reported_tokens
            summary_complete = usage_after.usage_complete
            if response.tool_calls:
                raise ValueError("Summarizer cannot call tools")
            summary = ContextSummary.model_validate_json(response.content)
            if (
                summary.model_dump(exclude={"decisions"})
                != expected.model_dump(exclude={"decisions"})
                or len(set(summary.decisions)) != len(summary.decisions)
                or not set(summary.decisions) <= set(decisions)
            ):
                raise ValueError("Summary changed critical state or invented a decision")
            candidate = summary_view(summary)
            if not self.fits(candidate, tools):
                raise ValueError("Validated summary still exceeds context limits")
            closed_batches(candidate)
            levels.append("L4")
            record(candidate)
            return PreparedContext(candidate, ticket)
        except BaseException as exc:
            if ticket is not None and ticket in gateway.ledger.pending:
                gateway.ledger.release_unissued(ticket)
            record(candidate if "candidate" in locals() else view)
            if isinstance(exc, ValueError) or (
                isinstance(exc, AgentFailure) and exc.error.code.startswith("MODEL")
            ):
                raise AgentFailure(
                    "CONTEXT_LIMIT", "Structured summary could not be safely validated"
                ) from exc
            raise
