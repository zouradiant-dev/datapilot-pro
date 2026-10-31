"""Frozen offline scorer adapter over original P7 signature, metric and RAG contracts."""

import argparse
import json
import sys
from collections import Counter
from math import sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from p7_business_evaluator import rag_result, retrieval_scores
from p7_business_scoring import authenticated, score_case
from v3_common import load, read_answers, verify

from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact, Plan, TaskResult, VerificationResult
from datapilot.reporting.contracts import CrossSourceReport


def aggregate(tasks, golds, observations):
    """Frozen denominators; no zero-data percentages or independent-trial claim."""
    if set(observations) - {t.case_id for t in tasks}:
        raise ValueError("Unknown observation")

    def group(selected):
        rows = [observations[t.case_id] for t in selected if t.case_id in observations]
        n = len(rows)
        correct = sum(r["strict_correct"] for r in rows)
        interval = None
        if n:
            z = 1.959963984540054
            p = correct / n
            d = 1 + z * z / n
            center = (p + z * z / (2 * n)) / d
            width = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
            interval = [center - width, center + width]
        return {
            "planned": len(selected),
            "observed": n,
            "strict_correct": correct,
            "strict_over_observed": correct / n if n else None,
            "strict_over_planned": correct / len(selected) if n and selected else None,
            "wilson95_descriptive": interval,
            "status_counts": dict(Counter(r.get("status") for r in rows)),
        }

    by_id = {g.case_id: g for g in golds}
    return {
        "all": group(tasks),
        "lanes": {
            lane: group([t for t in tasks if t.lane == lane])
            for lane in ["sql_only", "rag_only", "sql_rag"]
        },
        "gold_completed": group(
            [t for t in tasks if by_id[t.case_id].business_completion == "completed"]
        ),
        "gold_partial": group(
            [t for t in tasks if by_id[t.case_id].business_completion == "partial"]
        ),
        "gold_pure_refusal": group(
            [t for t in tasks if by_id[t.case_id].business_completion in {"unavailable", "blocked"}]
        ),
        "not_run": [t.case_id for t in tasks if t.case_id not in observations],
        "failure_classes": dict(
            Counter(r["failure_class"] for r in observations.values() if r.get("failure_class"))
        ),
        "source_cluster_limit": (
            "Shared datasets/sources; Wilson intervals are descriptive, "
            "not iid population guarantees"
        ),
    }


def failure_class(payload):
    state = payload.get("snapshot", {}).get("state", {})
    codes = {
        result["error"]["code"]
        for result in state.get("results", {}).values()
        if result.get("error")
    }
    if state.get("error"):
        codes.add(state["error"]["code"])
    if payload.get("snapshot", {}).get("unknown"):
        return "unknown_outcome"
    for names, label in [
        ({"BUDGET_EXCEEDED", "CONTEXT_LIMIT"}, "budget_exceeded"),
        ({"MODEL_TIMEOUT", "TOOL_TIMEOUT", "MCP_TIMEOUT"}, "timeout"),
        ({"MODEL_ERROR", "PROVIDER_ERROR"}, "provider_error"),
        (
            {"RECOVERY_IDENTITY", "RECOVERY_CORRUPT", "RECOVERY_BUSY", "RECOVERY_EXPIRED"},
            "durable_recovery_conflict",
        ),
        ({"PLAN_INVALID", "PLAN_COVERAGE", "MODEL_OUTPUT_INVALID"}, "planner_error"),
        ({"SQL_EXECUTION_ERROR", "QUERY_ERROR", "SQL_ERROR"}, "sql_tool_error"),
    ]:
        if codes & names:
            return label
    return "business_or_evidence_mismatch"


def call_integrity(payload):
    calls = payload.get("calls", [])
    indexed = {c["call_key"]: c for c in calls}
    if len(indexed) != len(calls):
        return False
    paired = set()
    for row in calls:
        if row["status"] != "complete" or digest(row["payload"]) != row["payload_hash"]:
            return False
        if row["kind"] == "model":
            for call in row["payload"]["data"].get("tool_calls", []):
                result = indexed.get("tool:" + row["account"] + ":" + call["id"])
                if not result or result["tool_name"] != call["name"]:
                    return False
                paired.add(result["call_key"])
    if any(
        row["kind"] == "tool"
        and row["tool_name"] not in {"p3_metric_execution", "verified_report_projection"}
        and row["call_key"] not in paired
        for row in calls
    ):
        return False
    return True


