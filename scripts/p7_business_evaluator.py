"""Trusted offline scoring of signed Inspector output; never given to a candidate."""

import argparse
import json
import math
from decimal import Decimal
from pathlib import Path

from p7_business_scoring import authenticated, score_case
from p7_holdout_pack import sha

from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact, Plan, TaskResult, VerificationResult
from datapilot.orchestration.rag_completion import goal_hash, retrieval_goal
from datapilot.reporting.contracts import CrossSourceReport

REASONS = {
    "currency_not_supported": {"currency_unsupported"},
    "recurring_contract_definition_missing": {"mrr_definition_missing"},
    "complete_contract_history_missing": {"history_unconfirmed"},
    "amount_unit_unconfirmed": {"amount_unit_unconfirmed"},
    "zero_denominator": {"zero_denominator"},
    "duplicate_record_grain": {"duplicate_record_grain", "duplicate_grain"},
    "outside_confirmed_coverage": {"outside_coverage"},
}


def ranks(actual, relevant, k=3):
    actual, relevant = list(dict.fromkeys(actual))[:k], set(relevant)
    hits = [i for i, id_ in enumerate(actual, 1) if id_ in relevant]
    return {
        "recall_at_k": len(hits) / len(relevant) if relevant else None,
        "precision_at_k": len(hits) / k,
        "precision_returned": len(hits) / len(actual) if actual else None,
        "mrr_at_k": 1 / hits[0] if hits else 0,
        "returned": len(actual),
        "k": k,
    }


def retrieval_scores(payload, gold):
    result = []
    artifacts = payload.get("artifacts", {})
    for call in sorted(payload.get("calls", []), key=lambda c: c["call_key"]):
        if call["tool_name"] != "search_documents" or call["status"] != "complete":
            continue
        feedback = call["payload"]
        feedback = json.loads(feedback["ordered_json"]) if "ordered_json" in feedback else feedback
        docs = []
        for ref in feedback.get("artifact_refs", []):
            item = artifacts.get(ref["artifact_id"])
            if not item or digest(item) != ref["sha256"]:
                raise ValueError("Retrieval artifact missing or changed")
            docs.extend((item.get("documents") or {}).get("documents", []))
        levels = {}
        for kind in ("chunk", "document", "source"):
            actual = [d["citation"][kind + "_id"] for d in docs]
            levels[kind] = ranks(
                actual, (gold.retrieval or {}).get("relevant_" + kind + "_ids", [])
            )
        result.append({"query_id": call["call_key"], "levels": levels})
    return result


def score_preflight(task, gold, payload):
    """Only exact host rejection evidence; runtime failures cannot become legal refusal."""
    reason = payload.get("preflight_code")
    expected = (
        {"REPORT_SCOPE_INVALID", "DOCUMENT_NOT_AUTHORIZED", "DATASET_NOT_AUTHORIZED"}
        if gold.host_decision == "permission_denied"
        else {"VERSION_NOT_AUTHORIZED", "REPORT_SCOPE_INVALID"}
        if gold.host_decision == "confirmation_required"
        else set()
    )
    correct = (
        payload.get("stage") == "preflight"
        and payload.get("case_id") == task.case_id
        and payload.get("task_sha256") == digest(task)
        and reason in expected
        and payload.get("model_calls") == 0
        and payload.get("business_queries") == 0
        and payload.get("retrieval_queries") == 0
        and payload.get("report") is None
        and gold.business_completion == "blocked"
    )
    return {
        "model_mode": payload.get("model_mode"),
        "live_authorized": bool(payload.get("live_authorization_ref")),
        "case_id": task.case_id,
        "strict_correct": correct,
        "status": "blocked",
        "execution_stage": "preflight",
        "reason": reason,
        "retrieval_obligation": False,
    }


