"""Versioned host authorization, P3 bridge and auditable report projections."""

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import Field, model_serializer, model_validator

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


class DocumentFact(Contract):
    """Host-confirmed interpretation of a literal source quote, never a Worker assertion.

    No proof means unverified. Confirmation comes from the trusted host, not a model tool;
    the report independently checks the immutable citation and exact quoted text.
    """

    fact_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    description: str = Field(min_length=1, max_length=256)
    citation: ChunkCitation | None = None
    quotation: str | None = Field(default=None, min_length=1, max_length=256)
    confirmation_ref: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def explicit_host_proof(self):
        fields = (self.citation, self.quotation, self.confirmation_ref)
        if any(v is not None for v in fields) and not all(v is not None for v in fields):
            raise ValueError("A fact proof needs a host confirmation, immutable pin and quote")
        if self.quotation is not None and (
            not self.quotation.strip() or not self.confirmation_ref.strip()
        ):
            raise ValueError("Blank confirmation or quote is not proof")
        return self


class DocumentGoal(Contract):
    goal_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    question: str = Field(min_length=1, max_length=512)
    metric_goals: list[str] = Field(max_length=6)
    purpose: Literal["locate", "summary", "facts", "conclusion"] | None = None
    required_facts: list[DocumentFact] = Field(default_factory=list, max_length=8)
    independent_facts: bool = False
    evidence_only: bool = False

    @model_validator(mode="after")
    def explicit_business_requirements(self):
        if self.purpose == "facts" and not self.required_facts:
            raise ValueError("Fact extraction requires explicit host fact requirements")
        if self.required_facts and self.purpose not in {"facts", "conclusion"}:
            raise ValueError("Facts cannot be silently added to an unconfirmed/summary goal")
        if self.independent_facts and (self.purpose != "facts" or not self.required_facts):
            raise ValueError("Independent facts require a facts purpose and facts")
        if self.evidence_only and not self.independent_facts:
            raise ValueError("Evidence-only context requires independent reviewed literal facts")
        if len({f.fact_id for f in self.required_facts}) != len(self.required_facts):
            raise ValueError("Required fact identities must be unique")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_projection(self, handler):
        value = handler(self)
        if self.purpose is None:
            value.pop("purpose", None)
        if not self.required_facts:
            value.pop("required_facts", None)
        if not self.independent_facts:
            value.pop("independent_facts", None)
        if not self.evidence_only:
            value.pop("evidence_only", None)
        return value


class CitationSource(Contract):
    """Source classification pin, never an authorization grant or a chunk counter."""

    corpus_id: DatasetId
    index_version: Digest
    source_id: Digest
    document_id: Digest
    version: Digest
    source_sha256: Digest


def source_identity(source):
    return tuple(getattr(source, name) for name in CitationSource.model_fields)


class CitationPolicy(Contract):
    schema_version: Literal["required-supplement-v1"] = "required-supplement-v1"
    goal_sha256: Digest
    required_sources: list[CitationSource] = Field(min_length=1, max_length=8)
    # Reviewed literal document facts only; no numeric/causal verification authority.
    supplementary_claims: list[DocumentFact] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def explicit_claims(self):
        if len({source_identity(s) for s in self.required_sources}) != len(self.required_sources):
            raise ValueError("Required sources must be distinct, not multiple chunks")
        if len({f.fact_id for f in self.supplementary_claims}) != len(self.supplementary_claims):
            raise ValueError("Supplementary claim IDs must be distinct")
        if any(f.citation is None for f in self.supplementary_claims):
            raise ValueError("Supplementary claims require reviewed immutable quote proofs")
        return self


class GoalScopeAttestation(Contract):
    """Trusted host record of full-goal equivalence to a finite contract, not a signature.

    A fact confirmation or execute approval alone must never create this record.
    The caller must already have reviewed the complete original goal and prerequisites.
    """

    basis: Literal["host-reviewed-finite-contract-v1"] = "host-reviewed-finite-contract-v1"
    confirmation_ref: str = Field(min_length=1, max_length=128, pattern=r"\S")
    contract_sha256: Digest
    rag_scope_sha256: Digest


class UnboundMetricGoal(Contract):
    """A real host-reviewed request with no executable definition or P3 evidence path."""

    goal_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    description: str = Field(min_length=1, max_length=256)
    reason: Literal["definition_missing", "p3_evidence_required"]