def metric_ref_integrity(payload, request, pins):
    state = payload["snapshot"]["state"]
    version = state["plan_version"]
    key = f"{version}:{request.goal_id}"
    result = TaskResult.model_validate(state["results"][key])
    check = VerificationResult.model_validate(state["verifications"][key])
    Plan.model_validate(state["plan"])
    if (result.run_id, result.task_id, result.plan_version, result.worker) != (
        payload["run_id"],
        request.goal_id,
        version,
        "sql",
    ):
        return False
    expected = (
        "passed"
        if result.status == "succeeded"
        else "unavailable"
        if result.status == "unavailable"
        else "failed"
    )
    if (check.task_id, check.plan_version, check.status) != (request.goal_id, version, expected):
        return False
    origin = version
    if result.reused_from:
        old = TaskResult.model_validate(state["results"][result.reused_from])
        origin = old.plan_version
        if not 1 <= origin < version or state["reuse_origins"].get(key) != result.reused_from:
            return False
        if old.reused_from or old.model_dump(
            exclude={"plan_version", "reused_from"}
        ) != result.model_dump(exclude={"plan_version", "reused_from"}):
            return False
        history = state["plan_history"]
        current_task = next(
            t for t in Plan.model_validate(state["plan"]).tasks if t.task_id == request.goal_id
        )
        old_task = next(
            t
            for t in Plan.model_validate(history[str(origin)]).tasks
            if t.task_id == request.goal_id
        )
        if current_task != old_task:
            return False
    bridges = []
    for ref in result.evidence_refs:
        body = payload["artifacts"][ref.artifact_id]
        artifact = Artifact.model_validate_json(json.dumps(body))
        if digest(body) != ref.sha256 or ref.artifact_id != ref.sha256:
            return False
        if (artifact.run_id, artifact.task_id, artifact.plan_version, artifact.kind) != (
            payload["run_id"],
            request.goal_id,
            origin,
            "metric",
        ):
            return False
        if artifact.metric:
            bridges.append(artifact.metric)
    if len(bridges) != 1:
        return False
    bridge = bridges[0]
    if bridge.request != request:
        return False
    ds = next(
        d
        for d in pins["datasets"].values()
        if (d["schema"]["dataset_id"], d["schema"]["version"])
        == (request.dataset_id, request.dataset_version)
    )
    if bridge.source_sha256 != ds["schema"]["source_sha256"]:
        return False
    if bridge.context:
        metric = next(
            m
            for m in ds["metrics"]
            if (m["metric_id"], m["metric_version"]) == (request.metric_id, request.metric_version)
        )
        if (bridge.context.semantic_sha256, bridge.context.metric_sha256) != (
            ds["semantics"]["definition_sha256"],
            metric["definition_sha256"],
        ):
            return False
    return bridge