def gold_contract_supported(gold):
    """Closed refusal vocabulary, shared by admission and actual offline scoring."""
    known = set(REASONS) | {
        "document_evidence_insufficient",
        "causal_effect_not_identified",
        "host_scope_denied",
        "version_confirmation_required",
    }
    expected_reasons = {g.reason for g in gold.metrics if g.disposition == "unavailable"}
    if gold.retrieval and gold.retrieval["disposition"] != "complete":
        expected_reasons.add("document_evidence_insufficient")
    if gold.causal_claim_must_remain_unverified:
        expected_reasons.add("causal_effect_not_identified")
    if gold.host_decision == "permission_denied":
        expected_reasons.add("host_scope_denied")
    if gold.host_decision == "confirmation_required":
        expected_reasons.add("version_confirmation_required")
    return (
        not (set(gold.refusal_conditions) - known)
        and set(gold.refusal_conditions) == expected_reasons
    )


def rag_result(payload, task):
    """Resolve only the current delegated task; signed history is not a latest-result search."""
    try:
        state = payload["snapshot"]["state"]
        version, goal = state["plan_version"], task.document_goal.goal_id
        if (
            type(version) is not int
            or not 1 <= version <= 10
            or (state["run_id"], state["question"]) != (payload["run_id"], task.question)
        ):
            raise ValueError("Wrong current task identity")
        plan = Plan.model_validate(state["plan"])
        history = state["plan_history"]
        if Plan.model_validate(history[str(version)]) != plan:
            raise ValueError("Current plan differs from authoritative history")
        spec = next((t for t in plan.tasks if t.task_id == goal), None)
        if spec is None or spec.worker != "rag":
            raise ValueError("Document goal was not delegated to RAG")
        current = f"{version}:{goal}"
        result = TaskResult.model_validate(state["results"][current])
        if (result.run_id, result.task_id, result.plan_version, result.worker) != (
            payload["run_id"],
            goal,
            version,
            "rag",
        ):
            raise ValueError("Result differs from current delegation")
        verified = VerificationResult.model_validate(state["verifications"][current])
        expected = {"succeeded": "passed", "unavailable": "unavailable"}.get(
            result.status, "failed"
        )
        if (verified.task_id, verified.plan_version, verified.status) != (goal, version, expected):
            raise ValueError("Result has no matching orchestration verification")
        origin = version
        if result.reused_from:
            old = state["results"][result.reused_from]
            prior = TaskResult.model_validate(old)
            origin = prior.plan_version
            old_plan = Plan.model_validate(history[str(origin)])
            origin_check = VerificationResult.model_validate(
                state["verifications"][result.reused_from]
            )
            if (
                not 1 <= origin < version
                or result.reused_from != f"{origin}:{goal}"
                or state["reuse_origins"].get(current) != result.reused_from
                or next((t for t in old_plan.tasks if t.task_id == goal), None) != spec
                or prior.reused_from is not None
                or (origin_check.task_id, origin_check.plan_version, origin_check.status)
                != (goal, origin, expected)
                or prior.model_dump(exclude={"plan_version", "reused_from"})
                != result.model_dump(exclude={"plan_version", "reused_from"})
            ):
                raise ValueError("Stale result reuse was not authorized for this plan")
        for ref in result.evidence_refs:
            item = payload["artifacts"][ref.artifact_id]
            artifact = Artifact.model_validate(item)
            if (
                digest(item) != ref.sha256
                or ref.artifact_id != ref.sha256
                or ref.kind != "documents"
                or (artifact.run_id, artifact.task_id, artifact.plan_version, artifact.kind)
                != (payload["run_id"], goal, origin, "documents")
            ):
                raise ValueError(
                    "Task evidence is missing, changed or belongs to another delegation"
                )
        if result.status in {"succeeded", "unavailable"}:
            receipt = result.rag_completion
            expected_goal = retrieval_goal(task.document_goal.question)
            if (
                receipt is None
                or payload["manifest"].get("rag_completion_goal") != expected_goal
                or receipt.goal_sha256 != goal_hash(expected_goal)
                or len({r.artifact_id for r in result.evidence_refs}) != len(result.evidence_refs)
                or len(set(receipt.submission.artifact_ids)) != len(receipt.submission.artifact_ids)
                or set(receipt.submission.artifact_ids)
                != {r.artifact_id for r in result.evidence_refs}
                or (result.status == "succeeded") != (receipt.submission.outcome == "complete")
                or (receipt.verdict in {"literal_locator", "semantic_retrieval"})
                != (result.status == "succeeded")
            ):
                raise ValueError("Completion receipt differs from task outcome, goal or evidence")
            # Same committed model/tool pairing as Journal.validate_rag_receipt, offline only.
            calls = payload["calls"]
            rows = [c for c in calls if c["call_key"] == f"tool:{origin}:{goal}:{receipt.call_id}"]
            if (
                len(rows) != 1
                or rows[0]["status"] != "complete"
                or (rows[0]["kind"], rows[0]["account"], rows[0]["tool_name"])
                != ("tool", f"{origin}:{goal}", "submit_rag_result")
            ):
                raise ValueError("No matching committed completion call")
            body = rows[0]["payload"]
            if digest(body) != rows[0]["payload_hash"] or (
                json.loads(body["ordered_json"]) if "ordered_json" in body else body
            ).get("rag_completion") != receipt.model_dump(mode="json"):
                raise ValueError("Committed receipt differs from task result")
            models = [
                c
                for c in calls
                if c["kind"] == "model"
                and c["status"] == "complete"
                and c["account"] == f"{origin}:{goal}"
                and c["payload_hash"] == receipt.model_response_sha256
            ]
            if (
                len(models) != 1
                or digest(models[0]["payload"]) != receipt.model_response_sha256
                or not any(
                    c["id"] == receipt.call_id
                    and c["name"] == "submit_rag_result"
                    and c["args"] == receipt.submission.model_dump(mode="json")
                    for c in models[0]["payload"]["data"]["tool_calls"]
                )
            ):
                raise ValueError("Completion has no matching committed model call")
        return result.model_dump(mode="json")
    except (KeyError, TypeError) as exc:
        raise ValueError("Missing current task identity, version or evidence") from exc