class ReportScope(Contract):
    schema_version: Literal["p6b-scope-1"] = "p6b-scope-1"
    owner: str = Field(default="local-user", min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=8000)
    datasets: DatasetScope
    metrics: list[MetricRequest] = Field(max_length=6)
    document_goal: DocumentGoal | None = None
    causal_requested: bool = False
    # Trusted host only; included in manifest/report hashes when explicitly enabled.
    partial_evidence_policy: Literal["legacy", "partial-facts-v1"] = "legacy"
    citation_policy: CitationPolicy | None = None
    rag_query_policy: Literal["legacy", "original-first-v1"] = "legacy"
    goal_scope_attestation: GoalScopeAttestation | None = None
    unbound_metric_goals: list[UnboundMetricGoal] = Field(default_factory=list, max_length=6)

    @model_serializer(mode="wrap")
    def preserve_legacy_policy(self, handler):
        value = handler(self)
        if self.partial_evidence_policy == "legacy":
            value.pop("partial_evidence_policy", None)
        if self.citation_policy is None:
            value.pop("citation_policy", None)
        if self.rag_query_policy == "legacy":
            value.pop("rag_query_policy", None)
        if self.goal_scope_attestation is None:
            value.pop("goal_scope_attestation", None)
        if not self.unbound_metric_goals:
            value.pop("unbound_metric_goals", None)
        return value

    @model_validator(mode="after")
    def scope_is_explicit(self):
        import re

        goals = [m.goal_id for m in self.metrics]
        if not goals and self.document_goal is None:
            raise ValueError("A report must have a real metric or document goal")
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
            if goals and not doc.metric_goals:
                raise ValueError("Combined reports require metric associations")
            if not goals and doc.question != self.question:
                raise ValueError("Document-only scope must preserve the original question")
            if doc.evidence_only and not goals:
                raise ValueError("Evidence-only context requires a primary metric goal")
        required = goals + ([self.document_goal.goal_id] if self.document_goal else [])
        required += [goal.goal_id for goal in self.unbound_metric_goals]
        if len(required) > 8 or len(set(required)) != len(required) or "report" in required:
            raise ValueError("Report goals must be distinct and fit the eight-goal limit")
        if policy := self.citation_policy:
            if (
                self.document_goal is None
                or policy.goal_sha256 != hashlib.sha256(self.question.encode("utf-8")).hexdigest()
            ):
                raise ValueError("Citation policy must bind the original host report goal")
            required = {source_identity(s) for s in policy.required_sources}
            if any(
                f.citation and source_identity(f.citation) not in required
                for f in self.document_goal.required_facts
            ):
                raise ValueError("Required facts cannot be relabelled as supplementary")
            if {f.fact_id for f in self.document_goal.required_facts} & {
                f.fact_id for f in policy.supplementary_claims
            }:
                raise ValueError("Required and supplementary claim IDs must not overlap")
        if self.rag_query_policy == "original-first-v1" and (
            self.document_goal is None or not self.document_goal.question.strip()
        ):
            raise ValueError("Original-first policy requires a nonblank host document goal")
        return self


def finite_contract_hash(scope: ReportScope):
    from datapilot.ingestion.common import digest

    return digest(scope.model_dump(mode="json", exclude={"goal_scope_attestation"}))


