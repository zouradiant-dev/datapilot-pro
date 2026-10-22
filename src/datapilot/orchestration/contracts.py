"""Untrusted plans never carry credentials, capabilities, budgets or executable code."""

from typing import Annotated, Literal

from pydantic import Field, model_serializer, model_validator

from datapilot.contracts import Contract, QueryResult
from datapilot.rag.contracts import ChunkCitation, EmbeddingUsage
from datapilot.reporting.contracts import CrossSourceReport, MetricBridge

TaskId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Worker = Literal["sql", "rag", "analysis", "report"]


class TaskSpec(Contract):
    task_id: TaskId
    worker: Worker
    instruction: str = Field(min_length=1, max_length=8000)
    dependencies: list[TaskId] = Field(default_factory=list, max_length=12)
    operation: Literal["sum", "ratio"] | None = None
    columns: list[Annotated[str, Field(min_length=1, max_length=63)]] = Field(
        default_factory=list, max_length=2
    )

    @model_validator(mode="after")
    def coherent(self):
        if self.task_id in self.dependencies or len(set(self.dependencies)) != len(
            self.dependencies
        ):
            raise ValueError("Self/repeated dependency")
        if self.worker == "analysis":
            if (
                len(self.dependencies) != 1
                or self.operation is None
                or len(self.columns) != (2 if self.operation == "ratio" else 1)
            ):
                raise ValueError("Analysis requires one input and explicit sum/ratio columns")
        elif self.operation is not None or self.columns:
            raise ValueError("Only analysis has numeric operations")
        if self.worker == "report" and not self.dependencies:
            raise ValueError("Report must cite dependencies")
        return self


class Plan(Contract):
    tasks: list[TaskSpec] = Field(default_factory=list, max_length=12)
    unsupported: bool = False

    @model_validator(mode="after")
    def valid_dag(self):
        if self.unsupported == bool(self.tasks):
            raise ValueError("Use tasks or an explicit unsupported answer")
        tasks = {t.task_id: t for t in self.tasks}
        if len(tasks) != len(self.tasks):
            raise ValueError("Duplicate task ID")
        visiting, visited = set(), set()

        def visit(key):
            if key not in tasks or key in visiting:
                raise ValueError("Missing dependency or cyclic DAG")
            if key in visited:
                return
            visiting.add(key)
            for parent in tasks[key].dependencies:
                visit(parent)
            visiting.remove(key)
            visited.add(key)

        for key in tasks:
            visit(key)
        return self


class BudgetLimits(Contract):
    calls: int = Field(default=4, ge=1, le=20)
    tokens: int = Field(default=18000, ge=100, le=100000)


class Usage(Contract):
    calls: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    reported_tokens: int = Field(default=0, ge=0)
    usage_complete: bool = True


class EvidenceRef(Contract):
    artifact_id: Digest
    kind: Literal["query", "documents", "analysis", "report", "schema", "context", "metric"]
    sha256: Digest


class ExecutionError(Contract):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=256)
    retryable: bool = False
    category: Literal[
        "permission",
        "input",
        "plan",
        "budget",
        "cancelled",
        "model",
        "tool",
        "verification",
        "internal",
    ]


class TaskEnvelope(Contract):
    run_id: str = Field(min_length=1, max_length=64)
    plan_version: int = Field(ge=1, le=10)
    task: TaskSpec
    # All fields below are filled by trusted host, never accepted from Planner JSON.
    allowed_tools: list[str] = Field(max_length=4)
    input_refs: list[EvidenceRef] = Field(default_factory=list, max_length=48)
    budget: BudgetLimits
    parent_id: str = Field(max_length=64)
    dependency_statuses: (
        dict[TaskId, Literal["succeeded", "failed", "unavailable", "cancelled", "blocked"]] | None
    ) = Field(default=None, max_length=12)

    @model_serializer(mode="wrap")
    def legacy_projection(self, handler):
        data = handler(self)
        if self.dependency_statuses is None:
            data.pop("dependency_statuses", None)
        return data


class TaskResult(Contract):
    run_id: str
    task_id: TaskId
    plan_version: int = Field(ge=1, le=10)
    worker: Worker
    status: Literal["succeeded", "failed", "unavailable", "cancelled", "blocked"]
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=48)
    error: ExecutionError | None = None
    usage: Usage = Field(default_factory=Usage)
    attempts: int = Field(default=0, ge=0, le=4)
    reused_from: str | None = None
    rag_completion: "RagCompletionReceipt | None" = None

    @model_validator(mode="after")
    def terminal(self):
        if self.status == "succeeded" and (not self.evidence_refs or self.error):
            raise ValueError("Success requires evidence without error")
        if self.status != "succeeded" and self.error is None:
            raise ValueError("Non-success needs an explicit reason")
        return self


class VerificationResult(Contract):
    task_id: TaskId
    plan_version: int
    status: Literal["passed", "failed", "unavailable"]
    checks: list[Literal["identity", "capability", "evidence", "shape", "dependencies"]]
    error: ExecutionError | None = None

    @model_validator(mode="after")
    def complete_checks(self):
        if self.checks != ["identity", "capability", "evidence", "shape", "dependencies"]:
            raise ValueError("All orchestration verification checks must appear in order")
        if (self.status == "passed") != (self.error is None):
            raise ValueError("Verification status must agree with its error")
        return self