def score(task, gold, record, key, *, source_hashes, rule=None):
    if task.case_id != gold.case_id:
        raise ValueError("Gold belongs to another task")
    payload = authenticated(record, key)
    if not gold_contract_supported(gold):
        return {
            "case_id": task.case_id,
            "strict_correct": False,
            "requires_human_adjudication": True,
            "failure_class": "unregistered_scoring_contract",
            "status": "blocked",
        }
    lineage = payload.get("lineage")
    rule = rule or {}
    if rule.get("execution_phase") == "preflight":
        return score_preflight(task, gold, payload)
    if payload.get("stage") == "preflight":
        return {
            "case_id": task.case_id,
            "strict_correct": False,
            "status": "blocked",
            "failure_class": "engineering_preflight_not_expected_business_refusal",
        }
    # Refusal meaning is checked below using original structured missing codes and receipts.
    comparison = gold.model_copy(deep=True)
    comparison.refusal_conditions = []
    if comparison.retrieval and comparison.retrieval["disposition"] != "complete":
        comparison.retrieval["facts"] = []  # Reference background, not a published complete answer.
    basic = score_case(task, comparison, record, key, source_hashes=source_hashes)
    if (
        payload["snapshot"]["unknown"]
        or payload["snapshot"]["next"]
        or payload["snapshot"]["review"]
        or not payload["snapshot"].get("report")
    ):
        return basic | {
            "strict_correct": False,
            "failure_class": "execution_incomplete",
            "model_mode": payload.get("model_mode"),
            "live_authorized": bool(payload.get("live_authorization_ref")),
        }
    report = CrossSourceReport.model_validate_json(json.dumps(payload["snapshot"]["report"]))
    claims = {c.goal_id: c for c in report.claims}
    refusals = []
    for goal in gold.metrics:
        if goal.disposition != "unavailable":
            continue
        claim = claims.get(goal.goal_id)
        allowed = REASONS.get(goal.reason, set())
        refusals.append(bool(claim and claim.kind == "unavailable" and set(claim.codes) & allowed))
    rag = rag_result(payload, task) if task.document_goal else {}
    if gold.retrieval and gold.retrieval["disposition"] != "complete":
        doc = claims.get(task.document_goal.goal_id)
        receipt = rag.get("rag_completion") or {}
        refusals.append(
            bool(
                doc
                and doc.kind == "unavailable"
                and rag.get("status") == "unavailable"
                and receipt.get("verdict") in {"empty", "insufficient"}
            )
        )
    if gold.causal_claim_must_remain_unverified:
        refusals.append(
            "causal_conclusion_not_verified" in report.business_completion.unconfirmed_claims
        )
    # Published sources must be relevant; raw retrieval may contain distractors.
    allowed_docs = set((gold.retrieval or {}).get("relevant_document_ids", []))
    citations = [d for c in report.claims for d in c.documents]
    citations_valid = all(d.citation.document_id in allowed_docs for d in citations)
    chart_valid = True
    bridges = {c.goal_id: c.metric for c in report.claims if c.kind == "metric"}
    for chart in report.charts:
        chart_valid = chart_valid and all(
            p.goal_id in bridges
            and p.metric == bridges[p.goal_id]
            and p.metric.value.unit == chart.unit
            for p in chart.points
        )
    lineage_valid = not rule.get("customer_linkage_and_invoice_grain")
    if not lineage_valid:
        # Only host Collector evidence bound to this Run and P3 source can satisfy JOIN.
        lineage_valid = bool(
            lineage
            and lineage.get("run_id") == payload["run_id"]
            and lineage.get("question_sha256") == payload["question_sha256"]
            and lineage.get("verified") is True
            and lineage.get("query_refs")
            and lineage.get("evidence_ids") == sorted(b.evidence_id for b in bridges.values())
        )
        if lineage_valid:
            lineage_valid = validate_lineage(lineage, next(iter(bridges.values())))
    return basic | {
        "model_mode": payload.get("model_mode"),
        "live_authorized": bool(payload.get("live_authorization_ref")),
        "strict_correct": basic["strict_correct"]
        and all(refusals)
        and citations_valid
        and chart_valid
        and lineage_valid,
        "failure_class": None
        if basic["strict_correct"]
        and all(refusals)
        and citations_valid
        and chart_valid
        and lineage_valid
        else "business_or_evidence_mismatch",
        "requires_human_adjudication": False,
        "structured_refusals_correct": all(refusals),
        "citations_valid": citations_valid,
        "chart_units_valid": chart_valid,
        "lineage_valid": lineage_valid,
        "retrieval_quality": retrieval_scores(payload, gold),
        "rag_worker_complete": rag.get("status") == "succeeded"
        and (rag.get("rag_completion") or {}).get("verdict")
        in {"literal_locator", "semantic_retrieval"},
        "report_required_fact_coverage": basic.get("required_fact_coverage"),
    }


