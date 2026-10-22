"""Versioned host authorization, P3 bridge and auditable report projections."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from datapilot.contracts import Contract
from datapilot.datasets.contracts import DatasetId, DatasetScope
from datapilot.ingestion.contracts import Digest
from datapilot.rag.contracts import ChunkCitation, RagScope
from datapilot.semantics.contracts import (
    MetricContext,
    MetricRequest,
    MetricValue,
    MissingRequirement,
    VerificationRecord,
)


class DocumentGoal(Contract):
    goal_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    question: str = Field(min_length=1, max_length=512)
    metric_goals: list[str] = Field(min_length=1, max_length=6)


class ReportScope(Contract):
    schema_version: Literal["p6b-scope-1"] = "p6b-scope-1"
    owner: str = Field(default="local-user", min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=8000)
    datasets: DatasetScope
    metrics: list[MetricRequest] = Field(min_length=1, max_length=6)
    document_goal: DocumentGoal | None = None
    causal_requested: bool = False

    @model_validator(mode="after")
    def scope_is_explicit(self):
        import re

        goals = [m.goal_id for m in self.metrics]
        allowed = {(b.dataset_id, b.version) for b in self.datasets.bindings}
        if any((m.dataset_id, m.dataset_version) not in allowed for m in self.metrics):
            raise ValueError("Metric goals require explicit Dataset/version authorization")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", g) or g == "report" for g in goals):
            raise ValueError("Use bounded task goal IDs other than report")
        if len(set(goals)) != len(goals):
            raise ValueError("Duplicate metric goals")
        if self.document_goal:
            doc = self.document_goal
            if doc.goal_id in {*goals, "report"} or not set(doc.metric_goals) <= set(goals):
                raise ValueError("Document associations must reference authorized metric goals")
            if len(set(doc.metric_goals)) != len(doc.metric_goals):
                raise ValueError("Repeated document association")
        return self


class MetricBridge(Contract):
    schema_version: Literal["p3-p4-metric-1"] = "p3-p4-metric-1"
    request: MetricRequest
    source_sha256: Digest
    context: MetricContext | None = None
    evidence_id: DatasetId | None = None
    evidence_sha256: Digest | None = None
    query_sha256: Digest | None = None
    result_sha256: Digest | None = None
    verification: VerificationRecord | None = None
    verification_sha256: Digest | None = None
    verdict: Literal["verified", "unavailable", "rejected"]
    value: MetricValue | None = None
    missing: list[MissingRequirement] = Field(default_factory=list, max_length=32)
    verified_at: datetime

    @model_validator(mode="after")
    def no_promotion(self):
        if self.verified_at.tzinfo is None:
            raise ValueError("Verification observation needs a timezone")
        if self.verification and self.verification.verdict != self.verdict:
            raise ValueError("Bridge cannot change P3 verdict")
        if self.verdict == "verified" and not all(
            (
                self.context,
                self.evidence_id,
                self.evidence_sha256,
                self.query_sha256,
                self.result_sha256,
                self.verification,
                self.verification_sha256,
                self.value,
            )
        ):
            raise ValueError("Verified metric needs persisted P3 proof and confirmed context")
        if self.verdict != "verified" and self.value is not None:
            raise ValueError("Unverified numbers cannot be published")
        return self


class DocumentReference(Contract):
    artifact_id: Digest
    citation: ChunkCitation
    excerpt: str = Field(max_length=4096)


class BusinessCompletion(Contract):
    schema_version: Literal["business-completion-1"] = "business-completion-1"
    status: Literal["completed", "partial", "unavailable", "blocked"]
    required_goals: list[str] = Field(max_length=8)
    verified_goals: list[str] = Field(max_length=8)
    missing_evidence: dict[str, list[str]] = Field(default_factory=dict, max_length=8)
    unconfirmed_claims: list[str] = Field(default_factory=list, max_length=8)
    limited_results_visible: bool = False

    @model_validator(mode="after")
    def coverage_is_explicit(self):
        if len(set(self.required_goals)) != len(self.required_goals) or len(
            set(self.verified_goals)
        ) != len(self.verified_goals):
            raise ValueError("Repeated business goal")
        if not set(self.verified_goals) <= set(self.required_goals):
            raise ValueError("Unknown verified goal")
        if not set(self.missing_evidence) <= set(self.required_goals) or set(
            self.missing_evidence
        ) & set(self.verified_goals):
            raise ValueError("Missing evidence must name uncovered required goals")
        if self.status == "completed" and (
            set(self.required_goals) != set(self.verified_goals)
            or self.missing_evidence
            or self.unconfirmed_claims
        ):
            raise ValueError("Completion requires every business goal without missing claims")
        if self.status == "unavailable" and self.verified_goals:
            raise ValueError("Unavailable cannot claim verified results")
        return self


class ReportClaim(Contract):
    goal_id: str
    kind: Literal["metric", "context", "unavailable"]
    metric: MetricBridge | None = None
    documents: list[DocumentReference] = Field(default_factory=list, max_length=10)
    related_metric_goals: list[str] = Field(default_factory=list, max_length=6)
    codes: list[str] = Field(default_factory=list, max_length=32)
    missing_requirements: list[MissingRequirement] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def kind_matches_payload(self):
        if self.kind == "metric" and (
            not self.metric
            or self.metric.verdict != "verified"
            or self.goal_id != self.metric.request.goal_id
            or self.documents
            or self.codes
            or self.missing_requirements
        ):
            raise ValueError("Metric claim requires matching P3 verified evidence")
        if self.kind == "context" and (
            self.metric
            or not self.documents
            or not self.related_metric_goals
            or self.codes
            or self.missing_requirements
        ):
            raise ValueError("Document context needs explicit citations and related goals")
        if self.kind == "unavailable" and (self.metric or self.documents or not self.codes):
            raise ValueError("Unavailable claims cannot publish facts")
        return self


class ChartPoint(Contract):
    goal_id: str
    metric: MetricBridge

    @model_validator(mode="after")
    def verified_only(self):
        if self.metric.verdict != "verified" or self.goal_id != self.metric.request.goal_id:
            raise ValueError("Chart data must reference a matching verified metric")
        return self


class ChartSpec(Contract):
    kind: Literal["bar"] = "bar"
    unit: str = Field(max_length=16)
    authorization_sha256: Digest
    dataset_scope: DatasetScope
    owner: str = Field(max_length=64)
    rag_scope_sha256: Digest | None = None
    document_refs: list[DocumentReference] = Field(default_factory=list, max_length=10)
    points: list[ChartPoint] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def units_match(self):
        if any(p.metric.value.unit != self.unit for p in self.points):
            raise ValueError("Chart units cannot be mixed or relabeled")
        return self


class CrossSourceReport(Contract):
    schema_version: Literal["cross-source-report-1"] = "cross-source-report-1"
    authorization_sha256: Digest
    authorization_scope: ReportScope
    rag_scope: RagScope | None = None
    execution_status: Literal["succeeded", "unavailable", "failed", "cancelled"]
    business_completion: BusinessCompletion
    claims: list[ReportClaim] = Field(max_length=8)
    charts: list[ChartSpec] = Field(default_factory=list, max_length=6)
    verified_at: datetime
    markdown: str = Field(max_length=200000)

    @model_validator(mode="after")
    def observation_is_dated(self):
        if self.verified_at.tzinfo is None:
            raise ValueError("Report verification observation needs a timezone")
        return self
