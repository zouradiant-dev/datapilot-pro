"""Strict boundaries between planner, worker and deterministic tools."""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AgentError(Contract):
    code: str
    message: str
    retryable: bool = False


class AgentFailure(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.error = AgentError(code=code, message=message, retryable=retryable)
        super().__init__(message)


class RouteDecision(Contract):
    route: Literal["sql", "unsupported"]


class SQLTask(Contract):
    task_id: str
    worker: Literal["sql"] = "sql"
    question: str = Field(min_length=1, max_length=8000)


class SQLProposal(Contract):
    sql: str = Field(min_length=1, max_length=12000)


class QueryResult(Contract):
    columns: list[str]
    rows: list[list[str | int | float | bool | None]]
    row_count: int = Field(ge=0)
    truncated: bool
    elapsed_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def consistent_shape(self):
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("Duplicate column names; use explicit aliases")
        if self.row_count != len(self.rows) or any(len(r) != len(self.columns) for r in self.rows):
            raise ValueError("Inconsistent query result shape")
        for row in self.rows:
            for cell in row:
                if isinstance(cell, float) and not math.isfinite(cell):
                    raise ValueError("Nonfinite query result")
        return self


class SQLAgentResult(Contract):
    task_id: str
    status: Literal["succeeded", "failed"]
    sql: str | None = None
    result: QueryResult | None = None
    error: AgentError | None = None
    attempts: int = Field(ge=0)

    @model_validator(mode="after")
    def consistent_status(self):
        if self.status == "succeeded":
            if self.result is None or self.error is not None or self.sql is None:
                raise ValueError("Success requires SQL and data without an error")
        elif self.error is None or self.result is not None:
            raise ValueError("Failure requires error without data")
        return self
