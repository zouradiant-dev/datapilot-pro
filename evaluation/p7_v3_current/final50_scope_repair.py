"""Trusted-host reconstruction of independent policy contracts, not a Worker capability."""

import json

from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import ReportScope, confirm_finite_scope


def confirm_independent_policy(scope: ReportScope, rag: RagScope, *, confirmation_ref: str):
    """Reuse the reviewed report grants without changing metric or source identities."""
    scope = ReportScope.model_validate_json(scope.model_dump_json())
    rag = RagScope.model_validate_json(rag.model_dump_json())
    goal = scope.document_goal
    allowed = {(b.dataset_id, b.version) for b in scope.datasets.bindings}
    if (
        goal is None
        or goal.purpose != "facts"
        or not goal.required_facts
        or any(not (f.citation and f.quotation and f.confirmation_ref) for f in goal.required_facts)
        or any((b.dataset_id, b.version) not in allowed for b in rag.datasets.bindings)
    ):
        raise ValueError("Independent policy needs reviewed facts and report-authorized datasets")
    value = scope.model_dump(mode="json", exclude={"goal_scope_attestation"})
    value["document_goal"]["independent_facts"] = True
    reviewed = ReportScope.model_validate_json(json.dumps(value))
    rag.datasets = reviewed.datasets.model_copy(deep=True)
    return (
        confirm_finite_scope(reviewed, rag, confirmation_ref=confirmation_ref),
        rag,
    )
