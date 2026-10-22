"""Completion projection only after original task/P3/reference revalidation."""

from datapilot.orchestration.contracts import CompletionDecision
from datapilot.reporting.contracts import BusinessCompletion


def finalize(engine, state, execution_status):
    version = state.get("plan_version", 1)
    task = (
        next((t for t in state.get("plan").tasks if t.task_id == "report"), None)
        if state.get("plan")
        else None
    )
    result = state.get("results", {}).get(f"{version}:report")
    report = None
    if (
        task
        and result
        and result.status == "succeeded"
        and engine.verify(state, task, result).status == "passed"
    ):
        report = engine.store.get(result.evidence_refs[0]).report
    required = list(engine.reporting.requests)
    if engine.reporting.scope.document_goal:
        required.append(engine.reporting.scope.document_goal.goal_id)
    business = (
        report.business_completion
        if report
        else BusinessCompletion(
            status="blocked",
            required_goals=required,
            verified_goals=[],
            missing_evidence={g: ["report_evidence_not_verified"] for g in required},
        )
    )
    if execution_status in {"failed", "cancelled"}:
        business = business.model_copy(update={"status": "blocked"})
    fields = {
        "execution_status": execution_status,
        "business_completion": business,
        "cross_source_report": report,
    }
    if report:
        required_tasks = [t.task_id for t in state["plan"].tasks]
        verified = [
            t.task_id
            for t in state["plan"].tasks
            if state["verifications"][f"{version}:{t.task_id}"].status == "passed"
        ]
        fields["completion"] = CompletionDecision(
            status="completed"
            if business.status == "completed"
            else "incomplete"
            if business.status == "partial"
            else "blocked",
            required_tasks=required_tasks,
            verified_tasks=verified,
            reason_codes=[]
            if business.status == "completed"
            else ["BUSINESS_" + business.status.upper()],
            business_metrics_required=True,
            business_evidence_verified=business.status == "completed",
        )
    return fields
