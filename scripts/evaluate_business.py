"""P7 real PG/MCP/Durable/P3/report contracts with explicit Fake decisions.

Never a real-model quality result. Operates ONLY on the labelled disposable PG.
"""

import json
import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from p7_isolated_pg import environment, inspect
from report_recovery_probe import ReportDecisions

from datapilot.config import Settings
from datapilot.data.semantic_demo import mapping_draft
from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.datasets.repository import DatasetRepository
from datapilot.db.management import management_url
from datapilot.evaluation import percentile, rate, wilson
from datapilot.ingestion.common import digest
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService
from datapilot.persistence.backend import Backend, execute
from datapilot.persistence.inspection import inspect_run
from datapilot.persistence.session import run_async, run_durable
from datapilot.reporting.contracts import ReportScope
from datapilot.semantics.contracts import MetricDraft, MetricRequest
from datapilot.semantics.registry import RegistryStore

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/p7/business"
OWNER = "p7-business-dev"


def prepare(settings):
    source = ROOT / "tests/fixtures/semantics/saas_metrics.xlsx"
    parsed = parse_file(source, options=ParseOptions(header="present"))
    confirmed = confirm_schema(parsed, propose_schema(parsed), reviewed=True)
    ingest = IngestionService(
        management_url("ingest"), storage_dir=ROOT / "artifacts/p7/private/sources"
    )
    imported = ingest.import_file(source, confirmed, ImportRequest(name="p7-business-synthetic-v1"))
    bindings = DatasetScope(
        bindings=[DatasetBinding(dataset_id=imported.dataset_id, version=imported.version)]
    )
    repository = DatasetRepository(settings.upload_reader_database_url.get_secret_value(), bindings)
    registry = RegistryStore(management_url("registry"))
    try:
        schema = repository.schema(imported.dataset_id)
        semantics = registry.confirm_semantics(mapping_draft(schema), reviewed=True)
        metrics = {
            kind: registry.confirm_metric(
                MetricDraft(
                    dataset_id=imported.dataset_id,
                    dataset_version=imported.version,
                    semantic_version=semantics.semantic_version,
                    metric_id=kind,
                ),
                reviewed=True,
            )
            for kind in [
                "paid_invoice_revenue",
                "usage",
                "active_subscriptions",
                "customer_churn",
                "subscription_churn",
            ]
        }
        return bindings, schema, semantics, metrics
    finally:
        repository.close()
        registry.close()
        ingest.close()


