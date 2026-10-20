"""Deterministic checks, independent of model self-evaluation."""

from pydantic import ValidationError

from datapilot.contracts import AgentFailure, SQLAgentResult, SQLTask


def verify_completion(task: SQLTask, result: SQLAgentResult, max_rows: int) -> None:
    try:
        checked = SQLAgentResult.model_validate(result.model_dump())
    except ValidationError as exc:
        raise AgentFailure("VERIFICATION_ERROR", "Worker returned an invalid result") from exc
    if checked.task_id != task.task_id:
        raise AgentFailure("VERIFICATION_ERROR", "Worker result task_id does not match delegation")
    if checked.result is not None and checked.result.row_count > max_rows:
        raise AgentFailure("VERIFICATION_ERROR", "Worker result exceeds the row limit")
