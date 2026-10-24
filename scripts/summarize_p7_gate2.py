"""Read-only Gate 2 scoring and original PG receipt audit. Never invokes a model."""

import argparse
import hashlib
import json
import os
import platform
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from evaluate_gate2 import BASE, BATCH_SIZES, PLAN, STRATEGIES, load_cases, receipts, summarize
from p7_isolated_pg import environment, inspect

from datapilot.config import Settings
from datapilot.evaluation import IntentGold, IntentObservation, percentile
from datapilot.ingestion.common import digest
from datapilot.persistence.backend import Backend, execute

ROOT = Path(__file__).resolve().parents[1]


def provider_totals(calls):
    names = ("input_tokens", "output_tokens", "total_tokens")
    totals = dict.fromkeys((*names, "cache_read", "cache_miss_derived", "cache_miss_reported"), 0)
    for call in calls:
        usage = call.get("usage") or {}
        cache = usage.get("input_token_details", {}).get("cache_read")
        if any(type(usage.get(k)) is not int or usage[k] < 0 for k in names):
            return dict.fromkeys(totals)
        if type(cache) is not int or not 0 <= cache <= usage["input_tokens"]:
            return dict.fromkeys(totals)
        if usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]:
            raise ValueError("Provider input/output/total disagree")
        for name in names:
            totals[name] += usage[name]
        totals["cache_read"] += cache
        totals["cache_miss_derived"] += usage["input_tokens"] - cache
        reported = call.get("provider_token_usage", {}).get("prompt_cache_miss_tokens")
        if type(reported) is int and reported >= 0:
            if reported + cache != usage["input_tokens"]:
                raise ValueError("Provider cache hit/miss disagree with input tokens")
            if totals["cache_miss_reported"] is not None:
                totals["cache_miss_reported"] += reported
        else:
            totals["cache_miss_reported"] = None
    return totals


def estimated_cost(totals, pricing):
    if any(totals[k] is None for k in ("cache_read", "cache_miss_derived", "output_tokens")):
        return None
    return str(
        (
            Decimal(totals["cache_read"]) * Decimal(pricing["input_cache_hit_usd"])
            + Decimal(totals["cache_miss_derived"]) * Decimal(pricing["input_cache_miss_usd"])
            + Decimal(totals["output_tokens"]) * Decimal(pricing["output_usd"])
        )
        / Decimal(1000000)
    )


def audit_batch(settings, plan, strategy, batch, record, selected):
    owner = "p7-intent-holdout"
    run_id = str(uuid5(NAMESPACE_URL, owner + plan["campaign_id"] + strategy + str(batch)))
    if record["run_id"] != run_id or not record["complete"] or record["error_code"]:
        raise ValueError("Do not score a wrong or unfinished batch as complete")
    backend = Backend(settings.runtime_database_url.get_secret_value(), run_id, owner)
    try:
        with backend.transaction() as conn:
            registered = backend.authorize(conn)
            manifest = registered["manifest"]
            if (
                digest(manifest) != record["manifest_sha256"]
                or manifest["plan_sha256"] != digest(plan)
                or manifest["selected_sha256"] != digest(selected)
                or (manifest["strategy"], manifest["batch"]) != (strategy, batch)
            ):
                raise ValueError("Frozen manifest/cases differ from persisted campaign")
            ledger = execute(
                conn, "SELECT payload FROM execution.ledger WHERE run_id=:r", r=run_id
            ).scalar_one()
            calls = (
                execute(conn, "SELECT * FROM execution.calls WHERE run_id=:r", r=run_id)
                .mappings()
                .all()
            )
        state = ledger["state"]
        if digest(state) != ledger["sha256"] or state["pending"]:
            raise ValueError("Invalid or pending budget")
        account = state["accounts"]["root"]
        if account["limits"] != {"calls": len(selected), "tokens": 75000}:
            raise ValueError("Persisted campaign limits changed")
        if account["usage"] != record["ledger"] or len(calls) != record["ledger"]["calls"]:
            raise ValueError("Observer/ledger/call counts disagree")
        for call in calls:
            usage = (call["usage"] or {}).get("total_tokens")
            receipt = state["receipts"].get(call["ticket"])
            if call["kind"] != "model" or call["status"] != "complete":
                raise ValueError("Unknown outcomes cannot become successful Live observations")
            if not receipt or receipt[:2] != ["settled", usage]:
                raise ValueError("Call settlement differs from persistent ledger")
        exported = receipts(backend)  # Checks every original payload hash, without publishing text.
        if exported != record["model_receipts"]:
            raise ValueError("Exported provider receipts differ from PostgreSQL")
        by_key = {call["call_key"]: call for call in calls}
        for call in exported:
            raw = by_key[call["call_key"]]["payload"]["data"].get("response_metadata", {})
            call["provider_token_usage"] = {
                k: v
                for k, v in raw.get("token_usage", {}).items()
                if k
                in {
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "prompt_cache_hit_tokens",
                    "prompt_cache_miss_tokens",
                }
                and type(v) is int
                and v >= 0
            }
        totals = provider_totals(exported)
        if totals["total_tokens"] is not None and (
            totals["total_tokens"] != account["usage"]["reported_tokens"]
            or totals["total_tokens"] != account["usage"]["total_tokens"]
        ):
            raise ValueError("Known provider usage differs from persistent charge")
        return exported, {
            "run_id": run_id,
            "batch": batch,
            "manifest_sha256": record["manifest_sha256"],
            "ledger_sha256": digest(ledger),
            "model_calls": len(calls),
            "unknown_outcomes": 0,
            "pending_reservations": 0,
            "payload_hashes_checked": len(calls),
        }
    finally:
        backend.close()