def confirm_finite_scope(scope: ReportScope, rag_scope: RagScope, *, confirmation_ref: str):
    """Host-only confirmation, deliberately not called by parsing, tools or execute approval.

    This records an existing trusted review; it does not infer intent equivalence.
    Reuse is safe only while both exact contracts remain unchanged.
    """
    from datapilot.ingestion.common import digest

    scope = ReportScope.model_validate_json(scope.model_dump_json())
    rag_scope = RagScope.model_validate_json(rag_scope.model_dump_json())
    if (
        scope.document_goal is None
        or scope.document_goal.purpose is None
        or scope.owner != rag_scope.owner
        or scope.datasets != rag_scope.datasets
        or not rag_scope.corpora
    ):
        raise ValueError("A reviewed finite document contract needs its exact authorized scope")
    scope.goal_scope_attestation = GoalScopeAttestation(
        confirmation_ref=confirmation_ref,
        contract_sha256=finite_contract_hash(scope),
        rag_scope_sha256=digest(rag_scope),
    )
    return scope


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
    satisfied_evidence_goals: list[str] = Field(default_factory=list, max_length=8)

    @model_serializer(mode="wrap")
    def preserve_legacy_projection(self, handler):
        value = handler(self)
        if not self.satisfied_evidence_goals:
            value.pop("satisfied_evidence_goals", None)
        return value

    @model_validator(mode="after")
    def coverage_is_explicit(self):
        if len(set(self.required_goals)) != len(self.required_goals) or len(
            set(self.verified_goals)
        ) != len(self.verified_goals):
            raise ValueError("Repeated business goal")
        if not set(self.verified_goals) <= set(self.required_goals):
            raise ValueError("Unknown verified goal")
        evidence = set(self.satisfied_evidence_goals)
        if (
            len(evidence) != len(self.satisfied_evidence_goals)
            or not evidence <= set(self.required_goals)
            or evidence & set(self.verified_goals)
        ):
            raise ValueError(
                "Evidence goals must be distinct required goals, separate from results"
            )
        if not set(self.missing_evidence) <= set(self.required_goals) or set(
            self.missing_evidence
        ) & (set(self.verified_goals) | evidence):
            raise ValueError("Missing evidence must name uncovered required goals")
        if self.status == "completed" and (
            set(self.required_goals) != set(self.verified_goals) | evidence
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
    fact_coverage: dict[str, DocumentReference | None] = Field(default_factory=dict, max_length=8)
    supplementary_coverage: dict[str, DocumentReference] = Field(default_factory=dict, max_length=4)

    @model_serializer(mode="wrap")
    def preserve_legacy_projection(self, handler):
        value = handler(self)
        if not self.fact_coverage:
            value.pop("fact_coverage", None)
        if not self.supplementary_coverage:
            value.pop("supplementary_coverage", None)
        return value

    @model_validator(mode="after")
    def kind_matches_payload(self):
        if self.kind != "context" and (self.fact_coverage or self.supplementary_coverage):
            raise ValueError("Document facts cannot become P3 metric/unavailable claims")
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
            or not (self.documents or self.supplementary_coverage)
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
        if not self.authorization_scope.metrics and (
            self.charts or any(c.kind == "metric" for c in self.claims)
        ):
            raise ValueError("Document-only reports cannot publish metric facts or charts")
        if self.authorization_scope.metrics and any(
            c.kind == "context" and not c.related_metric_goals for c in self.claims
        ):
            raise ValueError("Combined context must name its related metric goals")
        scope, completion = self.authorization_scope, self.business_completion
        doc = scope.document_goal
        evidence_goal = {doc.goal_id} if doc and doc.evidence_only else set()
        if not set(completion.satisfied_evidence_goals) <= evidence_goal:
            raise ValueError("Only host-declared evidence goals may satisfy citation obligations")
        if evidence_goal & set(completion.verified_goals):
            raise ValueError("Evidence-only context cannot become a verified business result")
        if completion.satisfied_evidence_goals:
            context = next((c for c in self.claims if c.goal_id == doc.goal_id), None)
            if (
                context is None
                or context.kind != "context"
                or any(context.fact_coverage.get(f.fact_id) is None for f in doc.required_facts)
            ):
                raise ValueError("Satisfied evidence goals need their required literal facts")
            for fact in doc.required_facts:
                support = context.fact_coverage[fact.fact_id]
                observations = {"score", "goal_sha256", "goal_score"}
                if (
                    fact.citation is None
                    or support.citation.model_dump(exclude=observations)
                    != fact.citation.model_dump(exclude=observations)
                    or support.excerpt != fact.quotation
                ):
                    raise ValueError("Evidence satisfaction differs from the host literal proof")
        if scope.unbound_metric_goals or evidence_goal:
            required = {r.goal_id for r in scope.metrics} | ({doc.goal_id} if doc else set())
            required |= {g.goal_id for g in scope.unbound_metric_goals}
            if set(completion.required_goals) != required:
                raise ValueError("Report completion omitted a host-required goal")
            claims = {c.goal_id: c for c in self.claims}
            for goal in scope.unbound_metric_goals:
                claim = claims.get(goal.goal_id)
                if (
                    goal.goal_id in completion.verified_goals
                    or goal.goal_id in completion.satisfied_evidence_goals
                    or goal.reason not in completion.missing_evidence.get(goal.goal_id, [])
                    or claim is None
                    or claim.kind != "unavailable"
                    or goal.reason not in claim.codes
                ):
                    raise ValueError("Unbound metric goals must remain explicitly unavailable")
        return self
