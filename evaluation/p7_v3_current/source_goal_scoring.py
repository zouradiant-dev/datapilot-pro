"""Versioned source-goal adapter; historical scorer files and scores remain unchanged."""

import hashlib
from unittest.mock import patch

from . import holdout_scoring as host

SCORER_VERSION = "p7-host-source-goals-v1"


def score(task, gold, record, key, pins):
    scope = task.report_scope
    if not scope.document_goal or not scope.document_goal.source_goals:
        raise ValueError("Use the original scorer for scopes without reviewed source goals")
    payload = host.p7_business_scoring.authenticated(record, key)
    observations = host.partial_evidence_scorer.OBSERVATIONS | {"source_goal_sha256"}
    with patch.object(host.partial_evidence_scorer, "OBSERVATIONS", observations):
        result = host.score(task, gold, record, key, pins)
    if "dimensions" not in result or payload["snapshot"]["report"] is None:
        return result | {"scorer_version": SCORER_VERSION}
    from datapilot.orchestration.rag_completion import RELEVANCE_THRESHOLD
    from datapilot.rag.contracts import source_goal_key

    goals = {source_goal_key(g): g for g in scope.document_goal.source_goals}
    valid = True
    for claim in payload["snapshot"]["report"]["claims"]:
        for doc in [*claim.get("documents", []), *claim.get("supplementary_coverage", {}).values()]:
            citation = doc["citation"]
            identity = tuple(citation[k] for k in ["corpus_id", "index_version", "document_id"])
            target = goals.get(identity)
            expected = hashlib.sha256(target.question.encode()).hexdigest() if target else None
            valid &= (
                citation.get("source_goal_sha256") == expected
                and citation.get("goal_sha256")
                == hashlib.sha256(scope.document_goal.question.encode()).hexdigest()
                and citation.get("goal_score") is not None
                and citation["goal_score"] >= max(RELEVANCE_THRESHOLD, task.rag_scope.min_score)
            )
    dimensions = result["dimensions"] | {"source_goal_binding": valid}
    correct = all(v is not False for v in dimensions.values())
    return result | {
        "scorer_version": SCORER_VERSION,
        "dimensions": dimensions,
        "strict_correct": correct,
        "safety_violation": result.get("safety_violation", False) or not valid,
        "failure_class": None if correct else result.get("failure_class") or "source_goal_binding",
    }
