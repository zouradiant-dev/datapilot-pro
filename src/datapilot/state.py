"""LangGraph state holds contracts, never credentials or database connections."""

from typing import Literal, TypedDict

from datapilot.contracts import AgentError, SQLAgentResult, SQLTask


class GraphState(TypedDict):
    run_id: str
    question: str
    status: Literal["pending", "running", "succeeded", "failed", "unsupported"]
    task: SQLTask | None
    result: SQLAgentResult | None
    error: AgentError | None
    steps: int
    answer: str
