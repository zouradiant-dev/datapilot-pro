"""Read-only Gate 1 receipts/negative cases; never invokes a model or opens Holdout."""

import argparse
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage, messages_to_dict
from p7_isolated_pg import environment

from datapilot.config import Settings
from datapilot.evaluation import IntentObservation, intent_summary, rate
from datapilot.ingestion.common import digest
from datapilot.persistence.backend import Backend, execute
from datapilot.web.chat_contracts import ChatSelection
from datapilot.web.semantic_intent import SYSTEM, IntentProposal, validate_candidate

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/p7"


def slot_metrics(observations):
    groups = {
        "dataset_version": ("dataset_id", "dataset_version"),
        "metric_semantic_version": ("metric_id", "metric_version", "semantic_version"),
        "time_window": ("window", "as_of"),
    }
    answerable = [o for o in observations if o.expected.action == "candidate"]
    result = {}
    for name, fields in groups.items():

        def values(metrics, fields=fields):
            return sorted(json.dumps({k: m[k] for k in fields}, sort_keys=True) for m in metrics)

        n = sum(
            o.actual is not None
            and o.actual.action == "candidate"
            and values(o.actual.metrics) == values(o.expected.metrics)
            for o in answerable
        )
        result[name] = rate(n, len(answerable))
    result["real_database_authorization"] = "not_run; synthetic metadata candidate only, no launch"
    return result


def request_key(case):
    catalog = [
        {
            "dataset_id": d["schema"]["dataset_id"],
            "version": d["schema"]["version"],
            "metrics": [
                {k: m[k] for k in ("metric_id", "metric_version", "semantic_version")}
                for m in d["metrics"]
            ],
        }
        for d in case["datasets"]
    ]
    payload = {
        "question": case["question"],
        "question_sha256": digest(case["question"]),
        "today": case["today"],
        "catalog": catalog,
        "selection": ChatSelection.model_validate_json(json.dumps(case["selection"])).model_dump(
            mode="json"
        ),
    }
    messages = [
        SystemMessage(content=SYSTEM),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
    ]
    return "model:root:" + digest({"messages": messages_to_dict(messages), "tools": []})


