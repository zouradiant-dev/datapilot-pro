"""Dev-only policy and limited-view simulation; never an authoritative product report."""

from typing import Literal

from pydantic import Field

from datapilot.contracts import AgentFailure, Contract
from datapilot.ingestion.common import digest
from datapilot.orchestration.rag_completion import retrieval_goal, validate_submission
from datapilot.reporting.contracts import DocumentReference, ReportScope
from datapilot.reporting.service import fact_coverage


class LimitedView(Contract):
    mode: Literal["dev_projection_only"] = "dev_projection_only"
    policy_status: Literal["PENDING_OWNER_ADJUDICATION"] = "PENDING_OWNER_ADJUDICATION"
    status: Literal["completed", "partial", "unavailable", "blocked"]
    receipt_outcome: Literal["complete", "insufficient", "unavailable"]
    required_source_coverage: float = Field(ge=0, le=1)
    supported_facts: list[str] = Field(max_length=8)
    missing_facts: list[str] = Field(max_length=8)
    documents: list[DocumentReference] = Field(max_length=10)
    causal_verified: Literal[False] = False
    p3_verdict: Literal["verified", "unavailable", "rejected"] | None = None
    missing: list[str] = Field(max_length=12)


def citation_policy(required, published, supplementary=None, *, allow_supplements=False):
    """All sets are pre-registered host labels, never model-supplied authority."""
    supplementary = supplementary or set()
    allowed = required | (supplementary if allow_supplements else set())
    return {
        "required_coverage": len(required & published) / len(required) if required else None,
        "precision": len(allowed & published) / len(published) if published else None,
        "missing": sorted(required - published),
        "unsupported": sorted(published - allowed),
        "accepted": required <= published and published <= allowed,
        "status": "PENDING_OWNER_ADJUDICATION",
    }


def project(
    service, pairs, retrieval, envelope, store, submission, required_sources, *, metric=None
):
    """Keep original receipt/status; authenticate every source before literal fact proof.

    This simulates a separate limited evidence view, not a relaxed ReportService.build.
    It never makes an insufficient receipt complete, counts supplements as required,
    interprets new facts, or persists a replacement P3/Report verdict.
    """
    try:
        ReportScope.model_validate_json(service.scope.model_dump_json())
    except ValueError:
        raise AgentFailure("REPORT_SCOPE_INVALID", "Host fact contract is invalid") from None
    if not required_sources or set(submission.artifact_ids) != {r.artifact_id for r, _ in pairs}:
        raise AgentFailure("EVIDENCE_INVALID", "Receipt and retained artifacts differ")
    goal = service.scope.document_goal
    validate_submission(
        envelope, store, [r for r, _ in pairs], submission, retrieval, retrieval_goal(goal.question)
    )
    documents = []
    for ref, artifact in pairs:
        if ref.artifact_id != digest(artifact) or ref.sha256 != ref.artifact_id:
            raise AgentFailure("EVIDENCE_INVALID", "Artifact payload/reference changed")
        retrieval.validate_result(artifact.documents)
        qualified = retrieval.qualifying_documents(
            artifact.documents.documents, retrieval_goal(goal.question)
        )
        documents.extend(
            DocumentReference(artifact_id=ref.artifact_id, citation=d.citation, excerpt=d.text)
            for d in qualified
        )
    coverage = fact_coverage(goal, documents)
    support = sorted(k for k, value in coverage.items() if value is not None)
    missing_facts = sorted(k for k, value in coverage.items() if value is None)
    observed = {d.citation.source_id for d in documents}
    source_coverage = len(required_sources & observed) / len(required_sources)
    missing = ["document_fact_unverified:" + f for f in missing_facts]
    if source_coverage < 1:
        missing.append("required_source_missing")
    if submission.outcome != "complete":
        missing.append("retrieval_contract_incomplete")
    if service.scope.causal_requested:
        missing.append("causal_conclusion_not_verified")
    verdict = None
    if metric is not None:
        service.verify_metric(metric)
        verdict = metric.verdict
    status = (
        "completed"
        if not missing
        else "partial"
        if support or verdict == "verified"
        else "unavailable"
    )
    return LimitedView(
        status=status,
        receipt_outcome=submission.outcome,
        required_source_coverage=source_coverage,
        supported_facts=support,
        missing_facts=missing_facts,
        documents=documents,
        p3_verdict=verdict,
        missing=missing,
    )
