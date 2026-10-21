"""Untrusted plans never carry credentials, capabilities, budgets or executable code."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from datapilot.contracts import Contract, QueryResult

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
    kind: Literal["query", "documents", "analysis", "report"]
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


class SearchResult(Contract):
    documents: list[Document] = Field(max_length=5)
    fixture: bool = False


class Artifact(Contract):
    run_id: str
    task_id: TaskId
    plan_version: int
    kind: Literal["query", "documents", "analysis", "report"]
    source: str = Field(max_length=256)
    sql: str | None = Field(default=None, max_length=12000)
    query: QueryResult | None = None
    documents: SearchResult | None = None
    values: dict[str, str] = Field(default_factory=dict, max_length=4)
    parents: list[EvidenceRef] = Field(default_factory=list, max_length=48)


class FinalDecision(Contract):
    artifact_ids: list[Digest] = Field(min_length=1, max_length=8)
    outcome: Literal["complete", "unavailable"] = "complete"


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
