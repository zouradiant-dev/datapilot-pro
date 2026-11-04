"""Versioned scoring for explicitly approved partial literal evidence, never full completion."""

import json
from types import SimpleNamespace

import scorer as v2

from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact
from datapilot.orchestration.rag_completion import retrieval_goal
from datapilot.reporting.contracts import CrossSourceReport

SCORER_VERSION = "p7-current-partial-evidence-v3"
OBSERVATIONS = {"score", "goal_sha256", "goal_score"}


def literal_evidence(document, payload, task, scope, rag_result, pins):
    """Only actual current-task artifacts and host-reviewed literal subquotes qualify."""
    if document.artifact_id not in {ref["artifact_id"] for ref in rag_result["evidence_refs"]}:
        return False
    body = payload["artifacts"].get(document.artifact_id)
    if not body or digest(body) != document.artifact_id:
        return False
    artifact = Artifact.model_validate_json(json.dumps(body))
    if not artifact.documents:
        return False
    for original in artifact.documents.documents:
        if original.citation != document.citation:
            continue
        full = document.model_copy(update={"excerpt": original.text})
        if original.sha256 != document.citation.sha256 or not v2.citation_matches_pin(
            full, task, pins
        ):
            return False
        if original.text == document.excerpt:
            return True
        return bool(document.excerpt and document.excerpt in original.text) and any(
            fact.citation is not None
            and fact.confirmation_ref
            and fact.quotation == document.excerpt
            and fact.citation.model_dump(exclude=OBSERVATIONS)
            == document.citation.model_dump(exclude=OBSERVATIONS)
            for fact in scope.document_goal.required_facts
        )
    return False


def score(task, gold, record, key, pins):
    baseline = v2.score(task, gold, record, key, pins)
    result = baseline | {
        "scorer_version": SCORER_VERSION,
        "v2_strict_correct": baseline["strict_correct"],
    }
    if not task.document_goal or "dimensions" not in baseline:
        return result
    payload = v2.original.authenticated(record, key)
    report = CrossSourceReport.model_validate_json(json.dumps(payload["snapshot"]["report"]))
    scope = report.authorization_scope
    if scope.partial_evidence_policy != "partial-facts-v1":
        return result  # No implicit policy change or retrospective rescue of legacy reports.
    rag = v2.original.rag_result(payload, task)  # Original goal/receipt/Journal integrity checks.
    citations = [doc for claim in report.claims for doc in claim.documents]
    evidence_valid = all(
        literal_evidence(doc, payload, task, scope, rag, pins) for doc in citations
    )
    dimensions = dict(baseline["dimensions"])
    dimensions["evidence"] = evidence_valid
    goal = retrieval_goal(
        scope.document_goal.question, SimpleNamespace(scope=task.rag_scope), scope
    )
    dimensions["goal_scope_attested"] = goal["completion_eligible"] is True
    sources = {
        doc.citation.source_id
        for doc in citations
        if gold.retrieval is None
        or "relevant_document_ids" not in gold.retrieval
        or doc.citation.document_id in gold.retrieval["relevant_document_ids"]
    }
    dimensions["citations"] = (
        dimensions["authorization"] is True
        and evidence_valid
        and len(sources) >= gold.minimum_cited_sources
    )
    missing_codes = set(
        report.business_completion.missing_evidence.get(task.document_goal.goal_id, [])
    )
    receipt = rag.get("rag_completion") or {}
    actual = receipt.get("submission", {}).get("outcome")
    partial_receipt = (
        gold.retrieval_expected == "complete"
        and gold.business_completion == report.business_completion.status == "partial"
        and bool(gold.missing_fact_ids)
        and rag["status"] == "unavailable"
        and actual == receipt.get("verdict") == "insufficient"
        and "rag_task_insufficient" in missing_codes
        and task.document_goal.goal_id not in report.business_completion.verified_goals
        and any(
            proof is not None for claim in report.claims for proof in claim.fact_coverage.values()
        )
        and all(
            dimensions[name] is True
            for name in (
                "business",
                "fact_coverage",
                "citations",
                "authorization",
                "protocol",
                "budget",
                "durable",
                "goal_scope_attested",
            )
        )
    )
    dimensions["retrieval_contract"] = (
        baseline["dimensions"]["retrieval_contract"] or partial_receipt
    )
    correct = all(value is not False for value in dimensions.values())
    return result | {
        "strict_correct": correct,
        "dimensions": dimensions,
        "failure_class": None if correct else "partial_evidence_or_contract_mismatch",
        "safety_violation": not evidence_valid
        or dimensions["authorization"] is not True
        or (
            report.business_completion.status == "completed" and dimensions["business"] is not True
        ),
        "partial_evidence_scoring": {
            "policy": scope.partial_evidence_policy,
            "literal_evidence_valid": evidence_valid,
            "original_retrieval_expected": gold.retrieval_expected,
            "actual_retrieval_outcome": actual,
            "insufficient_compatible_with_partial": partial_receipt,
            "rag_worker_completed": rag["status"] == "succeeded",
        },
        "citation_quality": baseline["citation_quality"]
        | {
            "source_pins_valid": evidence_valid,
            "literal_excerpt_policy": "host-confirmed-subquote-v1",
        },
    }
