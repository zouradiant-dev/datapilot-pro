"""Explicit pre-registration and trusted synthetic ingestion; no Worker is run here."""

import argparse
import json
import os
import secrets
from datetime import UTC, datetime

from datapilot.config import Settings
from datapilot.datasets.contracts import ImportRequest
from datapilot.ingestion.common import digest
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService as DatasetIngest
from datapilot.persistence.session import run_async
from datapilot.rag.contracts import RagScope
from datapilot.rag.models import create_embedding
from datapilot.rag.storage import IngestionService
from datapilot.runtime.mcp_client import dataset_session
from datapilot.semantics.contracts import MetricDraft, SemanticDraft
from datapilot.semantics.registry import RegistryStore

from .common import ARMS, HERE, OUT, ROOT, dataset_scope, load, manifest, sha, write_new


def environment():
    values = json.loads((OUT / "environment-private.json").read_bytes())
    assert values["DATAPILOT_ADMIN_DATABASE_URL"].endswith(
        "/datapilot_test_qwen_business_pilot_v1_20261030"
    )
    os.environ.update(values)
    os.environ.update(DATAPILOT_API_KEY="", DATAPILOT_RUN_LIVE_TESTS="0", DATAPILOT_LLM_MODE="fake")
    return values, Settings(
        _env_file=None, llm_mode="fake", api_key=None, model="phase2c-scripted-v1"
    )