def validate_lineage(lineage, bridge):
    """Recompute signed post-run JOIN checks, keeping P3 Evidence/Verification unchanged."""
    from datapilot.datasets.contracts import DatasetQueryResult
    from datapilot.tools.sql import SQLPolicy, validate_sql

    try:
        if (lineage["dataset_id"], lineage["dataset_version"], lineage["source_sha256"]) != (
            bridge.request.dataset_id,
            bridge.request.dataset_version,
            bridge.source_sha256,
        ):
            return False
        refs = lineage["query_refs"]
        if len(refs) != 4:
            return False
        checked = []
        import sqlglot
        from sqlglot import exp

        tables = {
            t.name
            for ref in refs
            for t in sqlglot.parse_one(ref["sql"], read="postgres").find_all(exp.Table)
        }
        if bridge.context.table.physical_name not in tables or len(tables) != 2:
            return False
        for ref in refs:
            result = DatasetQueryResult.model_validate_json(json.dumps(ref["result"]))
            sql = validate_sql(ref["sql"], SQLPolicy("uploads", frozenset(tables)))
            if (result.dataset_id, result.version, result.source_sha256) != (
                bridge.request.dataset_id,
                bridge.request.dataset_version,
                bridge.source_sha256,
            ):
                return False
            if (
                sha(sql.encode()) != ref["query_sha256"]
                or result.query_sha256 != ref["query_sha256"]
                or digest(result.result.model_dump(mode="json", exclude={"elapsed_ms"}))
                != ref["result_sha256"]
                or result.result_sha256 != ref["result_sha256"]
                or result.result.truncated
                or result.result.row_count != 1
            ):
                return False
            checked.append(result.result.rows[0])
        grain = (
            checked[0][0] == checked[0][1] == checked[2][0] == checked[2][1]
            and checked[1][0] == checked[1][1]
        )
        value = Decimal(str(checked[3][0]))
        if bridge.context.entity.amount_storage == "minor":
            value /= 100
        return grain and value == Decimal(bridge.value.value)
    except (ValueError, KeyError, IndexError, StopIteration, TypeError):
        return False


