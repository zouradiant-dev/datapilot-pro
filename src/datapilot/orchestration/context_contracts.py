"""Host authority and disposable model views are different contracts, never permissions."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from datapilot.contracts import AgentFailure, Contract
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Digest, EvidenceRef, TaskEnvelope, TaskId
from datapilot.semantics.contracts import Evidence, MetricContext, MetricRequest, VerificationRecord
from datapilot.semantics.recipes import request_missing


class FrozenContract(Contract):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SourcePin(FrozenContract):
    dataset_id: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    source_sha256: Digest


class MetricBinding(FrozenContract):
    request: MetricRequest
    context: MetricContext

    @model_validator(mode="after")
    def consistent(self):
        try:
            # Identity only; unavailable stays unavailable. DTO failures cannot bypass the
            # summary validation boundary by throwing a differently classified P3 exception.
            request_missing(self.context, self.request)
        except AgentFailure as exc:
            raise ValueError("Metric request/context identity mismatch") from exc
        if digest(self.context.model_dump(mode="json", exclude={"context_sha256"})) != (
            self.context.context_sha256
        ):
            raise ValueError("Metric context hash mismatch")
        return self


class P3Reference(FrozenContract):
    evidence_id: str = Field(min_length=1, max_length=64)
    verification_id: str = Field(min_length=1, max_length=64)
    evidence_sha256: Digest
    verification_sha256: Digest
    request_sha256: Digest

    @classmethod
    def from_verified(cls, evidence: Evidence, record: VerificationRecord) -> "P3Reference":
        # A host-only projection of an existing P3 verdict, not a new verifier/report bridge.
        from datapilot.semantics.contracts import ReportClaim
        from datapilot.semantics.service import validate_claims

        evidence = Evidence.model_validate_json(evidence.model_dump_json())
        record = VerificationRecord.model_validate_json(record.model_dump_json())
        request = evidence.request
        if (
            record.verdict != "verified"
            or evidence.value is None
            or (
                evidence.dataset_id,
                evidence.dataset_version,
                evidence.semantic_version,
                evidence.metric_id,
                evidence.metric_version,
            )
            != (
                request.dataset_id,
                request.dataset_version,
                request.semantic_version,
                request.metric_id,
                request.metric_version,
            )
        ):
            raise ValueError("Only existing, matching verified metric evidence can be pinned")
        claim = ReportClaim(
            goal_id=evidence.request.goal_id,
            kind="metric",
            evidence_id=evidence.evidence_id,
            verification_id=record.verification_id,
            value=evidence.value,
        )
        validate_claims([evidence.request], [claim], lambda _: evidence, lambda _: record)
        return cls(
            evidence_id=evidence.evidence_id,
            verification_id=record.verification_id,
            evidence_sha256=digest(evidence),
            verification_sha256=digest(record),
            request_sha256=digest(evidence.request),
        )


class ContextScope(FrozenContract):
    owner: str = Field(default="local-user", min_length=1, max_length=64)
    profile: Literal["saas", "dataset"] = "saas"
    sources: tuple[SourcePin, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def scoped(self):
        if self.profile == "dataset" and not self.sources:
            raise ValueError("Dataset context requires explicit pinned versions")
        if len({p.dataset_id for p in self.sources}) != len(self.sources):
            raise ValueError("Duplicate source pin")
        return self


class AuthoritySnapshot(FrozenContract):
    run_id: str = Field(min_length=1, max_length=64)
    task_id: TaskId
    plan_version: int = Field(ge=1, le=10)
    goals: tuple[Annotated[str, Field(min_length=1, max_length=8000)], ...] = Field(
        min_length=1, max_length=4
    )
    constraints: tuple[Annotated[str, Field(max_length=8000)], ...] = Field(max_length=8)
    allowed_tools: tuple[str, ...] = Field(max_length=4)
    scope: ContextScope = Field(default_factory=ContextScope)
    dependencies: tuple[TaskId, ...] = Field(default=(), max_length=12)
    unresolved: tuple[TaskId, ...] = Field(min_length=1, max_length=12)
    input_refs: tuple[EvidenceRef, ...] = Field(default=(), max_length=48)
    metrics: tuple[MetricBinding, ...] = Field(default=(), max_length=8)
    p3_verified_refs: tuple[P3Reference, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def pinned_definitions(self):
        pins = {(s.dataset_id, s.version, s.source_sha256) for s in self.scope.sources}
        for binding in self.metrics:
            c = binding.context
            if (c.dataset_id, c.dataset_version, c.source_sha256) not in pins:
                raise ValueError("Metric definition is outside the trusted pinned source scope")
        requests = {digest(m.request) for m in self.metrics}
        if any(r.request_sha256 not in requests for r in self.p3_verified_refs):
            raise ValueError("P3 references must retain their exact metric request/definition")
        return self

    @classmethod
    def for_worker(
        cls, envelope: TaskEnvelope, question: str, safety: str, **metadata
    ) -> "AuthoritySnapshot":
        return cls(
            run_id=envelope.run_id,
            task_id=envelope.task.task_id,
            plan_version=envelope.plan_version,
            goals=tuple(dict.fromkeys([question, envelope.task.instruction])),
            constraints=(safety,),
            allowed_tools=tuple(envelope.allowed_tools),
            dependencies=tuple(envelope.task.dependencies),
            unresolved=(envelope.task.task_id,),
            input_refs=tuple(envelope.input_refs),
            **metadata,
        )


class ContextSummary(Contract):
    authority_sha256: Digest
    goals: list[str] = Field(max_length=4)
    constraints: list[str] = Field(max_length=8)
    unresolved: list[TaskId] = Field(max_length=12)
    # Extractive decision IDs only, never newly generated claims or executable instructions.
    decisions: list[Annotated[str, Field(pattern=r"^turn_[0-9]{1,4}$")]] = Field(max_length=8)
    evidence_refs: list[EvidenceRef] = Field(max_length=48)
    scope: ContextScope
    metrics: list[MetricBinding] = Field(max_length=8)
    p3_verified_refs: list[P3Reference] = Field(max_length=8)
    archive_ref: EvidenceRef


class CompressionStats(Contract):
    levels: list[Literal["L1", "L2", "L3", "L4"]] = Field(default_factory=list)
    before_estimated_tokens: int = Field(ge=0)
    after_estimated_tokens: int = Field(ge=0)
    compression_count: int = Field(ge=0)
    summary_calls: int = Field(default=0, ge=0)
    summary_reported_tokens: int = Field(default=0, ge=0)
    summary_usage_complete: bool = True
    irreversible_source_loss: Literal[False] = False
    model_view_lossy: bool = False
    archive_id: str | None = None
    cache_support: Literal["unverified"] = "unverified"
