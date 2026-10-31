"""Mechanical pre-Live checks. No target-model inference, prompts or threshold tuning."""

import argparse
import json
from decimal import Decimal

from v3_common import BASE, ROOT, clean_settings, infrastructure, write_new
from v3_prepare import build_cases
from v3_runner import preflight_task

from datapilot.ingestion.common import digest
from datapilot.persistence.session import run_async
from datapilot.reporting.contracts import DocumentGoal
from datapilot.semantics.registry import RegistryStore
from datapilot.semantics.service import analyze


async def validate(values):
    pins = json.loads((BASE / "bindings-v2.json").read_bytes())
    tasks, answers, specs = build_cases(pins)
    old_inputs = json.loads((BASE / "draft-inputs.jsonl.json").read_bytes())
    old_gold = json.loads((BASE / "draft-gold.jsonl.json").read_bytes())
    changes = []
    for old, new in zip(old_inputs, [t.model_dump(mode="json") for t in tasks], strict=True):
        if old != new:
            changes.append(
                {
                    "case_id": new["case_id"],
                    "kind": (
                        "unsealed negative input: actual old Document in un"
                        "authorized new index; expected disposition unchang"
                        "ed"
                    ),
                }
            )
    for old, new in zip(old_gold, [g.model_dump(mode="json") for g in answers], strict=True):
        if old != new:
            a, b = json.loads(json.dumps(old)), json.loads(json.dumps(new))
            for row in a["metrics"]:
                row.pop("unit")
            for row in b["metrics"]:
                row.pop("unit")
            if a != b:
                raise ValueError("Unexpected numerical/semantic Gold edit")
            changes.append(
                {
                    "case_id": new["case_id"],
                    "kind": (
                        "unsealed Oracle unit label corrected to existing contract; "
                        "values/meaning unchanged"
                    ),
                }
            )
    write_new(BASE / "draft-r3-inputs.json", [t.model_dump(mode="json") for t in tasks])
    write_new(BASE / "draft-r3-gold.json", [g.model_dump(mode="json") for g in answers])
    write_new(
        BASE / "unsealed-draft-r3-revision.json",
        {"changes": changes, "paid_requests": 0, "product_output_used_to_change_gold": False},
    )
    settings = clean_settings(values)
    rows = []
    cache = {}
    for task, gold in zip(tasks, answers, strict=True):
        k = digest(
            {
                "ds": task.datasets.model_dump(mode="json"),
                "rag": task.rag_scope.model_dump(mode="json") if task.rag_scope else None,
                "scope_invalid": not task.datasets.bindings and bool(task.metrics),
            }
        )
        if k not in cache:
            cache[k] = await preflight_task(task, pins, settings)
        code = cache[k]
        if code != gold.host_code:
            raise ValueError((task.case_id, "Unexpected source/authority preflight outcome", code))
        if task.document_goal:
            DocumentGoal.model_validate_json(task.document_goal.model_dump_json())
            for fact in task.document_goal.required_facts:
                if fact.citation:
                    matches = [
                        s
                        for c in pins["corpora"].values()
                        for s in c["manifest"]["sources"]
                        if s["document_id"] == fact.citation.document_id
                    ]
                    if not matches:
                        raise ValueError("Fact source is absent")
        rows.append(
            {
                "case_id": task.case_id,
                "expected_host_code": gold.host_code,
                "actual_host_code": code,
                "eligible": True,
            }
        )
        print(task.case_id + " metadata preflight passed", flush=True)
    write_new(
        BASE / "mechanical-admission-r3.json",
        {
            "cases": rows,
            "paid_requests": 0,
            "formal_live_status": "not_run",
            "cache_entries": len(cache),
        },
    )
    registry = RegistryStore(values["DATAPILOT_REGISTRY_DATABASE_URL"])
    results = []
    seen = set()
    try:
        for task, gold in zip(tasks, answers, strict=True):
            if gold.host_code:
                continue
            for request, expected in zip(task.metrics, gold.metrics, strict=True):
                key = digest(request)
                if key in seen:
                    continue
                seen.add(key)
                path = BASE / "private/p3-mechanical" / (key + ".json")
                if path.exists():
                    prior = json.loads(path.read_bytes())
                    evidence = registry.get_evidence(prior["evidence_id"])
                    verification = registry.get_verification(
                        prior["verification"]["verification_id"]
                    )
                    if (
                        evidence.request != request
                        or verification.evidence_id != evidence.evidence_id
                    ):
                        raise ValueError("Cached mechanical identity mismatch")
                    value = evidence.value if verification.verdict == "verified" else None
                    codes = [m.code for m in evidence.missing]
                    evidence_id = evidence.evidence_id
                else:
                    result = await analyze(settings, registry, [request])
                    outcome = result.outcomes[0]
                    value = outcome.value
                    codes = [m.code for m in outcome.missing]
                    verification = outcome.verification
                    evidence_id = outcome.evidence_id
                if verification.verdict != expected.disposition:
                    raise ValueError(
                        (
                            task.case_id,
                            "P3 verdict differs from predeclared Gold",
                            verification.verdict,
                            expected.disposition,
                        )
                    )
                if value and (
                    Decimal(value.value) != Decimal(expected.value) or value.unit != expected.unit
                ):
                    raise ValueError(
                        (task.case_id, "P3 differs from independent numeric/unit Gold")
                    )
                if expected.reason and expected.reason not in codes:
                    raise ValueError((task.case_id, "P3 missing precise refusal reason", codes))
                results.append(
                    {
                        "request_sha256": key,
                        "case_id_first_reference": task.case_id,
                        "evidence_id": evidence_id,
                        "verification": verification.model_dump(mode="json"),
                        "missing_codes": codes,
                        "value": value.model_dump(mode="json") if value else None,
                    }
                )
                if not path.exists():
                    write_new(path, results[-1])
                print(
                    "P3 mechanical "
                    + task.case_id
                    + " "
                    + request.goal_id
                    + " "
                    + verification.verdict,
                    flush=True,
                )
    finally:
        registry.close()
    write_new(
        BASE / "p3-mechanical-summary-r3.json",
        {
            "checks": results,
            "target_model_calls": 0,
            "formal_runtime_runs": 0,
            "purpose": (
                "Deterministic original P3 compatibility check only; "
                "not formal Holdout Agent results"
            ),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    run_async(
        validate(infrastructure(ROOT / "artifacts/p7/unified-regression/private/environment.json"))
    )