def wilson(success, total):
    if not total:
        return None
    z = 1.959963984540054
    p = success / total
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return [
        (p + z * z / (2 * total) - half) / (1 + z * z / total),
        (p + z * z / (2 * total) + half) / (1 + z * z / total),
    ]


def quantile(values, q):
    return sorted(values)[math.ceil(q * len(values)) - 1] if values else None


def summarize(tasks, observations, *, mode):
    if mode not in {"live", "toy"} or set(observations) - {t.case_id for t in tasks}:
        raise ValueError("Mode/case denominator differs")
    if mode == "live" and any(
        not r.get("live_authorized")
        or (
            r.get("model_mode") != "live"
            and not (
                r.get("execution_stage") == "preflight" and r.get("model_mode") == "not_invoked"
            )
        )
        for r in observations.values()
    ):
        raise ValueError("Fake/unauthorized results cannot be counted as Live")
    rows = []
    for lane in ("sql_only", "rag_only", "sql_rag"):
        ids = [t.case_id for t in tasks if t.lane == lane]
        seen = [observations[i] for i in ids if i in observations]
        passed = sum(r["strict_correct"] for r in seen)
        rows.append(
            {
                "lane": lane,
                "planned": len(ids),
                "observed": len(seen),
                "not_run": len(ids) - len(seen),
                "correct": passed,
                "observed_rate": passed / len(seen) if seen else None,
                "planned_rate": passed / len(ids) if seen and ids else None,
                "ci95_observed_wilson": wilson(passed, len(seen)),
            }
        )
    return {
        "mode": mode,
        "formal_live_status": "not_run" if mode != "live" or not observations else "observed",
        "planned": len(tasks),
        "observed": len(observations),
        "lanes": rows,
        "all_missing_cases_retained": [t.case_id for t in tasks if t.case_id not in observations],
        "live_success_rate": sum(r["strict_correct"] for r in observations.values()) / len(tasks)
        if mode == "live" and observations and tasks
        else None,
    }