class Document(Contract):
    document_id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=256)
    version: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=4096)
    sha256: Digest
    citation: ChunkCitation | None = None


class SearchResult(Contract):
    documents: list[Document] = Field(max_length=5)
    fixture: bool = False
    requested_top_k: int | None = Field(default=None, ge=1, le=5)
    retriever_version: str | None = Field(default=None, max_length=64)
    unavailable_reason: Literal["no_matches", "no_authorized_documents"] | None = None
    embedding_usage: EmbeddingUsage | None = None


class Artifact(Contract):
    run_id: str
    task_id: TaskId
    plan_version: int
    kind: Literal["query", "documents", "analysis", "report", "schema", "context", "metric"]
    source: str = Field(max_length=256)
    sql: str | None = Field(default=None, max_length=12000)
    query: QueryResult | None = None
    documents: SearchResult | None = None
    metric: MetricBridge | None = None
    report: CrossSourceReport | None = None
    values: dict[str, str] = Field(default_factory=dict, max_length=4)
    parents: list[EvidenceRef] = Field(default_factory=list, max_length=48)

    @model_serializer(mode="wrap")
    def preserve_legacy_hash(self, handler):
        value = handler(self)
        for name in ("metric", "report"):
            if getattr(self, name) is None:
                value.pop(name, None)
        return value

    @model_validator(mode="after")
    def payload_matches_kind(self):
        if (self.kind == "query") != (self.query is not None) or (
            (self.kind == "documents") != (self.documents is not None)
        ):
            raise ValueError("Artifact payload must match its declared kind")
        if self.kind == "schema" and set(self.values) != {"schema"}:
            raise ValueError("Schema artifacts require complete schema text")
        if self.kind == "context" and set(self.values) != {"messages"}:
            raise ValueError("Context artifacts require the complete original transcript")
        if (self.kind == "metric") != (self.metric is not None):
            raise ValueError("Metric artifacts need an explicit P3 bridge")
        if self.report is not None and self.kind != "report":
            raise ValueError("Report payload belongs only to a report artifact")
        return self


class FinalDecision(Contract):
    artifact_ids: list[Digest] = Field(min_length=1, max_length=8)
    outcome: Literal["complete", "unavailable"] = "complete"


class RagSubmission(Contract):
    artifact_ids: list[Digest] = Field(
        min_length=1,
        max_length=8,
        description=(
            "Actual artifact_refs IDs obtained by this worker, not document/chunk IDs. "
            "No duplicates or invented/sibling IDs."
        ),
    )
    outcome: Literal["complete", "unavailable", "insufficient"] = Field(
        description=(
            "complete only for verified retrieval requirements; "
            "unavailable for empty retrieval; insufficient for inadequate passages."
        ),
    )


class RagCompletionReceipt(Contract):
    protocol: Literal["rag-submit-v1"] = "rag-submit-v1"
    call_id: str = Field(min_length=1, max_length=128)
    submission: RagSubmission
    verdict: Literal["literal_locator", "semantic_retrieval", "empty", "insufficient"]
    goal_sha256: Digest | None = None
    model_response_sha256: Digest
    relevant_chunk_ids: list[str] = Field(default_factory=list, max_length=40)
    business_conclusions_verified: Literal[False] = False


TaskResult.model_rebuild()


class ContextUsage(Contract):
    messages: int = Field(ge=0)
    message_chars: int = Field(ge=0)
    tool_schema_chars: int = Field(ge=0)
    input_bytes: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    output_reserved_tokens: int = Field(ge=0)
    tool_result_chars: int = Field(ge=0)
    estimation: Literal["utf8_bytes_plus_128"] = "utf8_bytes_plus_128"


class CompletionDecision(Contract):
    status: Literal["completed", "incomplete", "blocked"]
    # This prototype checks the required task DAG, not general NL goal equivalence.
    scope: Literal["required_task_contracts"] = "required_task_contracts"
    required_tasks: list[TaskId] = Field(default_factory=list, max_length=12)
    verified_tasks: list[TaskId] = Field(default_factory=list, max_length=12)
    reason_codes: list[str] = Field(default_factory=list, max_length=32)
    business_metrics_required: bool = False
    business_evidence_verified: bool = False

    @model_serializer(mode="wrap")
    def legacy_projection(self, handler):
        data = handler(self)
        if not self.business_evidence_verified:
            data.pop("business_evidence_verified", None)
        return data

    @model_validator(mode="after")
    def derived_completion(self):
        if (self.status == "completed") != (not self.reason_codes):
            raise ValueError("Completion requires all checks without missing requirements")
        if self.status == "completed" and (
            not self.required_tasks
            or set(self.required_tasks) != set(self.verified_tasks)
            or (self.business_metrics_required and not self.business_evidence_verified)
        ):
            raise ValueError("Task checks alone cannot complete a business metric request")
        return self


class TraceEvent(Contract):
    sequence: int
    run_id: str
    plan_version: int
    task_id: str | None = None
    node: str
    status: str
    elapsed_ms: float = 0
    error_code: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    usage: Usage | None = None
    context: ContextUsage | None = None
    compression: dict | None = None