async def main():
    inspect()
    os.environ.update(environment())
    settings = Settings(llm_mode="fake", max_model_calls=8)
    bindings, schema, semantics, definitions = prepare(settings)
    BASE.mkdir(parents=True, exist_ok=True)
    cases_path = ROOT / "tests/fixtures/evaluation/business-dev.jsonl"
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines()]
    pinned = {
        "dataset": schema.model_dump(mode="json"),
        "semantics": semantics.model_dump(mode="json"),
        "metrics": {k: d.model_dump(mode="json") for k, d in definitions.items()},
    }
    pins_path = BASE / "trusted-pins.json"
    if pins_path.exists() and json.loads(pins_path.read_text(encoding="utf-8")) != pinned:
        raise ValueError("Pinned source/definitions changed")
    pins_path.write_text(json.dumps(pinned, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for case in cases:
        path = BASE / (case["case_id"] + ".json")
        if path.exists():
            # Explicitly preserve completed observations; never silently rerun a case.
            rows.append(json.loads(path.read_text(encoding="utf-8")))
            continue
        definition = definitions[case["kind"]]
        request = MetricRequest.model_validate_json(
            json.dumps(
                {
                    "goal_id": "metric_1",
                    "dataset_id": schema.dataset_id,
                    "dataset_version": schema.version,
                    "semantic_version": semantics.semantic_version,
                    "metric_id": case["kind"],
                    "metric_version": definition.metric_version,
                    "window": case["window"],
                    "as_of": case["as_of"],
                }
            )
        )
        scope = ReportScope(
            question=case["question"], owner=OWNER, datasets=bindings, metrics=[request]
        )
        run_id = str(
            uuid5(NAMESPACE_URL, "datapilot-p7-business-1:" + digest(case) + digest(pinned))
        )
        started = time.perf_counter()
        backend = Backend(settings.runtime_database_url.get_secret_value(), run_id, OWNER)
        try:
            with backend.engine.connect() as conn:
                exists = execute(
                    conn, "SELECT 1 FROM execution.runs WHERE run_id=:r", r=run_id
                ).first()
            if not exists:
                result = await run_durable(
                    settings,
                    run_id,
                    case["question"],
                    owner=OWNER,
                    report_scope=scope,
                    transport=ReportDecisions(""),
                )
                runtime_ms = (time.perf_counter() - started) * 1000
            else:
                # A lost observer response must not create a second business analysis.
                result, runtime_ms = None, None
            proof = await inspect_run(settings, run_id, OWNER, case["question"], report_scope=scope)
            report = proof["report"]
            claims = [c for c in report.claims if c.kind == "metric"] if report else []
            expected = case["expected"]
            if expected["status"] == "verified":
                correct = len(claims) == 1 and claims[0].metric.verdict == "verified"
                if correct:
                    value = claims[0].metric.value
                    correct = value.unit == expected["unit"] and Decimal(value.value) == Decimal(
                        expected["value"]
                    )
                    if "numerator" in expected:
                        correct &= (
                            Decimal(value.numerator) == expected["numerator"]
                            and Decimal(value.denominator) == expected["denominator"]
                        )
                    correct &= all(
                        c.status == "passed" for c in claims[0].metric.verification.checks
                    )
                    correct &= claims[0].metric.request == request
            else:
                correct = (
                    bool(report)
                    and not claims
                    and report.business_completion.status in {"unavailable", "partial", "blocked"}
                )
            refs = [
                {
                    "evidence_id": c.metric.evidence_id,
                    "verification_id": c.metric.verification.verification_id,
                    "evidence_sha256": c.metric.evidence_sha256,
                    "verification_sha256": c.metric.verification_sha256,
                    "source_sha256": c.metric.source_sha256,
                    "metric_version": c.metric.request.metric_version,
                    "verdict": c.metric.verdict,
                    "value": c.metric.value.model_dump(mode="json"),
                }
                for c in claims
            ]
            observed = {
                "case_id": case["case_id"],
                "run_id": run_id,
                "checked_at": datetime.now(UTC).isoformat(),
                "kind": case["kind"],
                "expected": expected,
                "correct": bool(correct),
                "execution_status": proof["state"].get("status"),
                "business_completion": report.business_completion.model_dump(mode="json")
                if report
                else None,
                "unknown": proof["unknown"],
                "refs": refs,
                "runtime_ms": runtime_ms,
                "usage_fixture_only": proof["usage"],
                "paid_model_calls": 0,
                "transport": "explicit_Fake_decisions_real_PG_MCP",
                "no_model_proof": True,
                "recovered_observer": result is None,
            }
            with path.open("x", encoding="utf-8") as out:
                json.dump(observed, out, ensure_ascii=False, indent=2)
            rows.append(observed)
            print(
                json.dumps(
                    {
                        "case_id": case["case_id"],
                        "correct": bool(correct),
                        "status": observed["execution_status"],
                    }
                ),
                flush=True,
            )
        finally:
            backend.close()
    successes = sum(r["correct"] for r in rows)
    summary = {
        "checked_at": datetime.now(UTC).isoformat(),
        "tasks": len(rows),
        "business_contract_correct": rate(successes, len(rows)),
        "wilson_95pct": wilson(successes, len(rows)),
        "execution_succeeded": rate(
            sum(r["execution_status"] == "succeeded" for r in rows), len(rows)
        ),
        "unavailable_gold_tasks": sum(r["expected"]["status"] == "unavailable" for r in rows),
        "runtime_ms": {
            "definition": "Durable start to return; source setup/NoModel inspection excluded",
            "p50": percentile([r["runtime_ms"] for r in rows if r["runtime_ms"] is not None], 0.5),
            "p95": percentile([r["runtime_ms"] for r in rows if r["runtime_ms"] is not None], 0.95),
        },
        "api_accept_latency": "not_run",
        "real_model_quality": "not_run",
        "provider_tokens": None,
        "provider_cache": None,
        "paid_model_calls": 0,
        "formal_holdout": False,
        "pins_sha256": digest(pinned),
        "bad_cases": [r["case_id"] for r in rows if not r["correct"]],
    }
    (BASE / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    run_async(main())