def main(destination):
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    cases = load_cases(plan)
    gold = {c["case_id"]: IntentGold.model_validate_json(json.dumps(c["expected"])) for c in cases}
    pricing = json.loads((ROOT / "docs/research/p7-gate2-pricing.json").read_text(encoding="utf-8"))
    if datetime.fromisoformat(plan["approved_at"]).weekday() != 5:
        raise ValueError("Recheck dated prices instead of assuming Saturday off-peak")
    container = inspect()
    os.environ.update(environment())
    settings = Settings(llm_mode="fake")  # This command cannot construct a model transport.
    results, bad_cases, all_calls = {}, [], []
    baseline = json.loads((BASE / "rule-only.json").read_text(encoding="utf-8"))
    records = {
        "rule_only": [
            IntentObservation.model_validate_json(json.dumps(o)) for o in baseline["observations"]
        ]
    }
    for strategy in STRATEGIES:
        observations, calls, audits = [], [], []
        for batch, size in enumerate(BATCH_SIZES):
            start = sum(BATCH_SIZES[:batch])
            selected = cases[start : start + size]
            record = json.loads(
                (BASE / f"{strategy}-batch-{batch}.json").read_text(encoding="utf-8")
            )
            original, audit = audit_batch(settings, plan, strategy, batch, record, selected)
            audits.append(audit)
            calls.extend(original)
            observations.extend(
                IntentObservation.model_validate_json(json.dumps(o)) for o in record["observations"]
            )
        if sum(o.model_calls for o in observations) != len(calls):
            raise ValueError("Per-task model call count differs from provider receipts")
        records[strategy] = observations
        totals = provider_totals(calls)
        results[strategy] = {
            "provider_usage": totals,
            "estimated_cost_usd": estimated_cost(totals, pricing),
            "billed_cost_usd": None,
            "cost_source": pricing,
            "audited_batches": audits,
            "model_receipts": calls,
            "model_attempt_ms": {
                "p50": percentile([c["elapsed_ms"] for c in calls], 0.5),
                "p95": percentile([c["elapsed_ms"] for c in calls], 0.95),
                "samples": len(calls),
            },
        }
        all_calls.extend(calls)
    for strategy, observations in records.items():
        if [o.case_id for o in observations] != [c["case_id"] for c in cases]:
            raise ValueError("Missing, repeated or reordered formal task identity")
        if any(o.expected != gold[o.case_id] for o in observations):
            raise ValueError("Original Gold was changed during observation")
        results.setdefault(strategy, {}).update(summary=summarize(observations, len(cases)))
        for o in observations:
            if o.actual != o.expected or o.error_code:
                bad_cases.append(
                    {
                        "case_id": o.case_id,
                        "strategy": strategy,
                        "category": next(c["category"] for c in cases if c["case_id"] == o.case_id),
                        "expected_action": o.expected.action,
                        "observed_action": o.actual.action if o.actual else None,
                        "error_code": o.error_code,
                        "no_retry_or_retuning": True,
                    }
                )
        observations_path = BASE / f"{strategy}-observations.jsonl"
        data = "".join(
            json.dumps(o.model_dump(mode="json"), ensure_ascii=False) + "\n" for o in observations
        )
        if observations_path.exists():
            if observations_path.read_text(encoding="utf-8") != data:
                raise ValueError("Original observation JSONL differs")
        else:
            observations_path.write_text(data, encoding="utf-8", newline="\n")
    totals = provider_totals(all_calls)
    if len(all_calls) > plan["total_max_calls"] or (
        totals["total_tokens"] is not None and totals["total_tokens"] > plan["total_max_tokens"]
    ):
        raise ValueError("Authorized total budget exceeded")
    result = {
        "schema_version": "p7-gate2-intent-validation-1",
        "checked_at": datetime.now(UTC).isoformat(),
        "source_commit": plan["source_commit"],
        "plan_sha256": digest(plan),
        "status": "intent_holdout_completed_business_e2e_not_run",
        "strategies": results,
        "live_totals": {
            "calls": len(all_calls),
            "usage": totals,
            "estimated_cost_usd": estimated_cost(totals, pricing),
            "billed_cost_usd": None,
            "automatic_retries": 0,
            "unknown_outcomes": 0,
        },
        "bad_cases": bad_cases,
        "default_website_strategy": "unchanged_rule_only",
        "formal_agent_business_completion": "not_run",
        "formal_p3_numeric_evidence_accuracy": "not_run",
        "formal_rag_quality": "not_run",
        "gate2_fully_accepted": False,
        "gate3_started": False,
        "no_post_holdout_candidate_tuning": True,
        "provider_cache_randomized": False,
        "raw_prompts_responses_gold_exported": False,
        "live_authorization_closed": True,
        "holdout_design_analysis": json.loads(
            (BASE / "template-overlap.json").read_text(encoding="utf-8")
        ),
        "posthoc_bad_case_classification": json.loads(
            (BASE / "bad-case-analysis.json").read_text(encoding="utf-8")
        ),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "provider_concurrency": 1,
            "campaign_concurrency": 1,
            "container_image": container["Config"]["Image"],
            "container_memory_limit_bytes": container["HostConfig"].get("Memory"),
            "vm_memory_and_background_load": "not_measured",
        },
        "reporter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    destination = destination.resolve()
    if not (
        destination.is_relative_to(BASE.resolve())
        or destination.is_relative_to((ROOT / "docs/research").resolve())
    ):
        raise ValueError("Write only a new evaluation receipt inside the project")
    with destination.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({"status": result["status"], "live_totals": result["live_totals"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/research/p7-gate2-validation.json"
    )
    main(parser.parse_args().output)
