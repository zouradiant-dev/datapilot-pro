"""Versioned public DTOs. No owner, SQL, DSN or arbitrary Artifact payload parameters."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, field_validator, model_serializer, model_validator

from datapilot.datasets.contracts import DatasetColumn, DatasetId, Version
from datapilot.ingestion.contracts import (
    DTO,
    ConfirmationOverrides,
    Digest,
    Issue,
    LogicalType,
    ParsedColumn,
    ParseOptions,
    RelationCandidate,
    SchemaConfirmation,
    UploadFileInfo,
)
from datapilot.orchestration.contracts import Usage
from datapilot.rag.contracts import ChunkCitation
from datapilot.reporting.contracts import BusinessCompletion
from datapilot.semantics.contracts import (
    MetricDraft,
    MetricRequest,
    MetricValue,
    MetricVersion,
    SemanticDraft,
    SemanticVersion,
)

TaskStatus = Literal[
    "pending",
    "running",
    "paused",
    "awaiting_review",
    "partial",
    "unavailable",
    "blocked",
    "failed",
    "completed",
    "cancelled",
]
IdempotencyKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")]


def database_text(value: str) -> str:
    """Public persisted text must be representable by PostgreSQL JSONB."""
    if "\x00" in value:
        raise ValueError("NUL is not supported")
    value.encode("utf-8", errors="strict")
    return value


DatabaseText = Annotated[str, AfterValidator(database_text)]


class ErrorInfo(DTO):
    code: str = Field(max_length=64)
    message: str = Field(max_length=256)
    retryable: bool = False
    manual_action_required: bool = False


class ErrorResponse(DTO):
    schema_version: Literal["api-v1"] = "api-v1"
    error: ErrorInfo


class UploadOptions(DTO):
    options: ParseOptions = Field(default_factory=ParseOptions)


class SchemaReview(DTO):
    proposal_sha256: Digest
    reviewed: bool
    overrides: ConfirmationOverrides = Field(default_factory=ConfirmationOverrides)


class ImportUpload(DTO):
    confirmation_sha256: Digest
    name: str = Field(min_length=1, max_length=110)
    dataset_id: DatasetId | None = None


class SemanticReview(DTO):
    draft: SemanticDraft
    reviewed: bool

    @field_validator("draft", mode="before")
    @classmethod
    def json_dates(cls, value):
        import json

        return (
            SemanticDraft.model_validate_json(json.dumps(value))
            if isinstance(value, dict)
            else value
        )


class MetricReview(DTO):
    draft: MetricDraft
    reviewed: bool


class FactRequirement(DTO):
    """A fact question plus an optional exact quotation for host review.

    ``quotation`` is only a review input. The host resolves and pins the
    immutable citation; it is never accepted as a client-provided proof.
    """

    fact_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    description: DatabaseText = Field(min_length=1, max_length=256)
    quotation: str | None = Field(default=None, min_length=1, max_length=256)

    @model_serializer(mode="wrap")
    def legacy_projection(self, handler):
        value = handler(self)
        if self.quotation is None:
            value.pop("quotation", None)
        return value


class DocumentQuery(DTO):
    question: DatabaseText = Field(min_length=1, max_length=512)
    metric_goals: list[str] = Field(max_length=6)
    corpus_ids: list[DatasetId] = Field(min_length=1, max_length=8)
    purpose: Literal["locate", "summary", "facts", "conclusion"] | None = None
    required_facts: list[FactRequirement] = Field(default_factory=list, max_length=8)
    independent_facts: bool = False

    @model_validator(mode="after")
    def requirements(self):
        if self.purpose == "facts" and not self.required_facts:
            raise ValueError("State the facts to verify; user text is not proof")
        if self.required_facts and self.purpose not in {"facts", "conclusion"}:
            raise ValueError("Facts require an explicit fact/conclusion purpose")
        if self.independent_facts and (self.purpose != "facts" or not self.required_facts):
            raise ValueError("Independent facts require a facts purpose and facts")
        if len({f.fact_id for f in self.required_facts}) != len(self.required_facts):
            raise ValueError("Duplicate fact requirement")
        return self

    @model_serializer(mode="wrap")
    def legacy_projection(self, handler):
        value = handler(self)
        if self.purpose is None:
            value.pop("purpose", None)
        if not self.required_facts:
            value.pop("required_facts", None)
        if not self.independent_facts:
            value.pop("independent_facts", None)
        return value


class CreateTask(DTO):
    """SQL: confirmed metrics; combined: associated documents; documents-only: no
    metrics, nonempty authorized corpora, unchanged full question and mandatory review.
    Cross-field conditions are enforced by the host, including after candidate replay.
    """

    question: DatabaseText = Field(min_length=1, max_length=8000)
    metrics: list[MetricRequest] = Field(max_length=6)
    documents: DocumentQuery | None = None
    require_review: bool = True
    causal_requested: bool = False

    @model_validator(mode="after")
    def actual_goals(self):
        goals = [m.goal_id for m in self.metrics]
        if not goals and self.documents is None:
            raise ValueError("A task requires confirmed metrics or an authorized document goal")
        if not goals and not self.require_review:
            raise ValueError("Document-only tasks require host approval")
        if len(set(goals)) != len(goals):
            raise ValueError("Repeated metric goal")
        if self.documents:
            refs = self.documents.metric_goals
            if len(set(refs)) != len(refs) or not set(refs) <= set(goals):
                raise ValueError("Document associations must name actual metric goals")
            if self.metrics and not refs and not self.documents.independent_facts:
                raise ValueError("Combined tasks require explicit metric associations")
            if len(set(self.documents.corpus_ids)) != len(self.documents.corpus_ids):
                raise ValueError("Repeated corpus")
            if not self.metrics and self.documents.question != self.question:
                raise ValueError("Document-only task must preserve the entire original question")
        return self

    @field_validator("metrics", mode="before")
    @classmethod
    def json_dates(cls, value):
        import json

        return (
            [
                MetricRequest.model_validate_json(json.dumps(v)) if isinstance(v, dict) else v
                for v in value
            ]
            if isinstance(value, list)
            else value
        )


class TaskAction(DTO):
    confirmed: bool = False


class TaskProgress(DTO):
    task_id: str = Field(max_length=64)
    worker: Literal["sql", "rag", "analysis", "report"]
    status: str = Field(max_length=32)
    plan_version: int = Field(ge=1)


class TaskView(DTO):
    schema_version: Literal["api-v1"] = "api-v1"
    run_id: DatasetId
    status: TaskStatus
    execution_status: str | None = Field(default=None, max_length=32)
    business_completion: BusinessCompletion | None = None
    plan_version: int | None = Field(default=None, ge=1)
    steps: int = Field(default=0, ge=0)
    tasks: list[TaskProgress] = Field(default_factory=list, max_length=12)
    usage: Usage | None = None
    error: ErrorInfo | None = None
    expires_at: datetime
    report_available: bool = False
    question: str = Field(default="", max_length=8000)
    requested_metrics: list[MetricRequest] = Field(default_factory=list, max_length=6)


class MetricFact(DTO):
    goal_id: str = Field(max_length=63)
    request: MetricRequest
    value: MetricValue
    evidence_id: DatasetId
    verification_id: DatasetId
    source_sha256: Digest
    semantic_sha256: Digest
    metric_sha256: Digest
    evidence_sha256: Digest
    verification_sha256: Digest
    query_sha256: Digest
    result_sha256: Digest
    verified_at: datetime
    filters: dict[str, str | list[str] | None] = Field(max_length=8)


class CitationView(DTO):
    artifact_id: Digest
    citation: ChunkCitation
    quotation: str = Field(default="", max_length=4096)

    @model_serializer(mode="wrap")
    def legacy_projection(self, handler):
        data = handler(self)
        if not self.quotation:
            data.pop("quotation", None)
        return data


class PublicColumnProfile(DTO):
    column: ParsedColumn
    suggested_type: LogicalType
    sample_type: LogicalType
    confidence: float
    requires_confirmation: bool
    null_count: int
    distinct_count: int
    duplicate_count: int
    examples_truncated: bool
    precision: int | None
    scale: int | None
    outlier_count: int
    issues: list[Issue] = Field(max_length=32)


class PublicTablePreview(DTO):
    table_id: str
    source_name: str
    row_count: int
    header_row: int | None
    columns: list[PublicColumnProfile] = Field(max_length=100)
    preview_truncated: bool
    duplicate_rows: int
    skipped_blank_rows: int
    candidate_primary_keys: list[str] = Field(max_length=10)
    issues: list[Issue] = Field(max_length=2000)


class UploadView(DTO):
    schema_version: Literal["api-v1"] = "api-v1"
    upload_id: DatasetId
    proposal_sha256: Digest
    upload: UploadFileInfo
    tables: list[PublicTablePreview] = Field(max_length=32)
    candidate_relations: list[RelationCandidate] = Field(max_length=50)
    confirmation: SchemaConfirmation | None
    row_values_redacted: Literal[True] = True


class PublicDatasetTable(DTO):
    table_id: str
    source_name: str
    row_count: int
    columns: list[DatasetColumn] = Field(max_length=100)
    primary_key: list[str] = Field(max_length=10)


class PublicDatasetSchema(DTO):
    dataset_id: DatasetId
    version: Version
    name: str
    source_sha256: Digest
    row_count: int
    tables: list[PublicDatasetTable] = Field(max_length=32)


class DatasetView(DTO):
    dataset_schema: PublicDatasetSchema = Field(alias="schema")
    semantics: list[SemanticVersion] = Field(max_length=100)
    metrics: list[MetricVersion] = Field(max_length=100)

    @field_validator("semantics", mode="before")
    @classmethod
    def json_dates(cls, value):
        import json

        return [
            SemanticVersion.model_validate_json(json.dumps(v)) if isinstance(v, dict) else v
            for v in value
        ]


class DatasetViews(DTO):
    datasets: list[DatasetView] = Field(max_length=100)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=100)
    next_offset: int | None = Field(default=None, ge=0)


class SessionView(DTO):
    schema_version: Literal["api-v1"] = "api-v1"
    csrf_token: str = Field(max_length=128)
    deployment: Literal["trusted-local-single-user"]


class HealthView(DTO):
    status: Literal["ready"]
    mode: Literal["live", "fake"]
    durable: Literal[True]
    telemetry: str
    production_multi_tenant: Literal[False]


class DocumentIngested(DTO):
    corpus_id: DatasetId
    index_version: Digest
    reused: bool
    source_sha256: Digest
    embedding_fixture: bool
    usage: dict | None


class CorpusView(DTO):
    corpus_id: DatasetId
    index_version: Digest
    dataset_id: DatasetId
    dataset_version: Version


class CorporaView(DTO):
    corpora: list[CorpusView] = Field(max_length=100)


class TaskIDs(DTO):
    run_ids: list[DatasetId] = Field(max_length=30)


class Observation(DTO):
    run_id: str = Field(max_length=64)
    plan_version: int | None = None
    task_id: str | None = Field(default=None, max_length=64)
    tool_call_id: str | None = Field(default=None, max_length=128)
    model_call: str | None = Field(default=None, max_length=160)
    artifact_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    p3_evidence_id: str | None = Field(default=None, max_length=36)
    p3_verification_id: str | None = Field(default=None, max_length=36)
    provider_id: str | None = Field(default=None, max_length=32)
    model_id: str | None = Field(default=None, max_length=128)
    endpoint_alias: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,32}$")
    call_attempt_id: str | None = Field(default=None, max_length=160)
    error_category: str | None = Field(default=None, max_length=64)
    requested_route: str | None = Field(default=None, max_length=32)
    observed_route: str | None = Field(default=None, max_length=32)
    latency_ms: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cache_read_tokens: int | None = Field(default=None, ge=0)
    business_completion: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)


class TraceView(DTO):
    schema_version: Literal["api-v1"] = "api-v1"
    run_id: DatasetId
    usage_source: Literal["provider", "mock"]
    calls: list[Observation] = Field(max_length=352)
    routes: list[dict] = Field(max_length=2048)
    journal_replay_is_provider_cache: Literal[False]
    cost: dict
    remote_telemetry: Literal[False]
    local_export_succeeded: bool | None


class ReportView(DTO):
    schema_version: Literal["api-v1"] = "api-v1"
    run_id: DatasetId
    authorization_sha256: Digest
    execution_status: str
    business_completion: BusinessCompletion
    facts: list[MetricFact] = Field(max_length=6)
    citations: list[CitationView] = Field(max_length=10)
    charts: list[dict] = Field(max_length=6)
    missing_requirements: list[dict] = Field(max_length=64)
    markdown: str = Field(max_length=50000)


class Acknowledgement(DTO):
    schema_version: Literal["api-v1"] = "api-v1"
    run_id: DatasetId
    accepted: bool = True
