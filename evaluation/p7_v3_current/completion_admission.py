"""Nonpaid contract controls using the actual Runtime completion verifier.

The witness must come from separately approved Dev retrieval, never a model claim
or Gold-generated passage. This checks retrieval expectations, not business truth.
"""

from datapilot.contracts import AgentFailure
from datapilot.orchestration.contracts import RagSubmission
from datapilot.orchestration.rag_completion import validate_submission


def check_retrieval_expectation(envelope, store, refs, retrieval, goal, expected):
    """Fail admission when an independent retrieval witness contradicts its label."""
    ids = [ref.artifact_id for ref in refs]
    complete = RagSubmission(artifact_ids=ids, outcome="complete")
    try:
        validate_submission(envelope, store, refs, complete, retrieval, goal)
    except AgentFailure as exc:
        if exc.error.code != "EVIDENCE_INSUFFICIENT":
            raise  # Authorization, integrity and version failures are never insufficiency.
        empty = not any(store.get(ref).documents.documents for ref in refs)
        observed = "unavailable" if empty else "insufficient"
    else:
        observed = "complete"
    if expected != observed:
        raise ValueError(
            f"Retrieval expectation {expected} conflicts with Runtime witness {observed}; "
            "review retrieval requirements separately from business fact coverage"
        )
    validate_submission(
        envelope,
        store,
        refs,
        RagSubmission(artifact_ids=ids, outcome=expected),
        retrieval,
        goal,
    )
    return observed
