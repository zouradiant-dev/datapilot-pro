"""Fail-closed host completion prototype, independent of the model's final decision."""

import re

from datapilot.contracts import AgentFailure
from datapilot.orchestration.contracts import CompletionDecision, VerificationResult


def metric_intent(text):
    # Conservative safeguard, not a semantic classifier or a replacement for P3 requests.
    return bool(
        re.search(
            r"收入|营收|营业额|流失|活跃订阅|使用量|留存|续费率|"
            r"\b(?:revenue|mrr|arr|arpu|churn|retention|active\s+subscriptions|usage)\b",
            text,
            re.IGNORECASE,
        )
    )


def completion_gate(state, store, verify_task, *, original_plan=None, require_metrics=False):
    plan, version = state.get("plan"), state.get("plan_version", 1)
    reasons, verified = [], []
    blocked = False

    def reject(code, *, hard=False):
        nonlocal blocked
        if code not in reasons:
            reasons.append(code)
        blocked |= hard

    if state.get("error") or state.get("status") in {"cancelled", "failed", "unsupported"}:
        reject("RUN_NOT_SUCCESSFUL", hard=True)
    if plan is None or plan.unsupported or not plan.tasks:
        reject("NO_SUPPORTED_PLAN", hard=True)
    tasks = plan.tasks if plan else []
    required = [t.task_id for t in tasks]
    if original_plan:
        # Replan may fix execution, but dropping a previously required task cannot erase a goal.
        current = {t.task_id: t for t in tasks}
        for task in original_plan.tasks:
            if current.get(task.task_id) != task:
                reject("REQUIRED_TASK_CHANGED")
    metric_required = require_metrics or metric_intent(
        state.get("question", "") + "\n" + "\n".join(t.instruction for t in tasks)
    )
    for task in tasks:
        task_key = f"{version}:{task.task_id}"
        result = state.get("results", {}).get(task_key)
        checked = state.get("verifications", {}).get(task_key)
        if result is None or checked is None:
            reject("TASK_OR_VERIFICATION_MISSING")
            continue
        try:
            checked = VerificationResult.model_validate_json(checked.model_dump_json())
        except ValueError:
            reject("VERIFICATION_CONTRACT_INVALID", hard=True)
            continue
        if result.status != "succeeded" or checked.status != "passed":
            reject("REQUIRED_TASK_NOT_VERIFIED", hard=result.status != "succeeded")
            continue
        if (checked.task_id, checked.plan_version) != (task.task_id, version):
            reject("VERIFICATION_IDENTITY_INVALID", hard=True)
            continue
        try:
            # Recheck actual artifacts at Finish, not a cached model/worker boolean.
            if verify_task(state, task, result).status != "passed":
                raise AgentFailure("EVIDENCE_INVALID", "Final task revalidation failed")
            for ref in result.evidence_refs:
                artifact = store.get(ref)
                for parent in artifact.parents:
                    store.get(parent)
                if artifact.query and artifact.query.truncated:
                    reject("RESULT_TRUNCATED")
            verified.append(task.task_id)
        except (AgentFailure, ValueError, KeyError):
            reject("FINAL_EVIDENCE_INVALID", hard=True)
    if metric_required:
        # Deliberately no P3→P4 report bridge in P4.1. A raw SQL/Artifact SHA can never
        # substitute for persisted, version-bound P3 Evidence + six-layer Verification.
        reject("P3_VERIFIED_EVIDENCE_REQUIRED", hard=True)
    return CompletionDecision(
        status="blocked" if blocked else "incomplete" if reasons else "completed",
        required_tasks=required,
        verified_tasks=verified,
        reason_codes=reasons,
        business_metrics_required=metric_required,
    )
