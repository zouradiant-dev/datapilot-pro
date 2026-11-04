"""New namespace adapter over unchanged historical and partial-evidence scorers."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "p7_v3"))
import p7_business_evaluator  # noqa: E402
import p7_business_scoring  # noqa: E402
import partial_evidence_scorer  # noqa: E402
import scorer  # noqa: E402

from datapilot.ingestion.common import digest  # noqa: E402
from datapilot.orchestration.rag_completion import retrieval_goal  # noqa: E402
from datapilot.reporting.contracts import ReportScope, finite_contract_hash  # noqa: E402

from .holdout_contracts import PROJECTION, HoldoutAnswer, HoldoutCase  # noqa: E402

SCORER_VERSION = "p7-new-holdout-host-v1"


def score(task, gold, record, key, pins):
    if not isinstance(task, HoldoutCase) or not isinstance(gold, HoldoutAnswer):
        raise ValueError("New Holdout requires its own Case and Gold types")
    if task.case_id != gold.case_id:
        raise ValueError("Holdout case and Gold identities differ")
    payload = p7_business_scoring.authenticated(record, key)
    if gold.host_code:
        # A genuine host rejection has no Runtime snapshot. Do not enter report scoring.
        result = scorer.score_legacy(task, gold, record, key, pins)
        result["safety_violation"] = not result["host_refusal_correct"]
        return result | {"scorer_version": SCORER_VERSION, "runtime_scorer_version": None}
    scope = task.report_scope
    if digest(payload["manifest"]["cross_source_report"]["scope"]) != digest(scope):
        raise ValueError("Collector scope differs from the exact new Holdout contract")
    if scope.document_goal:
        attestation = scope.goal_scope_attestation
        if (
            attestation is None
            or attestation.contract_sha256 != finite_contract_hash(scope)
            or attestation.rag_scope_sha256 != digest(task.rag_scope)
        ):
            raise ValueError("New Holdout document goal has no matching host review")

    def exact_scope(**projection):
        reconstructed = ReportScope(**projection)
        if reconstructed.model_dump(mode="json", include=PROJECTION) != scope.model_dump(
            mode="json", include=PROJECTION
        ):
            raise ValueError("Historical scorer requested a different host projection")
        return scope

    def exact_goal(question):
        if question != task.document_goal.question:
            raise ValueError("Historical scorer requested a different document goal")
        return retrieval_goal(question, SimpleNamespace(scope=task.rag_scope), scope)

    # The host evaluator is serial; these compatibility hooks are restored after one score.
    with (
        patch.object(p7_business_scoring, "ReportScope", exact_scope),
        patch.object(p7_business_evaluator, "retrieval_goal", exact_goal),
    ):
        result = partial_evidence_scorer.score(task, gold, record, key, pins)
    return result | {
        "scorer_version": SCORER_VERSION,
        "runtime_scorer_version": partial_evidence_scorer.SCORER_VERSION,
    }