def verify_registration():
    reg = json.loads((OUT / "registration.json").read_bytes())
    for name, expected in reg["files"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("Registered evaluation file changed: " + name)
    original = json.loads(
        (ROOT / "artifacts/p7/qwen-lifecycle-v1/implementation-freeze.json").read_bytes()
    )
    for name, expected in original["payload"]["files"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("Frozen product changed: " + name)
    return reg


def register():
    p = load()
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "registration.json").exists():
        raise ValueError("Registration exists; no rewriting observed Gold")
    for case in p.cases:
        folder = OUT / "sources" / case.id
        folder.mkdir(parents=True, exist_ok=False)
        for name, text in {**p.noise, **case.documents}.items():
            (folder / name).write_bytes(text.encode("utf-8"))
    (OUT / "invoices.csv").write_bytes(p.csv.encode("utf-8"))
    expected = {}
    for case in p.cases:
        expected[case.id] = {}
        for arm in ARMS:
            m = manifest(case, arm)
            expected[case.id][arm] = {
                "manifest": m.model_dump(mode="json"),
                "index_version": digest(m),
            }
        assert (
            expected[case.id]["bge"]["manifest"]["sources"]
            == expected[case.id]["qwen"]["manifest"]["sources"]
        )
    files = [f for f in HERE.glob("*") if f.suffix in {".py", ".json"}]
    files += [ROOT / "tests/test_qwen_business_pilot.py"]
    files += list((OUT / "sources").glob("*/*.md")) + [OUT / "invoices.csv"]
    files += [ROOT / "scripts/report_recovery_probe.py", ROOT / "scripts/p7_business_scoring.py"]
    key = secrets.token_bytes(32)
    with (OUT / "collector-key-private.bin").open("xb") as stream:
        stream.write(key)
    write_new(
        OUT / "registration.json",
        {
            "schema_version": "phase2c-pilot-registration-1",
            "registered_at": datetime.now(UTC).isoformat(),
            "pilot_sha256": sha(HERE / "cases.json"),
            "files": {str(f.relative_to(ROOT)).replace("\\", "/"): sha(f) for f in files},
            "expected_indexes": expected,
            "planned": 16,
            "paired_runs": 32,
            "runtime_eligible": 30,
            "preflight_expected": 2,
            "model_decisions": (
                "Same ReportDecisions class, same fixed original host document query"
            ),
            "counterbalance": "odd cases BGE then Qwen; even cases Qwen then BGE; sequential",
            "scoring": {
                "source_recall_at_3": (
                    "Unique first-search returned sources / relevant Gold sources; "
                    "15 authorized cases per arm"
                ),
                "source_precision": (
                    "Relevant returned unique sources / returned unique sources; "
                    "null for zero returned"
                ),
                "required_coverage": (
                    "Returned Required sources / Required sources, "
                    "independent of Goal/fact eligibility"
                ),
                "fact_coverage": (
                    "Published supported Required facts / all Required fact requirements; "
                    "missing requirements stay in denominator"
                ),
                "strict_report": (
                    "Expected status + exact expected Required fact set + valid citations + "
                    "exact P3 numeric unit/value + causal guard"
                ),
                "safety": (
                    "Zero false completed, unsupported claim or citation, unauthorized source "
                    "and unverified financial publication"
                ),
                "stop": (
                    "First safety violation, unknown outcome or infrastructure/collector integrity "
                    "failure stops new dispatch; remaining stays not_run"
                ),
                "denominators": (
                    "16 planned per arm; retrieval excludes expected scope-blocked; "
                    "zero-data metric is null; categories fixed 2 cases each"
                ),
                "gate_b": (
                    "Qwen macro Required and Fact Coverage both strictly higher, "
                    "with no increase in total irrelevant returned sources"
                ),
                "gate_c": (
                    "Qwen strict-correct count strictly higher; recall is not report correctness"
                ),
            },
            "limits": {
                "root_calls": 8,
                "child_calls": 4,
                "tokens": 18000,
                "searches_per_worker": 2,
                "script_actual_searches": 1,
                "top_k": 3,
                "max_worker_turns": 4,
                "mcp_seconds": 10,
                "paid_api_calls": 0,
            },
            "gold_origin": (
                "New public synthetic author-defined literal facts and independent Decimal; "
                "not an independent human blind review"
            ),
            "binding_seal": (
                "Append actual Registry identity/hash before first retrieval; "
                "no Gold or rule amendments"
            ),
        },
    )
    print("Registered 16 Gold cases before any vector search")


async def metric(values, settings):
    p = load()
    parsed = parse_file(OUT / "invoices.csv", options=ParseOptions(header="present"))
    confirmation = confirm_schema(parsed, propose_schema(parsed), reviewed=True)
    ingest = DatasetIngest(values["DATAPILOT_INGEST_DATABASE_URL"], storage_dir=OUT / "uploads")
    registry = RegistryStore(values["DATAPILOT_REGISTRY_DATABASE_URL"])
    try:
        imported = ingest.import_file(
            OUT / "invoices.csv", confirmation, ImportRequest(name=p.dataset_name)
        )
        case = next(c for c in p.cases if c.metric)
        async with dataset_session(settings, dataset_scope(case)) as tools:
            schema = await tools.schema(imported.dataset_id)
            table = schema.tables[0]
            independent = await tools.execute(
                imported.dataset_id,
                f'SELECT SUM(amount_cents)/100.0 AS value FROM uploads."{table.physical_name}" '
                "WHERE payment_status='paid' AND currency='CNY' "
                "AND invoice_date >= DATE '2026-08-01' AND invoice_date < DATE '2026-09-01'",
            )
        from decimal import Decimal

        assert Decimal(independent.result.rows[0][0]) == Decimal(p.metric_gold["value"])
        definition = SemanticDraft.model_validate_json(
            json.dumps(
                {
                    "dataset_id": imported.dataset_id,
                    "dataset_version": 1,
                    "entities": [
                        {
                            "entity": "invoices",
                            "table_id": table.table_id,
                            "fields": {
                                "record_id": "invoice_id",
                                "amount": "amount_cents",
                                "invoice_date": "invoice_date",
                                "payment_status": "payment_status",
                                "currency": "currency",
                            },
                            "grain": ["invoice_id"],
                            "amount_storage": "minor",
                            "coverage_start": "2026-08-01",
                            "coverage_end_exclusive": "2026-09-01",
                        }
                    ],
                }
            )
        )
        semantic = registry.confirm_semantics(definition, reviewed=True)
        entry = registry.confirm_metric(
            MetricDraft(
                dataset_id=imported.dataset_id,
                dataset_version=1,
                semantic_version=semantic.semantic_version,
                metric_id="paid_invoice_revenue",
            ),
            reviewed=True,
        )
        return {
            "dataset": imported.model_dump(mode="json"),
            "semantic": semantic.model_dump(mode="json"),
            "metric": entry.model_dump(mode="json"),
            "independent_sql": independent.model_dump(mode="json"),
            "review_basis": (
                "Explicit public synthetic test-host fixture, "
                "not production approval or independent human signoff"
            ),
        }
    finally:
        registry.close()
        ingest.close()


def ingest_arm(arm):
    reg = verify_registration()
    values, _ = environment()
    embedding = create_embedding(ARMS[arm])
    service = IngestionService(values["DATAPILOT_RAG_INGEST_DATABASE_URL"], embedding)
    try:
        result = {}
        for case in load().cases:
            m = manifest(case, arm)
            scope = RagScope(
                owner=m.target.owner,
                allow_saas=not case.metric,
                datasets=dataset_scope(case),
                embedding_profile=ARMS[arm],
            )
            actual, index, reused, usage = service.ingest(
                m.target,
                sorted((OUT / "sources" / case.id).glob("*.md")),
                scope=scope,
                reviewed=True,
            )
            assert actual == m and index == reg["expected_indexes"][case.id][arm]["index_version"]
            assert not reused
            result[case.id] = {
                "manifest": actual.model_dump(mode="json"),
                "index_version": index,
                "usage": usage.model_dump(mode="json"),
            }
        write_new(OUT / ("indexes-" + arm + ".json"), result)
    finally:
        service.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["register", "metric", "bge", "qwen", "bind"])
    action = parser.parse_args().action
    if action == "register":
        register()
    elif action == "metric":
        verify_registration()
        values, settings = environment()
        write_new(OUT / "metric.json", run_async(metric(values, settings)))
    elif action == "bind":
        verify_registration()
        b, q = (json.loads((OUT / ("indexes-" + a + ".json")).read_bytes()) for a in ARMS)
        binding = {c.id: {"bge": b[c.id], "qwen": q[c.id]} for c in load().cases}
        binding["metric"] = json.loads((OUT / "metric.json").read_bytes())
        write_new(OUT / "bindings.json", binding)
        write_new(
            OUT / "bindings-seal.json",
            {
                "sha256": sha(OUT / "bindings.json"),
                "registration_sha256": sha(OUT / "registration.json"),
                "before_retrieval": True,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
    else:
        ingest_arm(action)


if __name__ == "__main__":
    main()
