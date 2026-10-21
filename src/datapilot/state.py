"""LangGraph state holds contracts, never credentials or database connections."""

from typing import Annotated, Literal, TypedDict

from datapilot.contracts import AgentError, SQLAgentResult, SQLTask
from datapilot.orchestration.contracts import (
    CompletionDecision,
    Plan,
    TaskResult,
    VerificationResult,
)


class GraphState(TypedDict):
    run_id: str
    question: str
    status: Literal["pending", "running", "succeeded", "failed", "unsupported"]
    task: SQLTask | None
    result: SQLAgentResult | None
    error: AgentError | None
    steps: int
    answer: str


def merge_results(left: dict, right: dict) -> dict:
    result = dict(left)
    for key, value in right.items():
        if key in result and result[key] != value:
            raise ValueError("Conflicting parallel task result for the same version/key")
        result[key] = value
    return result


class RunState(TypedDict, total=False):
    run_id: str
    question: str
    status: Literal[
        "pending", "running", "succeeded", "failed", "unsupported", "cancelled", "unavailable"
    ]
    plan: Plan
    plan_version: int
    results: Annotated[dict[str, TaskResult], merge_results]
    verifications: Annotated[dict[str, VerificationResult], merge_results]
    replans: int
    steps: int
    answer: str
    error: AgentError | None
    # Compatibility projection for the original single SQL CLI/API; not shared with workers.
    task: SQLTask | None
    result: SQLAgentResult | None
    completion: CompletionDecision
    plan_history: dict[str, Plan]
    reuse_origins: dict[str, str]
