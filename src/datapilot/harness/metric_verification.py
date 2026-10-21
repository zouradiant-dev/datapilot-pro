"""Six deterministic layers. Raw persisted evidence never self-declares correctness."""

import hashlib
from decimal import Decimal
from uuid import uuid4

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.semantics.contracts import (
    Evidence,
    LayerCheck,
    MetricExecution,
    MetricValue,
    VerificationRecord,
)
from datapilot.semantics.recipes import metric_value, request_missing, semantics_match
from datapilot.tools.sql import SQLPolicy, validate_sql


def equal_value(left: MetricValue | None, right: MetricValue | None) -> bool:
    if left is None or right is None:
        return False
    a, b = left.model_dump(), right.model_dump()
    x, y = a.pop("value"), b.pop("value")
    return a == b and x is not None and y is not None and Decimal(x) == Decimal(y)


def make_evidence(execution: MetricExecution, *, evidence_id: str | None = None) -> Evidence:
    context, primary = execution.context, execution.primary
    value = None
    if primary is not None:
        try:
            value = metric_value(context, execution.request, primary.result)
        except (ValueError, ArithmeticError):
            pass
    problems = list(execution.missing)
    if execution.proof and execution.proof.status == "unavailable":
        problems.extend(execution.proof.missing)
    return Evidence(
        evidence_id=evidence_id or str(uuid4()),
        dataset_id=context.dataset_id,
        dataset_version=context.dataset_version,
        source_sha256=context.source_sha256,
        semantic_version=context.semantic_version,
        semantic_sha256=context.semantic_sha256,
        metric_id=context.metric_id,
        metric_version=context.metric_version,
        metric_sha256=context.metric_sha256,
        request=execution.request,
        context_sha256=context.context_sha256,
        query_sql=execution.candidate_sql,
        query_sha256=primary.query_sha256 if primary else None,
        result=primary.result if primary else None,
        result_sha256=primary.result_sha256 if primary else None,
        proof=execution.proof,
        value=value,
        missing=problems[:32],
    )


def verify_execution(
    execution: MetricExecution, evidence: Evidence, referenced: Evidence | None
) -> VerificationRecord:
    context, request = execution.context, execution.request
    primary, proof = execution.primary, execution.proof
    checks = []

    def check(layer, status, code=None):
        checks.append(LayerCheck(layer=layer, status=status, codes=[code] if code else []))

    checked, value = None, None
    if execution.candidate_sql is None:
        check("safety", "not_applicable", "no_query")
    else:
        try:
            policy = SQLPolicy("uploads", frozenset({context.table.physical_name}))
            checked = validate_sql(execution.candidate_sql, policy)
            check("safety", "passed")
        except (AgentFailure, ValueError, AttributeError):
            check("safety", "failed", "unsafe_query")
    if primary is None:
        check("shape", "not_applicable" if evidence.missing else "failed", "no_result")
    else:
        try:
            value = metric_value(context, request, primary.result)
            identity = (primary.dataset_id, primary.version, primary.source_sha256)
            if identity != (context.dataset_id, context.dataset_version, context.source_sha256):
                raise ValueError("Wrong result source")
            if (
                checked is None
                or primary.query_sha256 != hashlib.sha256(checked.encode()).hexdigest()
            ):
                raise ValueError("Query hash mismatch")
            if primary.result_sha256 != digest(
                primary.result.model_dump(mode="json", exclude={"elapsed_ms"})
            ):
                raise ValueError("Result hash mismatch")
            check("shape", "passed")
        except (ValueError, ArithmeticError):
            check("shape", "failed", "result_invalid")
    try:
        problems = request_missing(context, request)
        if (
            digest(context.model_dump(mode="json", exclude={"context_sha256"}))
            != context.context_sha256
        ):
            raise ValueError("Context hash mismatch")
        if problems:
            check("semantics", "not_applicable", "missing_semantics")
        elif checked and semantics_match(checked, context, request):
            check("semantics", "passed")
        else:
            check("semantics", "failed", "recipe_mismatch")
    except (AgentFailure, ValueError):
        check("semantics", "failed", "semantic_identity_invalid")
    if proof is None:
        check("recomputation", "not_applicable" if evidence.missing else "failed", "no_proof")
    elif proof.context_sha256 != context.context_sha256 or proof.request_sha256 != digest(request):
        check("recomputation", "failed", "proof_identity_invalid")
    elif proof.status == "unavailable":
        check("recomputation", "not_applicable", "data_not_verifiable")
    elif (
        not context.table
        or proof.source_rows != context.table.row_count
        or not proof.page_hashes
        or not equal_value(value, proof.value)
    ):
        check("recomputation", "failed", "independent_result_mismatch")
    else:
        check("recomputation", "passed")
    expected = make_evidence(execution, evidence_id=evidence.evidence_id)
    if (
        referenced is None
        or digest(referenced) != digest(evidence)
        or digest(expected) != digest(evidence)
    ):
        check("references", "failed", "reference_invalid")
    else:
        check("references", "passed")
    # A source-bound missing-information answer covers a goal; a guessed scalar does not.
    answered = value is not None and proof is not None and proof.status == "computed"
    unavailable = bool(evidence.missing) and (proof is None or proof.status == "unavailable")
    if evidence.request != request or (request.intent == "explain_cause" and not unavailable):
        check("coverage", "failed", "goal_not_covered")
    elif answered or unavailable:
        check("coverage", "passed")
    else:
        check("coverage", "failed", "goal_not_covered")
    statuses = {c.status for c in checks}
    verdict = (
        "rejected"
        if "failed" in statuses
        else "unavailable"
        if "not_applicable" in statuses
        else "verified"
    )
    return VerificationRecord(
        verification_id=str(uuid4()),
        evidence_id=evidence.evidence_id,
        dataset_id=context.dataset_id,
        dataset_version=context.dataset_version,
        request_sha256=digest(request),
        checks=checks,
        verdict=verdict,
    )
