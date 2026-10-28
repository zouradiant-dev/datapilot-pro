"""Offline evaluator only. Verify a trusted collection signature before inspecting Gold."""

import hashlib
import hmac
from decimal import Decimal

from p7_holdout_pack import canonical, sha

from datapilot.ingestion.common import digest
from datapilot.reporting.contracts import ReportScope


def sign_collection(payload, key):
    if len(key) < 32:
        raise ValueError("Collector signing key is too short")
    raw = canonical(payload)
    return {
        "payload": payload,
        "sha256": sha(raw),
        "signature": hmac.new(key, raw, hashlib.sha256).hexdigest(),
    }


def authenticated(record, key):
    expected = sign_collection(record["payload"], key)
    if (
        not hmac.compare_digest(record["signature"], expected["signature"])
        or record["sha256"] != expected["sha256"]
    ):
        raise ValueError("Collection changed or was not signed by the trusted collector")
    return record["payload"]


def rank_metrics(actual, relevant, k=3):
    """Unique entities in first-occurrence order, never best-of-query selection."""
    actual = list(dict.fromkeys(actual))[:k]
    relevant = set(relevant)
    hits = [i for i, x in enumerate(actual, 1) if x in relevant]
    return {
        "recall": len(hits) / len(relevant) if relevant else None,
        "precision": len(hits) / len(actual) if actual else 0,
        "mrr": 1 / hits[0] if hits else 0,
        "returned": len(actual),
        "relevant": len(relevant),
    }


def score_case(task, gold, record, key, *, source_hashes):
    observed = authenticated(record, key)
    # Same original digest as run_durable/launch records: canonical JSON of exact text.
    if observed["case_id"] != task.case_id or observed["question_sha256"] != digest(task.question):
        raise ValueError("Collection belongs to a different frozen question")
    snapshot = observed["snapshot"]
    scope = ReportScope(
        owner=task.owner,
        question=task.question,
        datasets=task.datasets,
        metrics=task.metrics,
        document_goal=task.document_goal,
        causal_requested=task.causal_requested,
    )
    recorded_scope = observed["manifest"]["cross_source_report"]["scope"]
    if digest(recorded_scope) != digest(scope):
        raise ValueError("Collected scope differs from the frozen task")
    expected_rag = task.rag_scope.model_dump(mode="json") if task.rag_scope else None
    if observed["manifest"].get("rag_scope") != expected_rag:
        raise ValueError("Collected document authority differs from the frozen task")
    report = snapshot.get("report")
    if snapshot["unknown"] or snapshot["next"] or snapshot["review"] or not report:
        return {
            "case_id": task.case_id,
            "strict_correct": False,
            "status": "unknown" if snapshot["unknown"] else "blocked",
            "requires_human_adjudication": True,
        }
    claims = report["claims"]
    metric_claims = {c["goal_id"]: c for c in claims if c["kind"] == "metric"}
    requests = {r.goal_id: r.model_dump(mode="json") for r in task.metrics}
    numeric = []
    for goal in gold.metrics:
        claim = metric_claims.get(goal.goal_id)
        if goal.disposition == "unavailable":
            numeric.append(
                {"goal_id": goal.goal_id, "correct": claim is None, "expected": "unavailable"}
            )
            continue
        bridge = claim["metric"] if claim else None
        correct = bool(
            bridge
            and bridge["verdict"] == "verified"
            and bridge["verification"]["verdict"] == "verified"
            and bridge["evidence_id"]
            and bridge["verification"]["verification_id"]
            and Decimal(bridge["value"]["value"]) == Decimal(goal.value)
            and bridge["value"]["unit"] == goal.unit
            and bridge["request"] == requests[goal.goal_id]
            and bridge["source_sha256"]
            == source_hashes.get(
                (requests[goal.goal_id]["dataset_id"], requests[goal.goal_id]["dataset_version"])
            )
        )
        if correct and goal.denominator is not None:
            correct = (bridge["value"]["numerator"], bridge["value"]["denominator"]) == (
                goal.numerator,
                goal.denominator,
            )
        numeric.append({"goal_id": goal.goal_id, "correct": correct, "expected": "verified"})
    documents = [d for c in claims for d in c["documents"]]
    facts = (gold.retrieval or {}).get("facts", [])
    covered = [
        any(
            d["citation"]["document_id"] == f["document_id"]
            and d["citation"]["version"] == f["version"]
            and d["citation"]["start"] <= f["start"]
            and d["citation"]["end"] >= f["end"]
            and f["literal"] in d["excerpt"]
            for d in documents
        )
        for f in facts
    ]
    # Structured refusal reason equivalence needs an independent human decision: do not
    # invent aliases to convert every missing/failed tool into a legitimate refusal.
    needs_review = bool(gold.refusal_conditions)
    completion = report["business_completion"]
    correct = (
        completion["status"] == gold.business_completion
        and all(n["correct"] for n in numeric)
        and all(covered)
        and not needs_review
        and not (set(metric_claims) - {m.goal_id for m in gold.metrics})
    )
    if gold.causal_claim_must_remain_unverified:
        correct = correct and bool(completion["unconfirmed_claims"])
    return {
        "case_id": task.case_id,
        "strict_correct": correct,
        "status": completion["status"],
        "numeric": numeric,
        "required_fact_coverage": {"covered": sum(covered), "required": len(covered)},
        "requires_human_adjudication": needs_review,
        "automated_refusal_semantic_scoring": "not_implemented_fail_closed"
        if needs_review
        else "not_needed",
    }


def planned_summary(inputs, observations):
    """Missing outcomes remain in the planned denominator; never report empty Live quality."""
    ids = {t.case_id for t in inputs}
    if set(observations) - ids:
        raise ValueError("Observation outside the frozen task set")
    return {
        "planned_tasks": len(inputs),
        "collected_tasks": len(observations),
        "not_run": sorted(ids - set(observations)),
        "formal_business_live": "not_run" if not observations else "requires_campaign_verification",
        "live_success_rate": None,
    }
