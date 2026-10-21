"""Reviewed hints only. This store is ephemeral, not an execution checkpoint or Registry."""

import json
from datetime import datetime
from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from datapilot.contracts import AgentFailure
from datapilot.orchestration.context_contracts import ContextScope, FrozenContract
from datapilot.orchestration.contracts import Digest, TaskId, Worker


class PreferenceHint(FrozenContract):
    kind: Literal["preference"] = "preference"
    key: Literal["language", "verbosity", "report_format"]
    value: Literal["zh", "en", "concise", "detailed", "markdown", "table"]

    @model_validator(mode="after")
    def constrained_value(self):
        choices = {
            "language": {"zh", "en"},
            "verbosity": {"concise", "detailed"},
            "report_format": {"markdown", "table"},
        }
        if self.value not in choices[self.key]:
            raise ValueError("Unsupported preference")
        return self


class TermHint(FrozenContract):
    kind: Literal["term"] = "term"
    term_code: TaskId
    definition_ref: Digest  # A reviewed hint must refer back to a current definition.
    definition_version: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")


class DecisionHint(FrozenContract):
    kind: Literal["decision"] = "decision"
    decision_code: TaskId
    reference: Digest
    reference_version: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")


class MemoryEntry(FrozenContract):
    memory_id: TaskId
    hint: Annotated[PreferenceHint | TermHint | DecisionHint, Field(discriminator="kind")]
    created_at: datetime
    expires_at: datetime
    source_ref: Digest
    source_version: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    scope: ContextScope
    worker: Worker
    validity: Literal["valid", "invalidated"] = "valid"
    invalidation: Literal["user_revoked", "source_changed", "policy_changed"] | None = None
    invalidated_at: datetime | None = None

    @model_validator(mode="after")
    def coherent(self):
        for stamp in (self.created_at, self.expires_at, self.invalidated_at):
            if stamp is not None and stamp.utcoffset() is None:
                raise ValueError("Memory timestamps require explicit timezone")
        if self.expires_at <= self.created_at:
            raise ValueError("Memory expiry must follow creation")
        if (self.validity == "invalidated") != (
            self.invalidation is not None and self.invalidated_at is not None
        ):
            raise ValueError("Memory invalidation requires reason and timestamp")
        if self.validity == "valid" and (
            self.invalidation is not None or self.invalidated_at is not None
        ):
            raise ValueError("Valid memory cannot carry partial invalidation metadata")
        if self.invalidated_at is not None and self.invalidated_at < self.created_at:
            raise ValueError("Invalidation precedes memory creation")
        return self


class MemoryStore(Protocol):
    def put_reviewed(self, entry: MemoryEntry, *, reviewed: bool) -> None: ...

    def recall(
        self, scope: ContextScope, worker: Worker, *, now: datetime, source_versions: dict[str, str]
    ) -> tuple[MemoryEntry, ...]: ...

    def invalidate(self, memory_id: str, *, reason: str, at: datetime) -> None: ...


class InMemoryMemoryStore:
    """No arbitrary text, raw business rows, credentials, LLM writes, files or DB operations."""

    def __init__(self):
        self._entries: dict[str, MemoryEntry] = {}

    def put_reviewed(self, entry: MemoryEntry, *, reviewed: bool) -> None:
        if reviewed is not True:
            raise AgentFailure("MEMORY_REVIEW_REQUIRED", "Memory needs explicit host review")
        checked = MemoryEntry.model_validate_json(entry.model_dump_json())
        if checked.memory_id in self._entries:
            raise AgentFailure("MEMORY_CONFLICT", "Use a new ID for a revised memory")
        size = sum(len(v.model_dump_json().encode()) for v in self._entries.values())
        if len(self._entries) >= 64 or size + len(checked.model_dump_json().encode()) > 65536:
            raise AgentFailure("MEMORY_LIMIT", "Reviewed hint store is full")
        self._entries[checked.memory_id] = checked

    def recall(
        self, scope: ContextScope, worker: Worker, *, now: datetime, source_versions: dict[str, str]
    ) -> tuple[MemoryEntry, ...]:
        if now.utcoffset() is None:
            raise ValueError("Recall time requires explicit timezone")
        found = []
        for entry in self._entries.values():
            if (
                entry.scope != scope
                or entry.worker != worker
                or entry.validity != "valid"
                or not entry.created_at <= now < entry.expires_at
                or source_versions.get(entry.source_ref) != entry.source_version
            ):
                continue
            if isinstance(entry.hint, (TermHint, DecisionHint)):
                reference = (
                    entry.hint.definition_ref
                    if isinstance(entry.hint, TermHint)
                    else entry.hint.reference
                )
                version = (
                    entry.hint.definition_version
                    if isinstance(entry.hint, TermHint)
                    else entry.hint.reference_version
                )
                if source_versions.get(reference) != version:
                    continue
            found.append(MemoryEntry.model_validate_json(entry.model_dump_json()))
        return tuple(sorted(found, key=lambda e: e.memory_id)[:8])

    def invalidate(self, memory_id: str, *, reason: str, at: datetime) -> None:
        entry = self._entries[memory_id]
        raw = entry.model_dump(mode="json")
        raw.update(validity="invalidated", invalidation=reason, invalidated_at=at.isoformat())
        self._entries[memory_id] = MemoryEntry.model_validate_json(json.dumps(raw))
