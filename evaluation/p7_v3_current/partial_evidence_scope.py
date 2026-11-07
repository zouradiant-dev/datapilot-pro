"""Explicit trusted-host opt-in to the existing partial literal evidence contract."""

import json

from datapilot.reporting.contracts import ReportScope, confirm_finite_scope


def confirm_partial_literals(scope, rag_scope, *, confirmation_ref):
    scope = ReportScope.model_validate_json(scope.model_dump_json())
    goal = scope.document_goal
    if (
        goal is None
        or goal.purpose != "facts"
        or not any(f.citation and f.quotation and f.confirmation_ref for f in goal.required_facts)
    ):
        raise ValueError("Partial literal publication needs an existing host-reviewed fact proof")
    value = scope.model_dump(mode="json", exclude={"goal_scope_attestation"})
    value["partial_evidence_policy"] = "partial-facts-v1"
    reviewed = ReportScope.model_validate_json(json.dumps(value))
    return confirm_finite_scope(reviewed, rag_scope, confirmation_ref=confirmation_ref)


def confirm_document_evidence(scope, rag_scope, *, confirmation_ref):
    """Record a new host review of publication and explanations, never mutate an old scope."""
    value = scope.model_dump(mode="json", exclude={"goal_scope_attestation"})
    if scope.document_goal is None or scope.document_goal.purpose not in {"facts", "conclusion"}:
        raise ValueError("Evidence publication needs explicit document facts or conclusion goals")
    value.update(
        partial_evidence_policy="partial-facts-v1",
        rag_query_policy="source-goals-v1"
        if scope.document_goal.source_goals
        else "original-first-v1",
        document_explanation_policy="evidence-reasons-v1",
    )
    reviewed = ReportScope.model_validate_json(json.dumps(value))
    return confirm_finite_scope(reviewed, rag_scope, confirmation_ref=confirmation_ref)
