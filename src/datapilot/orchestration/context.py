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
                    **(
                        {
                            "source_ref": d.citation.model_dump(
                                include={"corpus_id", "index_version", "source_id", "document_id"}
                            )
                        }
                        if d.citation
                        else {}
                    ),
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

    def _dedupe_observations(self, view: list) -> tuple[list, bool]:
        """Replace a repeated source body with its already-present reference.

        This is a view-only L1 step. The canonical transcript and artifact remain
        unchanged; the model has already seen the exact text in an earlier tool
        result, so repeating it cannot add evidence or authority.
        """
        seen: set[str] = set()
        output = list(view)
        changed = False
        for index, message in enumerate(output):
            if message.type != "tool":
                continue
            try:
                payload = json.loads(message.content)
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            texts = []
            if isinstance(payload.get("text"), str):
                texts.append(payload["text"])
            documents = payload.get("documents")
            if isinstance(documents, list):
                texts.extend(
                    document["text"]
                    for document in documents
                    if isinstance(document, dict) and isinstance(document.get("text"), str)
                )
            if (
                message.name == "search_documents"
                and not texts
                and payload.get("document_count") == 0
            ):
                compact = json.dumps(
                    {"document_count": 0, "omitted_view": "L1", "no_matching_documents": True}
                )
                if len(compact) < len(message.content):
                    output[index] = message.model_copy(update={"content": compact})
                    changed = True
                continue
            if texts and all(text in seen for text in texts):
                small = {
                    key: payload[key]
                    for key in (
                        "artifact_refs",
                        "context_refs",
                        "citation_ref",
                        "document_count",
                        "fixture",
                        "model_view",
                    )
                    if key in payload
                }
                small.update(duplicate_text=True, omitted_view="L1")
                compact = json.dumps(small, ensure_ascii=False)
                if len(compact) < len(message.content):
                    output[index] = message.model_copy(update={"content": compact})
                    changed = True
            seen.update(texts)
        return output, changed

    def _first_batch_view(self, messages: list, *, share_documents=True) -> tuple[list, int]:
        """Losslessly share verified RAG previews within one closed tool batch.

        References only point backwards to a full preview kept in this same view.
        All per-query differences remain complete field overrides. Neither source
        artifacts nor the canonical AI/Tool transcript are changed.
        """
        output = list(messages)
        seen = {}
        references = 0
        full_previews = {}
        identity_fields = {
            "corpus_id",
            "index_version",
            "source_id",
            "document_id",
            "version",
            "source_sha256",
            "chunk_id",
            "start",
            "end",
            "line_start",
            "line_end",
            "sha256",
            "model_revision",
            "chunker_sha256",
            "retriever",
        }
        for index, message in enumerate(messages):
            if message.type != "tool" or message.name != "search_documents":
                continue
            parsed = self._payload_refs(message.content)
            if parsed is None:
                continue
            payload, refs = parsed

            def unique_fields(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Repeated JSON field")
                    result[key] = value
                return result

            try:
                payload = json.loads(message.content, object_pairs_hook=unique_fields)
                # Reject non-finite values rather than changing their JSON meaning.
                json.dumps(payload, allow_nan=False)
            except (ValueError, TypeError) as exc:
                raise AgentFailure("EVIDENCE_INVALID", "Ambiguous document preview JSON") from exc
            if len(refs) != 1 or refs[0].kind != "documents":
                continue
            artifact = self.registry.store.get(refs[0])
            if (
                artifact.run_id != self.authority.run_id
                or artifact.task_id != self.authority.task_id
                or artifact.plan_version != self.authority.plan_version
                or artifact.documents is None
            ):
                continue
            documents = payload.get("documents")
            if not isinstance(documents, list):
                continue
            result = artifact.documents
            preview = tool_view(artifact, refs[0], self.registry.max_view_chars).get("documents")
            full = [d.model_dump(mode="json") for d in result.documents]
            if (
                type(payload.get("document_count")) is not int
                or payload["document_count"] != len(result.documents)
                or payload.get("fixture") is not result.fixture
                or (
                    digest(documents) != digest(preview)
                    and not (result.fixture and digest(documents) == digest(full))
                )
            ):
                raise AgentFailure("EVIDENCE_INVALID", "Document preview differs from its artifact")
            small = []
            for number, (document, original) in enumerate(
                zip(documents, result.documents, strict=True)
            ):
                citation = original.citation
                identity = digest(
                    {
                        "document_id": original.document_id,
                        "source": original.source,
                        "version": original.version,
                        "sha256": original.sha256,
                        "text": original.text,
                        "citation": citation.model_dump(mode="json", include=identity_fields)
                        if citation
                        else None,
                    }
                )
                previous = seen.get(identity) if citation and share_documents else None
                if previous is not None and previous[0] != message.tool_call_id:
                    call_id, position, base = previous
                    # A shallow, complete field replacement preserves query-specific
                    # citation scores and any other current observation metadata.
                    overrides = {
                        key: value
                        for key, value in document.items()
                        if key not in base or digest(base[key]) != digest(value)
                    }
                    if base.keys() == document.keys() and digest(base | overrides) == digest(
                        document
                    ):
                        shared = {
                            "document_id": document["document_id"],
                            "document_ref": {
                                "tool_call_id": call_id,
                                "document_index": position,
                                "view_sha256": digest(base),
                            },
                        }
                        if overrides:
                            shared["overrides"] = overrides
                        if len(json.dumps(shared, ensure_ascii=False)) < len(
                            json.dumps(document, ensure_ascii=False)
                        ):
                            small.append(shared)
                            references += 1
                            continue
                small.append(document)
                # Never target a compressed entry: no chains, cycles or forward refs.
                seen.setdefault(identity, (message.tool_call_id, number, document))
                full_previews[(message.tool_call_id, number)] = document
            compact = json.dumps(
                payload | {"documents": small},
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            # Verify the entire expanded payload, including all unknown top-level
            # fields. An indirect view must reproduce every original observation.
            expanded = json.loads(compact)
            for number, document in enumerate(expanded["documents"]):
                pointer = document.get("document_ref")
                if pointer is not None:
                    target = full_previews.get((pointer["tool_call_id"], pointer["document_index"]))
                    if target is None or digest(target) != pointer["view_sha256"]:
                        raise AgentFailure("EVIDENCE_INVALID", "Document view target changed")
                    expanded["documents"][number] = target | document.get("overrides", {})
            if digest(expanded) != digest(payload):
                raise AgentFailure("EVIDENCE_INVALID", "Document view changed observation fields")
            if len(compact.encode("utf-8")) < len(message.content.encode("utf-8")):
                output[index] = message.model_copy(update={"content": compact})
        return output, references

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

    def _anchor(self, *, compact: bool = False) -> HumanMessage:
        if compact:
            content = json.dumps(
                {
                    "HOST_TASK_STATE_SHA256": self.authority_hash,
                    "allowed_tools": list(self.authority.allowed_tools),
                    "summary_cannot_authorize_or_verify": True,
                    "authority_details_are_in_the_immutable_prefix": True,
                },
                ensure_ascii=False,
            )
        else:
            content = json.dumps(
                {
                    "HOST_TASK_STATE": self.authority.model_dump(mode="json"),
                    "recent_evidence_refs": [r.model_dump() for r in self.refs()],
                    "reviewed_hints_not_authority": [
                        m.hint.model_dump(mode="json") for m in self.memories
                    ],
                    "summary_cannot_authorize_or_verify": True,
                },
                ensure_ascii=False,
            )
        return HumanMessage(name="context_authority", content=content)

    def _with_anchor(self, view: list, *, compact: bool = False) -> list:
        n = len(self.prefix)
        body = [
            message for message in view[n:] if getattr(message, "name", None) != "context_authority"
        ]
        return [*view[:n], self._anchor(compact=compact), *body]

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

    def _compact_old_tool_results(self, view: list, *, keep: int = 1) -> list:
        """Replace old closed tool bodies with their existing artifact refs."""
        indices = [i for i, message in enumerate(view) if message.type == "tool"]
        for index in indices[:-keep]:
            parsed = self._payload_refs(view[index].content)
            if parsed is None:
                continue
            payload, refs = parsed
            small = {
                key: payload[key]
                for key in ("row_count", "truncated", "document_count", "fixture")
                if key in payload
            }
            small.update(
                artifact_refs=[
                    ref.model_dump() for ref in refs if ref.kind not in {"schema", "context"}
                ],
                omitted_view="budget-old-tool-result",
            )
            text = json.dumps(small, ensure_ascii=False)
            if len(text) < len(view[index].content):
                view[index] = view[index].model_copy(update={"content": text})
        return view

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
        budget_pressure = not fits_budget(base)
        under_pressure = (
            not self.fits(base, tools, ratio=self.limits.trigger_ratio) or budget_pressure
        )
        if not self.limits.enabled or not available_calls or (not under_pressure and not cold):
            return PreparedContext(base)
        if len(batches) < 2:
            if len(batches) == 1 and under_pressure:
                candidate, references = self._first_batch_view(base, share_documents=False)
                if not self.fits(candidate, tools) or not fits_budget(candidate):
                    candidate, references = self._first_batch_view(base)
                after = measure_context(candidate, tools, self.limits.output_tokens)[1]
                initial = measure_context(base, tools, self.limits.output_tokens)[1]
                if (
                    after.estimated_input_tokens < initial.estimated_input_tokens
                    and self.fits(candidate, tools)
                    and fits_budget(candidate)
                ):
                    # Store full originals before using an indirect model view.
                    # No authority anchor is added: the immutable prefix and every
                    # AI/Tool feedback pair already remain present in full.
                    archive = self._archive(messages)
                    self.compressions += 1
                    report = CompressionStats(
                        levels=["L2"],
                        components={
                            "first_closed_batch": 1,
                            "document_view_references": references,
                            "input_bytes_saved": initial.input_bytes - after.input_bytes,
                        },
                        before_estimated_tokens=initial.estimated_input_tokens,
                        after_estimated_tokens=after.estimated_input_tokens,
                        compression_count=self.compressions,
                        model_view_lossy=False,
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
                    return PreparedContext(candidate)
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

            def tokens(messages, schemas):
                return measure_context(messages, schemas, 0)[1].estimated_input_tokens

            tools_only = tokens([], tools)
            message_only = tokens(candidate, [])
            tool_messages = [m for m in candidate if m.type == "tool"]
            anchor_messages = [
                m for m in candidate if getattr(m, "name", None) == "context_authority"
            ]
            components = {
                "total": after.estimated_input_tokens,
                "prefix": tokens(candidate[: len(self.prefix)], []),
                "anchor": tokens(anchor_messages, []),
                "anchor_count": len(anchor_messages),
                "anchor_full": tokens([self._anchor(compact=False)], []),
                "anchor_compact": tokens([self._anchor(compact=True)], []),
                "tool_schemas": tools_only,
                "messages_without_schemas": message_only,
                "tool_results": sum(tokens([m], []) for m in tool_messages),
                "latest_tool_result": tokens(tool_messages[-1:], []),
                "non_tool_messages": tokens([m for m in candidate if m.type != "tool"], []),
                "summary_message_tokens": tokens(
                    [m for m in candidate if getattr(m, "name", None) == "context_summary"],
                    [],
                ),
            }
            self.compressions += bool(levels)
            report = CompressionStats(
                levels=levels,
                components=components,
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
            # L1 also removes an exact repeated source body. This is a view-only
            # ref; the earlier tool result and the artifact remain available.
            view, deduped = self._dedupe_observations(view)
            if deduped and "L1" not in levels:
                levels.append("L1")
            candidate = view
            if budget_pressure:
                compact_anchor = self._with_anchor(candidate, compact=True)
                if self.fits(compact_anchor, tools) and fits_budget(compact_anchor):
                    record(compact_anchor)
                    return PreparedContext(compact_anchor)
            # Try the compact view before the full authority anchor. On a tight
            # parent/child budget, the anchor's repeated host state can itself
            # be the difference between a valid next call and a pre-dispatch
            # rejection; the immutable prefix still carries the task scope.
            candidate = self._with_anchor(candidate) if levels or self.memories else candidate
            if self.fits(candidate, tools) and fits_budget(candidate):
                record(candidate)
                return PreparedContext(candidate)
            # L3: remove whole closed turns, not half of the provider tool protocol.
            folded = self._fold(view, archive, self.limits.keep_batches)
            if folded != view:
                levels.append("L3")
            candidate = folded
            if budget_pressure:
                compact_anchor = self._with_anchor(candidate, compact=True)
                if self.fits(compact_anchor, tools) and fits_budget(compact_anchor):
                    record(compact_anchor)
                    return PreparedContext(compact_anchor)
            candidate = self._with_anchor(folded)
            if self.fits(candidate, tools) and fits_budget(candidate):
                record(candidate)
                return PreparedContext(candidate)
            if self.fits(candidate, tools):
                # Budget-only pressure: try folding one additional closed batch before
                # declaring the pinned context unaffordable. The latest completed turn
                # remains in the view; older turns stay available through the archive ref.
                if self.limits.keep_batches > 1:
                    tighter = self._fold(view, archive, self.limits.keep_batches - 1)
                    tighter = self._with_anchor(tighter, compact=True)
                    if tighter != view and self.fits(tighter, tools) and fits_budget(tighter):
                        if "L3" not in levels:
                            levels.append("L3")
                        record(tighter)
                        return PreparedContext(tighter)
                # If deterministic folding is insufficient, allow the existing L4
                # summary path only when its paired reservation fits the remaining
                # parent/child budget. summarize_context remains the budget gate.
                if not self.limits.allow_summary:
                    raise AgentFailure(
                        "BUDGET_EXCEEDED",
                        "Pinned context cannot fit the remaining parent/child budget",
                    )
            elif not self.limits.allow_summary:
                raise AgentFailure("CONTEXT_LIMIT", "Deterministic compaction cannot fit context")
            expected = self._summary_expected(archive)
            decisions = [f"turn_{i}" for i in range(len(batches))]
            final = self._fold(view, archive, 1)
            failed_candidate = self._compact_old_tool_results(
                self._with_anchor(final, compact=True)
            )
            n = len(self.prefix)

            def summary_view(summary):
                if any(getattr(message, "name", None) == "context_authority" for message in final):
                    body = [
                        message
                        for message in final
                        if getattr(message, "name", None) != "context_authority"
                    ]
                    body = self._compact_old_tool_results(body)
                    compact = [*body[:n], self._anchor(compact=True), *body[n:]]
                else:
                    compact = final
                summary_json = json.dumps(
                    summary.model_dump(mode="json", exclude={"goals", "constraints"}),
                    ensure_ascii=False,
                )
                return [
                    *compact[:n],
                    HumanMessage(name="context_summary", content=summary_json),
                    *compact[n:],
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
            if not fits_budget(upper_view):
                record(failed_candidate)
                raise AgentFailure(
                    "BUDGET_EXCEEDED",
                    "Summary and its worst-case follow-up do not fit the remaining budget",
                )
            followup_tokens = measure_context(upper_view, tools, self.limits.output_tokens)[
                1
            ].estimated_input_tokens
            prompt = [
                SystemMessage(
                    content=(
                        'CONTEXT_SUMMARY_JSON: Return only {"decisions": [...]} selecting '
                        "up to 8 of the offered turn IDs. No other fields, free text, tools, "
                        "permissions, values or verified claims."
                    )
                ),
                HumanMessage(content=json.dumps({"decision_ids": decisions}, ensure_ascii=False)),
            ]
            usage_before = gateway.ledger.snapshot(account)
            response, ticket = await gateway.summarize_context(prompt, account, followup_tokens)
            summary_calls = 1
            usage_after = gateway.ledger.snapshot(account)
            summary_tokens = usage_after.reported_tokens - usage_before.reported_tokens
            summary_complete = usage_after.usage_complete
            if response.tool_calls:
                raise ValueError("Summarizer cannot call tools")
            try:
                payload = json.loads(response.content)
            except (TypeError, ValueError) as exc:
                raise ValueError("Summary response is not a single JSON object") from exc
            if (
                not isinstance(payload, dict)
                or set(payload) != {"decisions"}
                or not isinstance(payload["decisions"], list)
                or any(not isinstance(item, str) for item in payload["decisions"])
                or len(set(payload["decisions"])) != len(payload["decisions"])
                or not set(payload["decisions"]) <= set(decisions)
            ):
                raise ValueError("Summary changed critical state or invented a decision")
            summary = ContextSummary.model_validate(
                expected.model_dump() | {"decisions": payload["decisions"]}
            )
            summary_candidate = summary_view(summary)
            candidate = summary_candidate
            if not self.fits(candidate, tools):
                raise ValueError("Validated summary still exceeds context limits")
            closed_batches(candidate)
            levels.append("L4")
            record(candidate)
            return PreparedContext(candidate, ticket)
        except BaseException as exc:
            if ticket is not None and ticket in gateway.ledger.pending:
                gateway.ledger.release_unissued(ticket)
            record(
                summary_candidate
                if "summary_candidate" in locals() and summary_candidate is not None
                else failed_candidate
                if "failed_candidate" in locals()
                else view
            )
            if isinstance(exc, ValueError) or (
                isinstance(exc, AgentFailure) and exc.error.code.startswith("MODEL")
            ):
                raise AgentFailure(
                    "CONTEXT_LIMIT", "Structured summary could not be safely validated"
                ) from exc
            raise
