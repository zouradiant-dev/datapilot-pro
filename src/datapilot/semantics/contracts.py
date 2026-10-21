"""Strict semantic, metric, evidence and six-layer verification boundaries."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, model_validator

from datapilot.contracts import QueryResult
from datapilot.datasets.contracts import DatasetId, DatasetQueryResult, DatasetTable, Version
from datapilot.ingestion.contracts import DTO, Digest, Name

Entity = Literal["invoices", "subscriptions", "usage_events"]
MetricId = Literal[
    "paid_invoice_revenue",
    "customer_churn",
    "subscription_churn",
    "active_subscriptions",
    "usage",
    "mrr",
]
Role = Literal[
    "record_id",
    "customer_id",
    "amount",
    "invoice_date",
    "payment_status",
    "currency",
    "start_date",
    "end_date",
    "termination_kind",
    "event_date",
    "event_count",
    "feature",
]
DecimalText = Annotated[str, Field(max_length=80, pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")]
Layer = Literal["safety", "shape", "semantics", "recomputation", "references", "coverage"]
LAYERS = ("safety", "shape", "semantics", "recomputation", "references", "coverage")
COMPUTATION_VERSION = "saas-metrics-1"


class MissingRequirement(DTO):
    code: Name
    message: str = Field(min_length=1, max_length=256)
    fields: list[Annotated[str, Field(max_length=128)]] = Field(default_factory=list, max_length=20)


class EntityMapping(DTO):
    entity: Entity
    table_id: Name
    fields: dict[Role, Name] = Field(max_length=16)
    grain: list[Name] = Field(min_length=1, max_length=3)
    coverage_start: date | None = None
    coverage_end_exclusive: date | None = None
    history_complete: bool = False
    subscription_identity: Literal["contract", "plan_period", "unknown"] = "unknown"
    amount_storage: Literal["minor", "major"] | None = None
    currency_constant: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    timezone: Literal["UTC"] = "UTC"
    null_policy: Literal["reject_required"] = "reject_required"

    @model_validator(mode="after")
    def coherent_mapping(self):
        if len(set(self.fields.values())) != len(self.fields) or len(set(self.grain)) != len(
            self.grain
        ):
            raise ValueError("Repeated semantic fields or grain columns")
        if (self.coverage_start is None) != (self.coverage_end_exclusive is None):
            raise ValueError("Coverage needs both boundaries")
        if self.coverage_start and self.coverage_start >= self.coverage_end_exclusive:
            raise ValueError("Invalid observation coverage")
        if self.currency_constant and "currency" in self.fields:
            raise ValueError("Choose a currency column or an explicitly confirmed constant")
        return self


class SemanticDraft(DTO):
    dataset_id: DatasetId
    dataset_version: Version
    domain_version: Literal["saas-1"] = "saas-1"
    entities: list[EntityMapping] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_entities(self):
        if len({e.entity for e in self.entities}) != len(self.entities):
            raise ValueError("Duplicate entity mappings")
        return self


class SemanticVersion(DTO):
    dataset_id: DatasetId
    dataset_version: Version
    semantic_version: Version
    source_sha256: Digest
    definition_sha256: Digest
    state: Literal["confirmed"] = "confirmed"
    definition: SemanticDraft


class MetricDraft(DTO):
    dataset_id: DatasetId
    dataset_version: Version
    semantic_version: Version
    metric_id: MetricId
    policy: Literal["saas_metrics_v1"] = "saas_metrics_v1"
    currency: str = Field(default="CNY", pattern=r"^[A-Z]{3}$")
    paid_values: list[Annotated[str, Field(min_length=1, max_length=32)]] = Field(
        default_factory=lambda: ["paid"], min_length=1, max_length=8
    )
    churn_values: list[Annotated[str, Field(min_length=1, max_length=32)]] = Field(
        default_factory=lambda: ["churned"], min_length=1, max_length=8
    )
    non_churn_end_values: list[Annotated[str, Field(min_length=1, max_length=32)]] = Field(
        default_factory=lambda: ["downgraded", "plan_change"], max_length=8
    )
    feature: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def explicit_policies(self):
        if set(self.churn_values) & set(self.non_churn_end_values):
            raise ValueError("Churn and non-churn events must be disjoint")
        if self.feature is not None and self.metric_id != "usage":
            raise ValueError("Feature filter only applies to usage")
        for values in (self.paid_values, self.churn_values, self.non_churn_end_values):
            if len(values) != len(set(values)):
                raise ValueError("Duplicate policy values")
        return self


class MetricVersion(DTO):
    dataset_id: DatasetId
    dataset_version: Version
    metric_id: MetricId
    metric_version: Version
    semantic_version: Version
    definition_sha256: Digest
    semantic_sha256: Digest
    state: Literal["confirmed"] = "confirmed"
    definition: MetricDraft


class MetricWindow(DTO):
    start: date
    end_exclusive: date

    @model_validator(mode="after")
    def ordered(self):
        if not 0 < (self.end_exclusive - self.start).days <= 3660:
            raise ValueError("Use a nonempty half-open window of at most ten years")
        return self


class MetricRequest(DTO):
    goal_id: Name
    dataset_id: DatasetId
    dataset_version: Version
    semantic_version: Version
    metric_id: MetricId
    metric_version: Version
    window: MetricWindow | None = None
    as_of: date | None = None
    intent: Literal["measure", "explain_cause"] = "measure"

    @model_validator(mode="after")
    def temporal_shape(self):
        if self.metric_id == "active_subscriptions":
            if self.as_of is None or self.window is not None:
                raise ValueError("Active subscriptions need an explicit as_of date")
        elif self.window is None or self.as_of is not None:
            raise ValueError("This metric needs a half-open date window")
        return self


class MetricContext(DTO):
    dataset_id: DatasetId
    dataset_version: Version
    source_sha256: Digest
    semantic_version: Version
    semantic_sha256: Digest
    metric_id: MetricId
    metric_version: Version
    metric_sha256: Digest
    definition: MetricDraft
    entity: EntityMapping | None = None
    table: DatasetTable | None = None
    missing: list[MissingRequirement] = Field(default_factory=list, max_length=32)
    context_sha256: Digest


class MetricValue(DTO):
    value: DecimalText | None
    unit: str = Field(min_length=1, max_length=16)
    numerator: int | None = Field(default=None, ge=0, le=100_000)
    denominator: int | None = Field(default=None, ge=0, le=100_000)
    window_days: int | None = Field(default=None, ge=1, le=3660)


class MetricProof(DTO):
    context_sha256: Digest
    request_sha256: Digest
    computation_version: Literal["saas-metrics-1"] = COMPUTATION_VERSION
    method: Literal["python_raw_projection_v1"] = "python_raw_projection_v1"
    status: Literal["computed", "unavailable"]
    value: MetricValue | None = None
    missing: list[MissingRequirement] = Field(default_factory=list, max_length=32)
    source_rows: int = Field(ge=0, le=20_000)
    page_hashes: list[Digest] = Field(max_length=256)

    @model_validator(mode="after")
    def consistent(self):
        if self.status == "computed" and (self.value is None or self.missing):
            raise ValueError("Computed proof requires a value and no missing requirements")
        if self.status == "unavailable" and (self.value is not None or not self.missing):
            raise ValueError("Unavailable proof needs explicit reasons without a value")
        return self


class MetricExecution(DTO):
    request: MetricRequest
    context: MetricContext
    candidate_sql: str | None = Field(default=None, max_length=12000)
    primary: DatasetQueryResult | None = None
    proof: MetricProof | None = None
    missing: list[MissingRequirement] = Field(default_factory=list, max_length=32)


class Evidence(DTO):
    evidence_id: DatasetId
    dataset_id: DatasetId
    dataset_version: Version
    source_sha256: Digest
    semantic_version: Version
    semantic_sha256: Digest
    metric_id: MetricId
    metric_version: Version
    metric_sha256: Digest
    computation_version: Literal["saas-metrics-1"] = COMPUTATION_VERSION
    request: MetricRequest
    context_sha256: Digest
    query_sql: str | None = Field(default=None, max_length=12000)
    query_sha256: Digest | None = None
    result: QueryResult | None = None
    result_sha256: Digest | None = None
    proof: MetricProof | None = None
    value: MetricValue | None = None
    missing: list[MissingRequirement] = Field(default_factory=list, max_length=32)


class LayerCheck(DTO):
    layer: Layer
    status: Literal["passed", "failed", "not_applicable"]
    codes: list[Name] = Field(default_factory=list, max_length=16)


class VerificationRecord(DTO):
    verification_id: DatasetId
    evidence_id: DatasetId
    dataset_id: DatasetId
    dataset_version: Version
    request_sha256: Digest
    rule_version: Literal["six-layers-1"] = "six-layers-1"
    checks: list[LayerCheck] = Field(min_length=6, max_length=6)
    verdict: Literal["verified", "unavailable", "rejected"]

    @model_validator(mode="after")
    def derived_verdict(self):
        if tuple(c.layer for c in self.checks) != LAYERS:
            raise ValueError("All six verification layers must appear in order")
        statuses = {c.status for c in self.checks}
        expected = (
            "rejected"
            if "failed" in statuses
            else "unavailable"
            if "not_applicable" in statuses
            else "verified"
        )
        if self.verdict != expected:
            raise ValueError("Verification verdict must be derived from deterministic checks")
        return self


class ReportClaim(DTO):
    goal_id: Name
    kind: Literal["metric", "unavailable", "causal"]
    evidence_id: DatasetId
    verification_id: DatasetId
    value: MetricValue | None = None


class MetricOutcome(DTO):
    request: MetricRequest
    evidence_id: DatasetId
    verification: VerificationRecord
    value: MetricValue | None = None
    missing: list[MissingRequirement] = Field(default_factory=list, max_length=32)


class MetricReport(DTO):
    execution_mode: Literal["deterministic", "model_assisted"] = "deterministic"
    outcomes: list[MetricOutcome] = Field(min_length=1, max_length=10)
    claims: list[ReportClaim] = Field(min_length=1, max_length=10)
    markdown: str = Field(max_length=200_000)