def usage_summary(collections, rates=None):
    calls, latencies, unknown = 0, [], 0
    tokens = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_miss": 0}
    cache_known = True
    for payload in collections:
        for call in payload.get("calls", []):
            if call["kind"] != "model":
                continue
            calls += 1
            usage = call.get("usage") or {}
            if call["status"] != "complete" or any(
                type(usage.get(k)) is not int or usage[k] < 0
                for k in ("input_tokens", "output_tokens")
            ):
                unknown += 1
                continue
            tokens["input_tokens"] += usage["input_tokens"]
            tokens["output_tokens"] += usage.get("output_tokens", 0)
            if call.get("elapsed_ms") is not None:
                latencies.append(call["elapsed_ms"])
            # Provider cache data is preserved in original response payload, not fabricated.
            message = call.get("payload") or {}
            metadata = message.get("data", message).get("response_metadata", {})
            details = metadata.get("token_usage", {})
            hit, miss = (
                details.get("prompt_cache_hit_tokens"),
                details.get("prompt_cache_miss_tokens"),
            )
            if type(hit) is not int or type(miss) is not int:
                cache_known = False
            else:
                tokens["cache_read"] += hit
                tokens["cache_miss"] += miss
    estimate = None
    active = [p for p in collections if any(c["kind"] == "model" for c in p.get("calls", []))]
    real = bool(active) and all(p.get("model_mode") == "live" for p in active)
    unresolved = sum(bool(p.get("unresolved_dispatch")) for p in collections)
    if rates and not unknown and cache_known and real and not unresolved:
        estimate = str(
            (
                Decimal(tokens["cache_read"]) * Decimal(rates["input_hit"])
                + Decimal(tokens["cache_miss"]) * Decimal(rates["input_miss"])
                + Decimal(tokens["output_tokens"]) * Decimal(rates["output"])
            )
            / Decimal(1000000)
        )
    return {
        "usage_kind": "unresolved_provider_usage"
        if unresolved
        else "provider_reported"
        if real
        else "fake_or_scripted_not_provider_tokens",
        "model_calls": calls,
        "unresolved_dispatches": sum(bool(p.get("unresolved_dispatch")) for p in collections),
        "model_call_count_complete": not any(p.get("unresolved_dispatch") for p in collections),
        "known_tokens": tokens,
        "unknown_usage_calls": unknown,
        "provider_cache_complete": cache_known if calls else None,
        "attempt_latency_ms": {
            "n": len(latencies),
            "p50": quantile(latencies, 0.5),
            "p95": quantile(latencies, 0.95),
        },
        "estimated_usd": estimate,
        "actual_bill_usd": None,
        "price_snapshot_hash": sha(json.dumps(rates, sort_keys=True).encode()) if rates else None,
    }


def campaign_check():
    from p7_business_v2 import BASE, DEST, load_v2
    from p7_gate2b import write_new
    from p7_holdout_pack import Gold

    tasks, pins, anchor = load_v2()
    golds = [
        Gold.model_validate_json(line) for line in (DEST / "gold.jsonl").read_bytes().splitlines()
    ]
    rules = json.loads((DEST / "acceptance-rules.json").read_bytes())
    rows = []
    for task, gold in zip(tasks, golds, strict=True):
        if task.case_id != gold.case_id:
            raise ValueError("Wrong Gold identity")
        unknown = [
            g.reason
            for g in gold.metrics
            if g.disposition == "unavailable" and g.reason not in REASONS
        ]
        rule = rules["cases"].get(task.case_id, rules["default"])
        if unknown or not gold_contract_supported(gold):
            raise ValueError("Unreviewed refusal vocabulary must not be automatically scored")
        rows.append(
            {
                "case_id": task.case_id,
                "schema_supported": True,
                "execution_phase": rule.get("execution_phase", "runtime"),
                "customer_linkage_required": rule.get("customer_linkage_and_invoice_grain", False),
                "chart_units_if_present": rule.get("chart_units_if_present", False),
                "conditional_document_facts": rule.get(
                    "retrieval_facts_are_conditional_reference_only", False
                ),
            }
        )
    if len(rows) != 60:
        raise ValueError("Do not reduce denominator")
    receipt = {
        "seal_sha256": anchor["seal_sha256"],
        "cases": rows,
        "scoring_schema_check": "passed",
        "scored_business_runs": 0,
        "source_hash_bindings": len(pins["datasets"]),
        "live": "not_run",
        "negative_retrieval_facts": "ranking reference; not a published complete document answer",
        "reason_mapping": {k: sorted(v) for k, v in REASONS.items()},
    }
    from uuid import uuid4

    receipt_path = BASE / (
        "scoring-admission.json"
        if not (BASE / "scoring-admission.json").exists()
        else "scoring-admission-" + uuid4().hex + ".json"
    )
    write_new(receipt_path, receipt)
    print(json.dumps({"scoring_contracts": 60, "business_runs_scored": 0}))