def main(destination=None):
    os.environ.update(environment())
    settings = Settings(llm_mode="fake")
    plan = json.loads((ROOT / "docs/research/p7-live-pilot-plan.json").read_text(encoding="utf-8"))
    cases = {
        r["case_id"]: r
        for r in map(
            json.loads,
            (ROOT / "tests/fixtures/evaluation/intent-dev.jsonl")
            .read_text(encoding="utf-8")
            .splitlines(),
        )
    }
    baseline = json.loads((BASE / "rule-baseline-dev.json").read_text(encoding="utf-8"))
    selected = [
        IntentObservation.model_validate_json(json.dumps(o))
        for o in baseline["observations"]
        if o["case_id"] in plan["case_ids"]
    ]
    outputs = {
        "rule_only_same_12": {"summary": intent_summary(selected), "slots": slot_metrics(selected)}
    }
    bad_cases = [
        {
            "case_id": o["case_id"],
            "question": cases[o["case_id"]]["question"],
            "strategy": "rule_only",
            "expected": o["expected"],
            "actual": o["actual"],
        }
        for o in baseline["observations"]
        if o["case_id"] in baseline["summary"]["bad_cases"]
    ]
    total_calls, total_tokens, total_cost = 0, 0, Decimal(0)
    for strategy in ["llm_only", "hybrid"]:
        paths = list(BASE.glob("intent-live-" + strategy + "-*.json"))
        if len(paths) != 1:
            raise ValueError("Do not silently choose between or overwrite repeated experiments")
        record = json.loads(paths[0].read_text(encoding="utf-8"))
        assert record["complete"]
        backend = Backend(
            settings.runtime_database_url.get_secret_value(), record["run_id"], "p7-intent-dev"
        )
        try:
            with backend.transaction() as conn:
                manifest = backend.authorize(conn)["manifest"]
                calls = (
                    execute(
                        conn,
                        "SELECT * FROM execution.calls WHERE run_id=:r ORDER BY call_key",
                        r=record["run_id"],
                    )
                    .mappings()
                    .all()
                )
                ledger = execute(
                    conn, "SELECT payload FROM execution.ledger WHERE run_id=:r", r=record["run_id"]
                ).scalar_one()
            assert all(c["status"] == "complete" and c["kind"] == "model" for c in calls)
            assert digest(ledger["state"]) == ledger["sha256"]
            observations = [
                IntentObservation.model_validate_json(json.dumps(o)) for o in record["observations"]
            ]
            rows, inp, out, cache = [], 0, 0, 0
            usage_complete = True
            by_hash = {digest(cases[i]["question"]): i for i in plan["case_ids"]}
            by_key = {request_key(cases[i]): i for i in plan["case_ids"]}
            for c in calls:
                usage = c["usage"] or {}
                details = usage.get("input_token_details", {})
                known = (
                    all(
                        type(usage.get(k)) is int
                        for k in ["input_tokens", "output_tokens", "total_tokens"]
                    )
                    and type(details.get("cache_read")) is int
                )
                usage_complete &= known
                if known:
                    inp += usage["input_tokens"]
                    out += usage["output_tokens"]
                    cache += details["cache_read"]
                data = c["payload"]["data"]
                try:
                    proposed = IntentProposal.model_validate_json(data["content"])
                    case_id = by_hash.get(proposed.question_sha256)
                    if case_id:
                        case = cases[case_id]
                        checked = validate_candidate(
                            proposed,
                            case["question"],
                            ChatSelection.model_validate_json(json.dumps(case["selection"])),
                            case["datasets"],
                            today=__import__("datetime").date.fromisoformat(case["today"]),
                        )
                        if case_id in record["summary"]["bad_cases"]:
                            bad_cases.append(
                                {
                                    "case_id": case_id,
                                    "question": case["question"],
                                    "strategy": strategy,
                                    "host_reason": checked.missing,
                                    "proposal_sha256": digest(proposed),
                                    "no_live_retry": True,
                                }
                            )
                except ValueError:
                    case_id = by_key.get(c["call_key"])
                    if case_id in record["summary"]["bad_cases"]:
                        bad_cases.append(
                            {
                                "case_id": case_id,
                                "question": cases[case_id]["question"],
                                "strategy": strategy,
                                "host_reason": ["INTENT_PROPOSAL_INVALID"],
                                "response_sha256": c["payload_hash"],
                                "no_live_retry": True,
                            }
                        )
                meta = data.get("response_metadata", {})
                rows.append(
                    {
                        "call_key": c["call_key"],
                        "case_id": case_id,
                        "status": c["status"],
                        "usage": usage,
                        "elapsed_ms": c["elapsed_ms"],
                        "payload_sha256": c["payload_hash"],
                        "model": {
                            k: meta[k]
                            for k in ["model_name", "system_fingerprint", "finish_reason"]
                            if k in meta
                        },
                    }
                )
            assert len(calls) == record["ledger"]["calls"]
            actual = sum((c["usage"] or {}).get("total_tokens", 0) for c in calls)
            assert actual == record["ledger"]["reported_tokens"]
            # These separately approved receipts occurred on Saturday 2026-10-24.
            approved = datetime.fromisoformat(plan["approved_at"])
            assert approved.date().isoformat() == "2026-10-24" and approved.weekday() == 5
            cost = (
                (
                    Decimal(inp - cache) * Decimal(".15")
                    + Decimal(cache) * Decimal(".003")
                    + Decimal(out) * Decimal(".6")
                )
                / Decimal(1000000)
                if usage_complete
                else None
            )
            for o in observations:
                matching = [r for r in rows if r["case_id"] == o.case_id]
                o.provider_cache_read_tokens = (
                    sum(r["usage"]["input_token_details"]["cache_read"] for r in matching)
                    if usage_complete
                    else None
                )
            summary = intent_summary(observations)
            outputs[strategy] = {
                "run_id": record["run_id"],
                "summary": summary,
                "slots": slot_metrics(observations),
                "model_receipts": rows,
                "model_input_tokens": inp if usage_complete else None,
                "model_output_tokens": out if usage_complete else None,
                "provider_cache_read_tokens": cache if usage_complete else None,
                "model_elapsed_ms": sum(c["elapsed_ms"] or 0 for c in calls),
                "manifest_sha256": digest(manifest),
                "ledger_sha256": digest(ledger),
                "cost": {
                    "currency": "USD",
                    "estimated": str(cost) if cost is not None else None,
                    "billed": None,
                    "rate_period": "off_peak",
                    "source": "https://api-docs.deepseek.com/quick_start/pricing/",
                },
            }
            total_calls += len(calls)
            total_tokens += actual
            if cost is not None:
                total_cost += cost
        finally:
            backend.close()
    assert total_calls <= 24 and total_tokens <= 150000
    result = {
        "schema_version": "p7-gate1-development-1",
        "checked_at": datetime.now(UTC).isoformat(),
        "phase_status": "bounded_development_pilot_completed",
        "not_full_p7_acceptance": True,
        "baseline_59": baseline["summary"],
        "same_12_case_comparison": outputs,
        "live_totals": {
            "calls": total_calls,
            "provider_total_tokens": total_tokens,
            "estimated_cost_usd": str(total_cost),
            "billed_cost": None,
            "no_automatic_live_retry": True,
        },
        "bad_cases": bad_cases,
        "holdout": "sealed_not_run",
        "gate2": "not_started",
        "additional_gate3_experiments_after_stop_instruction": 0,
        "default_website_strategy": "unchanged_rule_only",
        "scope": (
            "Intent candidate on synthetic metadata; no business Run, no true DB "
            "authorization or end-to-end business-quality claim"
        ),
        "raw_provider_prompts_keys_rows_documents_exported": False,
    }
    path = destination or ROOT / "docs/research/p7-gate1-validation.json"
    path = path.resolve()
    if not (
        path.is_relative_to(ROOT / "artifacts/p7") or path.is_relative_to(ROOT / "docs/research")
    ):
        raise ValueError("Write validation records only within this repository")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                "totals": result["live_totals"],
                "same_12": {k: v["summary"]["intent_exact_match"] for k, v in outputs.items()},
                "holdout": result["holdout"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    main(parser.parse_args().output)
