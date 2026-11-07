"""Nonpaid publication admission using the real report builder and verifier.

Inputs must be independently obtained Dev evidence, not passages generated from
Gold. This checks whether a reviewed finite contract can actually be published;
it does not run a model, grant scope, or replace a business-quality evaluation.
"""

from collections.abc import Collection

from datapilot.reporting.contracts import CrossSourceReport
from datapilot.reporting.service import ReportService


def check_publication_expectation(
    service: ReportService,
    artifacts,
    retrieval,
    *,
    source_statuses: dict[str, str],
    expected_status: str,
    expected_verified_goals: Collection[str],
    expected_evidence_goals: Collection[str],
    expected_unconfirmed_claims: Collection[str],
) -> CrossSourceReport:
    """Build and independently verify a report against predeclared expectations.

    Authorization, version and evidence failures propagate unchanged. Reviewed
    literal proofs must survive publication even when their role is evidence-only
    and the business conclusion correctly remains partial or unavailable.
    """
    report = service.build(artifacts, retrieval, source_statuses=source_statuses)
    service.verify_report(report, artifacts, retrieval, source_statuses=source_statuses)
    completion = report.business_completion
    checks = (
        (completion.status, expected_status, "business status"),
        (set(completion.verified_goals), set(expected_verified_goals), "verified goals"),
        (
            set(completion.satisfied_evidence_goals),
            set(expected_evidence_goals),
            "evidence-only goals",
        ),
        (
            set(completion.unconfirmed_claims),
            set(expected_unconfirmed_claims),
            "unconfirmed conclusions",
        ),
    )
    for actual, expected, label in checks:
        if actual != expected:
            raise ValueError(f"Publication {label} conflicts with the reviewed expectation")
    if goal := service.scope.document_goal:
        reviewed_facts = {fact.fact_id for fact in goal.required_facts if fact.citation is not None}
        published_facts = {
            fact_id
            for claim in report.claims
            if claim.goal_id == goal.goal_id and claim.kind == "context"
            for fact_id, proof in claim.fact_coverage.items()
            if proof is not None
        }
        if not reviewed_facts <= published_facts:
            raise ValueError("Publication omitted a required reviewed literal fact")
    return report
