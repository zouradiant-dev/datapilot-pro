"""Frozen Gate 2 intent Holdout only; no business execution or implicit paid approval."""

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from evaluate_intent import rule_baseline
from p7_isolated_pg import environment, inspect
from summarize_p7_gate1 import request_key, slot_metrics

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.evaluation import IntentGold, IntentObservation, intent_summary, rate, signature
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.orchestration.model import Gateway, NativeTransport, live_transport
from datapilot.persistence.backend import Backend, DurableArtifacts, DurableLedger, execute
from datapilot.persistence.journal import Journal
from datapilot.persistence.session import PersistentCancellation, run_async
from datapilot.web.chat_contracts import ChatSelection
from datapilot.web.semantic_intent import resolve_candidate

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/p7/gate2"
PLAN = ROOT / "docs/research/p7-gate2-plan.json"
STRATEGIES = ("llm_only", "hybrid")
BATCH_SIZES = (12, 12, 12, 12, 11)


def check_plan(plan, *, live=False):
    """Check the host's frozen experiment, never a model-provided authorization."""
    if plan.get("phase") != "p7-gate2-intent" or not plan.get("holdout_authorized"):
        raise ValueError("Explicit Gate 2 Holdout authorization is required")
    if plan.get("batch_sizes") != list(BATCH_SIZES) or plan.get("strategies") != list(STRATEGIES):
        raise ValueError("Do not select or resize Holdout batches after seeing results")
    if (plan.get("total_max_calls"), plan.get("total_max_tokens")) != (118, 750000):
        raise ValueError("Frozen total limits changed")
    for name, expected in plan["files"].items():
        path = (ROOT / name).resolve()
        if (
            not path.is_relative_to(ROOT)
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("Frozen candidate or measurement source changed")
    if live and (
        plan.get("live_allowed") is not True
        or plan.get("live_approval_status") != "explicit_human_approved"
        or not plan.get("live_approval_text")
    ):
        raise ValueError("New bounded paid Holdout approval is required; Gate 1 approval expired")


def load_cases(plan):
    check_plan(plan)
    manifest = json.loads(
        (ROOT / "docs/research/p7-intent-corpus-manifest.json").read_text(encoding="utf-8")
    )
    pin = manifest["splits"]["holdout"]
    raw = (ROOT / pin["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError("Sealed Holdout bytes changed")
    cases = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    if len(cases) != sum(BATCH_SIZES) or len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("Holdout count or unique identities changed")
    return cases


def summarize(observations, planned):
    summary = intent_summary(observations)
    correct = sum(o.actual == o.expected and o.error_code is None for o in observations)
    return {
        "observed_only": summary,
        "planned_tasks": planned,
        "observed_tasks": len(observations),
        "not_run_tasks": planned - len(observations),
        "planned_denominator_exact_match": rate(correct, planned),
        "all_planned_tasks_observed": len(observations) == planned,
        "slots": slot_metrics(observations),
        "agent_execution": "not_run",
        "evidence_verification": "not_run",
        "rag_quality": "not_run",
        "api_accept_latency": "not_run",
        "business_completion_latency": "not_run",
    }


def save(path, record, *, first=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    # The first write refuses to overwrite an earlier experiment, even a partial one.
    destination = path if first else path.with_suffix(".pending.json")
    with destination.open("x" if first else "w", encoding="utf-8") as output:
        json.dump(record, output, ensure_ascii=False, indent=2)
    if not first:
        destination.replace(path)


def check_order(strategy, batch):
    order = [(s, b) for s in STRATEGIES for b in range(len(BATCH_SIZES))]
    for previous_strategy, previous_batch in order[: order.index((strategy, batch))]:
        path = BASE / f"{previous_strategy}-batch-{previous_batch}.json"
        if not path.exists():
            raise ValueError("Frozen batch order cannot be skipped")
        previous = json.loads(path.read_text(encoding="utf-8"))
        if not previous.get("complete") or previous.get("error_code"):
            raise ValueError("Earlier batch stopped; preserve results and request host inspection")


def receipts(backend):
    """Only scoped execution metadata. Raw model text stays in the private Journal."""
    with backend.transaction() as conn:
        backend.authorize(conn)
        rows = (
            execute(
                conn,
                "SELECT * FROM execution.calls WHERE run_id=:r ORDER BY call_key",
                r=backend.run_id,
            )
            .mappings()
            .all()
        )
    result = []
    for row in rows:
        if row["payload"] is not None and digest(row["payload"]) != row["payload_hash"]:
            raise ValueError("Journal response hash mismatch")
        metadata = (row["payload"] or {}).get("data", {}).get("response_metadata", {})
        result.append(
            {
                "call_key": row["call_key"],
                "status": row["status"],
                "usage": row["usage"],
                "elapsed_ms": row["elapsed_ms"],
                "response_sha256": row["payload_hash"],
                "model": {
                    k: metadata[k]
                    for k in ("model_name", "system_fingerprint", "finish_reason")
                    if k in metadata
                },
            }
        )
    return result


async def live_batch(plan, strategy, batch):
    check_plan(plan, live=True)  # Must happen before loading Gold or constructing a client.
    if strategy not in STRATEGIES or type(batch) is not int or not 0 <= batch < len(BATCH_SIZES):
        raise ValueError("Use one of the frozen strategy/batch identities")
    check_order(strategy, batch)
    all_cases = load_cases(plan)
    start = sum(BATCH_SIZES[:batch])
    selected = all_cases[start : start + BATCH_SIZES[batch]]
    path = BASE / f"{strategy}-batch-{batch}.json"
    if path.exists():
        raise ValueError("Batch already recorded; do not rerun a Holdout attempt")
    inspect()
    os.environ.update(environment())
    settings = Settings(
        llm_mode="live",
        max_model_calls=len(selected),
        max_total_tokens=75000,
        max_output_tokens=768,
    )
    if (
        settings.model_provider != "deepseek"
        or settings.model != "deepseek-flash"
        or settings.base_url.rstrip("/")
        not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}
    ):
        raise ValueError("Live destination/profile differs from the frozen plan")
    gateway_limits = {
        key: getattr(settings, key)
        for key in ("max_input_chars", "max_context_tokens", "model_timeout_seconds")
    }
    if gateway_limits != plan["gateway_limits"]:
        raise ValueError("Gateway resource configuration changed after freeze")
    owner = "p7-intent-holdout"
    run_id = str(uuid5(NAMESPACE_URL, owner + plan["campaign_id"] + strategy + str(batch)))
    backend = Backend(settings.runtime_database_url.get_secret_value(), run_id, owner)
    manifest = {
        "purpose": owner,
        "plan_sha256": digest(plan),
        "strategy": strategy,
        "batch": batch,
        "selected_sha256": digest(selected),
        "thinking": "disabled",
        "sdk_retries": 0,
        "max_output_tokens": 768,
        "gateway_limits": gateway_limits,
    }
    limits = BudgetLimits(calls=len(selected), tokens=75000)
    record = {
        "schema_version": "p7-gate2-intent-batch-1",
        "run_id": run_id,
        "strategy": strategy,
        "batch": batch,
        "manifest_sha256": digest(manifest),
        "observations": [],
        "complete": False,
        "error_code": None,
        "billed_cost_usd": None,
        "estimated_cost_usd": None,
        "cost_status": "not_estimated; inspect original usage and current dated pricing first",
    }
    try:
        with backend.lease():
            with backend.engine.connect() as conn:
                exists = execute(
                    conn, "SELECT 1 FROM execution.runs WHERE run_id=:r", r=run_id
                ).first()
            if exists:
                raise ValueError("Campaign already exists; no automatic replay or new identity")
            backend.register(manifest, limits)
            ledger = DurableLedger(backend, limits)
            journal = Journal(backend, ledger, DurableArtifacts(backend))
            transport = live_transport(settings)
            transport_kind = "live" if isinstance(transport, NativeTransport) else "mock"
            gateway = Gateway(transport, settings, ledger, PersistentCancellation(backend))
            gateway.durability = journal
            record["transport"] = transport_kind
            observations = []
            save(path, record, first=True)
            for case in selected:
                before, started = ledger.snapshot(), time.perf_counter()
                code, actual = None, None
                try:
                    draft = await resolve_candidate(
                        case["question"],
                        ChatSelection.model_validate_json(json.dumps(case["selection"])),
                        case["datasets"],
                        today=date.fromisoformat(case["today"]),
                        previous=case["previous"],
                        gateway=gateway,
                        strategy=strategy,
                    )
                    actual = signature(draft)
                except Exception as exc:
                    code = exc.error.code if isinstance(exc, AgentFailure) else "EVALUATION_ERROR"
                after = ledger.snapshot()
                calls = receipts(backend)
                matching = [c for c in calls if c["call_key"] == request_key(case)]
                cache = [
                    (c["usage"] or {}).get("input_token_details", {}).get("cache_read")
                    for c in matching
                ]
                observations.append(
                    IntentObservation(
                        case_id=case["case_id"],
                        strategy=strategy,
                        transport=transport_kind,
                        expected=IntentGold.model_validate_json(json.dumps(case["expected"])),
                        actual=actual,
                        error_code=code,
                        elapsed_ms=(time.perf_counter() - started) * 1000,
                        model_calls=after.calls - before.calls,
                        reported_tokens=after.reported_tokens - before.reported_tokens
                        if after.usage_complete
                        else None,
                        provider_cache_read_tokens=(
                            0
                            if after.calls == before.calls
                            else sum(cache)
                            if len(matching) == 1 and all(type(v) is int for v in cache)
                            else None
                        ),
                    )
                )
                record.update(
                    checked_at=datetime.now(UTC).isoformat(),
                    observations=[o.model_dump(mode="json") for o in observations],
                    summary=summarize(observations, len(selected)),
                    ledger=after.model_dump(),
                    model_receipts=calls,
                    complete=len(observations) == len(selected),
                    error_code=code,
                )
                save(path, record)
                if code:
                    # A known bad proposal is a scored clarification. A provider/runtime
                    # error ends the batch; later batches require host inspection, not retry.
                    raise AgentFailure(code, "Holdout attempt stopped; preserve Journal and budget")
            print(json.dumps(record["summary"], ensure_ascii=False))
    finally:
        backend.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["rule", "live"])
    parser.add_argument("--strategy", choices=STRATEGIES)
    parser.add_argument("--batch", type=int, choices=range(len(BATCH_SIZES)))
    args = parser.parse_args()
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if args.mode == "rule":
        cases = load_cases(plan)
        rows = rule_baseline(cases)
        result = {
            "checked_at": datetime.now(UTC).isoformat(),
            "plan_sha256": digest(plan),
            "observations": [r.model_dump(mode="json") for r in rows],
            "summary": summarize(rows, len(cases)),
        }
        save(BASE / "rule-only.json", result, first=True)
        print(json.dumps(result["summary"], ensure_ascii=False))
    else:
        if args.strategy is None or args.batch is None:
            parser.error("Live requires the frozen --strategy and --batch")
        run_async(live_batch(plan, args.strategy, args.batch))


if __name__ == "__main__":
    main()