def score(task, gold, record, key, pins):
    payload = authenticated(record, key)
    if payload["case_id"] != task.case_id or payload["question_sha256"] != digest(task.question):
        raise ValueError("Wrong collected task identity")
    if gold.host_code:
        ok = (
            payload.get("stage") == "preflight"
            and payload.get("task_sha256") == digest(task)
            and payload.get("preflight_code") == gold.host_code
            and payload.get("model_calls") == 0
            and payload.get("business_queries") == 0
            and payload.get("retrieval_queries") == 0
            and payload.get("report") is None
        )
        return {
            "case_id": task.case_id,
            "strict_correct": ok,
            "status": "blocked",
            "stage": "host_preflight",
            "host_refusal_correct": ok,
            "agent_executed": False,
            "dimensions": {"authorization": ok},
            "failure_class": None if ok else "authorization_denied",
        }
    source_hashes = {
        (d["schema"]["dataset_id"], d["schema"]["version"]): d["schema"]["source_sha256"]
        for d in pins["datasets"].values()
    }
    comparison = gold.model_copy(deep=True)
    comparison.refusal_conditions = []
    basic = score_case(task, comparison, record, key, source_hashes=source_hashes)
    snapshot = payload["snapshot"]
    if not snapshot.get("report") or snapshot["unknown"] or snapshot["next"] or snapshot["review"]:
        return basic | {
            "strict_correct": False,
            "failure_class": failure_class(payload),
        }
    report = CrossSourceReport.model_validate_json(json.dumps(snapshot["report"]))
    claims = {c.goal_id: c for c in report.claims}
    bridges = {}
    for request in task.metrics:
        bridge = metric_ref_integrity(payload, request, pins)
        if not bridge:
            return basic | {"strict_correct": False, "failure_class": "p3_evidence_integrity"}
        published = claims.get(request.goal_id)
        if published and published.kind == "metric" and published.metric != bridge:
            return basic | {"strict_correct": False, "failure_class": "p3_evidence_integrity"}
        bridges[request.goal_id] = bridge
        if bridge.verdict == "verified":
            days = (
                (request.window.end_exclusive - request.window.start).days
                if request.window
                else None
            )
            if (
                bridge.value.window_days != days
                or bridge.verification.request_sha256 != digest(request)
                or bridge.verification.evidence_id != bridge.evidence_id
                or any(check.status != "passed" for check in bridge.verification.checks)
            ):
                return basic | {"strict_correct": False, "failure_class": "p3_evidence_integrity"}
    reasons = all(
        goal in claims and set(codes) <= set(claims[goal].codes)
        for goal, codes in gold.expected_codes.items()
    )
    verdicts = all(
        bridges[goal].verdict == expected for goal, expected in gold.expected_verdicts.items()
    )
    factual = True
    if task.document_goal:
        claim = claims.get(task.document_goal.goal_id)
        factual = bool(claim)
        coverage = claim.fact_coverage if claim else {}
        codes = set(report.business_completion.missing_evidence.get(task.document_goal.goal_id, []))
        factual &= all(
            coverage.get(fact_id) is None
            and (
                "document_fact_unverified:" + fact_id in codes
                or bool(set(gold.document_missing_codes) & codes)
            )
            for fact_id in gold.missing_fact_ids
        )
        for fact in task.document_goal.required_facts:
            if fact.citation:
                support = coverage.get(fact.fact_id)
                factual &= bool(
                    support
                    and support.citation.document_id == fact.citation.document_id
                    and support.citation.version == fact.citation.version
                    and fact.quotation == support.excerpt
                )
    citations = [d for c in report.claims for d in c.documents]
    allowed = {
        (pin.corpus_id, pin.index_version, document)
        for pin in (task.rag_scope.corpora if task.rag_scope else [])
        for document in pin.document_ids
    }
    sources = {d.citation.source_id for d in citations}
    citations_authorized = all(
        (d.citation.corpus_id, d.citation.index_version, d.citation.document_id) in allowed
        for d in citations
    )
    citations_valid = citations_authorized and len(sources) >= gold.minimum_cited_sources
    if gold.retrieval and "relevant_document_ids" in gold.retrieval:
        citations_valid &= all(
            d.citation.document_id in gold.retrieval["relevant_document_ids"] for d in citations
        )
    artifacts_valid = True
    for d in citations:
        body = payload["artifacts"].get(d.artifact_id)
        if not body or digest(body) != d.artifact_id:
            artifacts_valid = False
            continue
        artifact = Artifact.model_validate_json(json.dumps(body))
        artifacts_valid &= bool(
            artifact.documents
            and any(
                original.citation == d.citation and original.text == d.excerpt
                for original in artifact.documents.documents
            )
        )
    if task.document_goal:
        factual &= all(
            any(
                proof.artifact_id == doc.artifact_id
                and proof.citation == doc.citation
                and proof.excerpt in doc.excerpt
                for doc in citations
            )
            for c in report.claims
            for proof in c.fact_coverage.values()
            if proof is not None
        )
    rag = rag_result(payload, task) if task.document_goal else None
    retrieval_correct = True
    if gold.retrieval_expected:
        retrieval_correct = bool(
            rag
            and rag.get("rag_completion")
            and rag["rag_completion"]["submission"]["outcome"] == gold.retrieval_expected
        )
    model = [c for c in payload["calls"] if c["kind"] == "model"]
    counts = Counter(c["account"] for c in model if c["account"] != "root")
    usage = snapshot["usage"]
    reported = sum(c.get("usage", {}).get("total_tokens", 0) for c in model)
    budget = (
        usage["usage_complete"]
        and usage["calls"] == len(model) <= 8
        and usage["total_tokens"] == reported <= 18000
        and all(v <= 4 for v in counts.values())
    )
    chart_valid = all(
        point.metric == bridges.get(point.goal_id) and point.metric.value.unit == chart.unit
        for chart in report.charts
        for point in chart.points
    )
    causal = (
        not task.causal_requested
        or "causal_conclusion_not_verified" in report.business_completion.unconfirmed_claims
    )
    dimensions = {
        "business": basic["strict_correct"],
        "p3_numeric": all(n["correct"] for n in basic["numeric"]) if task.metrics else None,
        "evidence": artifacts_valid,
        "p3_semantics": verdicts,
        "citations": citations_valid if task.document_goal else None,
        "fact_coverage": factual if task.document_goal else None,
        "authorization": citations_authorized,
        "protocol": call_integrity(payload),
        "completion": report.business_completion.status == gold.business_completion,
        "budget": budget,
        "durable": not snapshot["unknown"],
        "business_refusal": reasons,
        "causal": causal,
        "chart_units": chart_valid,
        "retrieval_contract": retrieval_correct if task.document_goal else None,
    }
    ok = all(value is not False for value in dimensions.values())
    return basic | {
        "strict_correct": ok,
        "dimensions": dimensions,
        "failure_class": None
        if ok
        else "rag_retrieval_failure"
        if not retrieval_correct
        else "document_fact_unverified"
        if not factual
        else "p3_verification_failure"
        if not verdicts or not reasons
        else "budget_exceeded"
        if not budget
        else "business_or_evidence_mismatch",
        "retrieval_worker_complete": bool(rag and rag["status"] == "succeeded"),
        "business_completed": report.business_completion.status == "completed",
        "source_coverage": len(sources),
        "required_fact_coverage_separate": {
            k: v is not None for c in report.claims for k, v in c.fact_coverage.items()
        },
        "retrieval_quality": retrieval_scores(payload, gold) if task.document_goal else None,
        "safety_violation": not artifacts_valid
        or not citations_authorized
        or (report.business_completion.status == "completed" and not basic["strict_correct"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("record")
    parser.add_argument("key")
    args = parser.parse_args()
    verify()
    tasks, pins, _ = load()
    answers = read_answers()
    from pathlib import Path

    record = json.loads(Path(args.record).read_bytes())
    task = next(t for t in tasks if t.case_id == record["payload"]["case_id"])
    print(json.dumps(score(task, answers[task.case_id], record, Path(args.key).read_bytes(), pins)))