def evaluate_collections(directory):
    from p7_business_v2 import DEST, load_v2
    from p7_holdout_pack import Gold

    tasks, pins, anchor = load_v2()
    golds = {
        g.case_id: g
        for g in (
            Gold.model_validate_json(line)
            for line in (DEST / "gold.jsonl").read_bytes().splitlines()
        )
    }
    rules = json.loads((DEST / "acceptance-rules.json").read_bytes())
    sources = {
        (p["dataset_id"], p["dataset_version"]): p["source_sha256"]
        for p in pins["datasets"].values()
    }
    key = (directory / "collector.key").read_bytes()
    observations, collections = {}, []
    for task in tasks:
        path = directory / (task.case_id + ".json")
        if not path.exists():
            continue
        record = json.loads(path.read_bytes())
        payload = authenticated(record, key)
        if (
            (
                payload.get("model_mode") != "live"
                and not (
                    payload.get("stage") == "preflight"
                    and payload.get("model_mode") == "not_invoked"
                )
            )
            or payload.get("campaign_pack_sha256") != anchor["seal_sha256"]
            or not payload.get("live_authorization_ref")
        ):
            raise ValueError("Fake/unsigned campaign authority cannot be reported as Live")
        collections.append(payload)
        observations[task.case_id] = score(
            task,
            golds[task.case_id],
            record,
            key,
            source_hashes=sources,
            rule=rules["cases"].get(task.case_id, rules["default"]),
        )
    summary = summarize(tasks, observations, mode="live")
    summary["usage"] = usage_summary(collections)
    summary["quality"] = quality_summary(golds, observations, rules)
    # Whole-campaign scoring is offline; no task is resumed or retried here.
    with (directory / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump({"summary": summary, "cases": observations}, stream, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {"planned": 60, "collected": len(observations), "live": summary["formal_live_status"]}
        )
    )


def quality_summary(golds, observations, rules):
    """Separate business, numeric, citation, retrieval, and execution denominators."""
    numeric = [
        n
        for r in observations.values()
        for n in r.get("numeric", [])
        if n["expected"] == "verified"
    ]
    facts = [
        r["report_required_fact_coverage"]
        for r in observations.values()
        if r.get("report_required_fact_coverage")
    ]
    relevant_rag = {
        id_
        for id_, g in golds.items()
        if g.retrieval
        and rules["cases"].get(id_, rules["default"])["execution_phase"] != "preflight"
    }
    rag_seen = [observations[id_] for id_ in relevant_rag if id_ in observations]
    ranking = {}
    for level in ("chunk", "document", "source"):
        values = [
            query["levels"][level] for row in rag_seen for query in row.get("retrieval_quality", [])
        ]
        ranking[level] = {
            "queries": len(values),
            **{
                name: (
                    sum(v[name] for v in values if v[name] is not None)
                    / sum(v[name] is not None for v in values)
                    if any(v[name] is not None for v in values)
                    else None
                )
                for name in ("recall_at_k", "precision_at_k", "mrr_at_k")
            },
        }
    return {
        "numeric": {
            "planned_goals": sum(
                g.disposition == "verified" for a in golds.values() for g in a.metrics
            ),
            "observed_goals": len(numeric),
            "correct": sum(n["correct"] for n in numeric),
            "observed_rate": sum(n["correct"] for n in numeric) / len(numeric) if numeric else None,
        },
        "published_required_fact_coverage": {
            "covered": sum(f["covered"] for f in facts),
            "required_observed": sum(f["required"] for f in facts),
        },
        "rag": {
            "planned_runtime_tasks": len(relevant_rag),
            "observed_tasks": len(rag_seen),
            "worker_retrieval_complete": sum(r.get("rag_worker_complete", False) for r in rag_seen),
            "strict_business_correct": sum(r["strict_correct"] for r in rag_seen),
            "per_level_macro_per_query": ranking,
        },
        "failures": {
            kind: sum(r.get("failure_class") == kind for r in observations.values())
            for kind in {r.get("failure_class") for r in observations.values()}
            if kind
        },
        "status_counts": {
            status: sum(r.get("status") == status for r in observations.values())
            for status in {r.get("status") for r in observations.values()}
            if status
        },
        "business_completion_not_equated_to_retrieval": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "score"])
    parser.add_argument("--collections", type=Path)
    options = parser.parse_args()
    if options.action == "check":
        campaign_check()
    elif options.collections:
        evaluate_collections(options.collections)
    else:
        parser.error("--collections required for score")
