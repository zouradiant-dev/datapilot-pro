"""Pre-register before retrieval; trusted synthetic data ingestion only in a new database."""

import argparse
import json
import os
import re
import secrets
from collections import Counter
from datetime import UTC, datetime

from datapilot.config import Settings
from datapilot.ingestion.common import digest
from datapilot.persistence.session import run_async
from datapilot.rag.contracts import RagScope
from datapilot.rag.models import create_embedding
from datapilot.rag.storage import IngestionService

from .common import (
    ARMS,
    BASE,
    HERE,
    OUT,
    ROOT,
    cases,
    manifest,
    order,
    select,
    sha,
    verify,
    write_new,
)


def environment():
    v = json.loads((OUT / "environment-private.json").read_bytes())
    assert v["DATAPILOT_ADMIN_DATABASE_URL"].endswith("/datapilot_test_qwen_expanded_v1_20261030")
    os.environ.update(v)
    os.environ.update(DATAPILOT_API_KEY="", DATAPILOT_LLM_MODE="fake", DATAPILOT_RUN_LIVE_TESTS="0")
    return v, Settings(_env_file=None, llm_mode="fake", api_key=None, model="expanded-scripted-v1")


def normalized(text, numbers=False):
    text = re.sub(r"[\s\W_]+", "", text.lower())
    return re.sub(r"\d+", "#", text) if numbers else text


def register():
    rows = cases()
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "registration.json").exists():
        raise ValueError("Registration exists; never overwrite Gold")
    question_counts = Counter(normalized(c.query, True) for c in rows)
    assert max(question_counts.values()) == 1, "Numeric-only question templates duplicated"
    historical = [
        "evaluation/qwen_business_pilot/cases.json",
        "tests/fixtures/rag/embedding-ab-dev.json",
        "tests/fixtures/rag/qwen-migration-dev.json",
        "tests/fixtures/rag/qwen-migration-safety.json",
        "evaluation/p7_citation_dev/cases.json",
        "tests/fixtures/rag/host-goal-requirements-v2.json",
    ]

    def strings(x):
        if isinstance(x, str):
            yield x
        elif isinstance(x, dict):
            for v in x.values():
                yield from strings(v)
        elif isinstance(x, list):
            for v in x:
                yield from strings(v)

    overlaps = []
    for name in historical:
        old = set(strings(json.loads((ROOT / name).read_bytes())))
        oldnorm = {normalized(t, True) for t in old}
        hit = [
            c.id
            for c in rows
            if normalized(c.query, True) in oldnorm or any(t in old for t in c.documents.values())
        ]
        assert not hit, (name, hit)
        overlaps.append(
            {"path": name, "sha256": sha(ROOT / name), "exact_or_numeric_normalized_matches": hit}
        )
    expected = {}
    for c in rows:
        folder = OUT / "sources" / c.id
        folder.mkdir(parents=True, exist_ok=False)
        for name, text in c.documents.items():
            (folder / name).write_bytes(text.encode("utf8"))
        if c.metric:
            (folder / "invoices.csv").write_bytes(c.metric_input["csv"].encode("utf8"))
        expected[c.id] = {}
        for arm in ARMS:
            m = manifest(c, arm)
            expected[c.id][arm] = {
                "manifest": m.model_dump(mode="json"),
                "index_version": digest(m),
            }
        assert (
            expected[c.id]["bge"]["manifest"]["sources"]
            == expected[c.id]["qwen"]["manifest"]["sources"]
        )
    parent = json.loads(
        (ROOT / "artifacts/p7/host-goal-repair-v2/implementation-final.json").read_bytes()
    )
    files = {n: h for n, h in parent["files"].items()}
    for n, h in files.items():
        assert sha(ROOT / n) == h, n
    extra = list(HERE.glob("*.py")) + [
        HERE / "cases.json",
        ROOT / "tests/test_qwen_expanded_quality.py",
    ]
    extra += list((ROOT / "evaluation/qwen_business_pilot").glob("*.py"))
    extra += [ROOT / "scripts/report_recovery_probe.py", ROOT / "scripts/p7_business_scoring.py"]
    extra += list((OUT / "sources").glob("*/*"))
    files.update({str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in extra})
    with (OUT / "collector-key-private.bin").open("xb") as f:
        f.write(secrets.token_bytes(32))
    sequence = [c.id for c in order("dev")] + [c.id for c in order("validation")]
    batchids = [sequence[i : i + 20] for i in range(0, 100, 20)]
    write_new(
        OUT / "registration.json",
        {
            "schema_version": "expanded-quality-registration-1",
            "registered_at": datetime.now(UTC).isoformat(),
            "cases_sha256": sha(HERE / "cases.json"),
            "files": files,
            "expected_indexes": expected,
            "planned_cases": 100,
            "planned_arm_observations": 200,
            "dev": 20,
            "validation": 80,
            "expected_runtime_per_arm": sum(not c.preflight for c in rows),
            "batches": batchids,
            "arm_order": "odd ordinal BGE/Qwen, even ordinal Qwen/BGE; serial",
            "validation_guard": (
                "Batch 2 requires frozen Batch 1 seal; no product/Gold/scorer "
                "changes allowed in Dev or Validation"
            ),
            "scoring": {
                "reuse": (
                    "Original signed Collector / Inspector / P3 / Report and Pilot "
                    "Gold adapter; extended bindings only"
                ),
                "strict": (
                    "Exact report status, Required fact set, valid references, exact "
                    "P3 numeric/unit and causal guard; expected unsupported "
                    "eligibility also correct"
                ),
                "parse": (
                    "Boolean unsupported eligibility vs independent Gold, not "
                    "arbitrary full NL classification; ambiguous excluded if null"
                ),
                "source": (
                    "First actual search Top-3 chunks, deduplicated Source; not "
                    "best-of replan/search"
                ),
                "denominators": (
                    "100 planned each; separate 20 Dev/80 Validation; authorized "
                    "retrieval and runtime/preflight separately; no-data null"
                ),
                "gate_a": (
                    "No false completed, unsupported published "
                    "facts/finance/causality, scope bypass, forged refs, unknown "
                    "resend"
                ),
                "gate_b": (
                    "Validation macro Required and Fact Coverage strictly higher; "
                    "micro Precision not lower; unrelated and stale returns not "
                    "increased"
                ),
                "gate_c": (
                    "Validation paired strict difference positive; 95% paired "
                    "bootstrap interval and exact McNemar reported separately, not "
                    "significant is not no effect"
                ),
                "uncertainty": (
                    "Seed 20261030, category-stratified paired bootstrap 10000 resamples; complete "
                    "cohorts only for primary inference; partial observed pairs "
                    "descriptive only"
                ),
                "stop": (
                    "First safety, infrastructure/unknown, freeze/budget/authorization"
                    " or collector integrity failure; no failed-case rerun; remaining "
                    "not_run"
                ),
            },
            "limits": {
                "root_calls": 8,
                "child_calls": 4,
                "tokens": 18000,
                "worker_turns": 4,
                "searches_max": 2,
                "script_searches": 1,
                "top_k": 3,
                "mcp_seconds": 10,
                "paid_calls": 0,
            },
            "independence_checks": overlaps,
            "limitations": [
                (
                    "Author is AI-assisted and knows product limitations, not "
                    "independent human blind review"
                ),
                "Shared noise documents intentionally repeated as controls",
                "Ten distinct invoice snapshots reuse one reviewed paid-invoice recipe",
                (
                    "Related SaaS themes can overlap semantically with previous Dev "
                    "despite zero exact/normalized overlap"
                ),
                (
                    "Validation outputs not inspected before Dev is sealed; "
                    "infrastructure ingestion is not query evaluation"
                ),
            ],
        },
    )
    print("Registered 100 cases, 20 Dev/80 Validation, no retrieval executed")


async def metrics():
    from decimal import Decimal

    from datapilot.datasets.contracts import ImportRequest
    from datapilot.ingestion.confirmation import confirm_schema
    from datapilot.ingestion.contracts import ParseOptions
    from datapilot.ingestion.parser import parse_file
    from datapilot.ingestion.profiling import propose_schema
    from datapilot.ingestion.service import IngestionService as DatasetIngest
    from datapilot.runtime.mcp_client import dataset_session
    from datapilot.semantics.contracts import MetricDraft, SemanticDraft
    from datapilot.semantics.registry import RegistryStore

    values, settings = environment()
    results = {}
    for c in cases():
        if not c.metric:
            continue
        select(c)
        folder = OUT / "sources" / c.id
        path = folder / "invoices.csv"
        parsed = parse_file(path, options=ParseOptions(header="present"))
        confirm = confirm_schema(parsed, propose_schema(parsed), reviewed=True)
        ingestor = DatasetIngest(
            values["DATAPILOT_INGEST_DATABASE_URL"], storage_dir=folder / "uploads"
        )
        registry = RegistryStore(values["DATAPILOT_REGISTRY_DATABASE_URL"])
        try:
            imported = ingestor.import_file(
                path, confirm, ImportRequest(name="expanded-v1-" + c.id)
            )
            async with dataset_session(settings, BASE.dataset_scope(c)) as tools:
                schema = await tools.schema(imported.dataset_id)
                table = schema.tables[0]
                start, end = c.metric_input["start"], c.metric_input["end_exclusive"]
                independent = await tools.execute(
                    imported.dataset_id,
                    f'SELECT SUM(amount_cents)/100.0 FROM uploads."{table.physical_name}" '
                    f"WHERE payment_status='paid' AND currency='CNY' "
                    f"AND invoice_date >= DATE '{start}' AND invoice_date < DATE '{end}'",
                )
            assert Decimal(independent.result.rows[0][0]) == Decimal(c.metric_input["value"])
            semantic = registry.confirm_semantics(
                SemanticDraft.model_validate_json(
                    json.dumps(
                        {
                            "dataset_id": imported.dataset_id,
                            "dataset_version": 1,
                            "entities": [
                                {
                                    "entity": "invoices",
                                    "table_id": table.table_id,
                                    "grain": ["invoice_id"],
                                    "amount_storage": "minor",
                                    "coverage_start": start,
                                    "coverage_end_exclusive": end,
                                    "fields": {
                                        "record_id": "invoice_id",
                                        "amount": "amount_cents",
                                        "invoice_date": "invoice_date",
                                        "payment_status": "payment_status",
                                        "currency": "currency",
                                    },
                                }
                            ],
                        }
                    )
                ),
                reviewed=True,
            )
            metric = registry.confirm_metric(
                MetricDraft(
                    dataset_id=imported.dataset_id,
                    dataset_version=1,
                    semantic_version=semantic.semantic_version,
                    metric_id="paid_invoice_revenue",
                ),
                reviewed=True,
            )
            results[c.id] = {
                "dataset": imported.model_dump(mode="json"),
                "semantic": semantic.model_dump(mode="json"),
                "metric": metric.model_dump(mode="json"),
                "independent_sql": independent.model_dump(mode="json"),
                "review_basis": (
                    "Public synthetic host test definition, "
                    "not production or independent human approval"
                ),
            }
        finally:
            registry.close()
            ingestor.close()
    write_new(OUT / "metrics.json", results)


def ingest(arm):
    reg = verify()
    values, _ = environment()
    service = IngestionService(
        values["DATAPILOT_RAG_INGEST_DATABASE_URL"], create_embedding(ARMS[arm])
    )
    result = {}
    try:
        for c in cases():
            select(c)
            m = manifest(c, arm)
            scope = RagScope(
                owner=m.target.owner,
                allow_saas=not c.metric,
                datasets=BASE.dataset_scope(c),
                embedding_profile=ARMS[arm],
            )
            actual, index, reused, usage = service.ingest(
                m.target, sorted((OUT / "sources" / c.id).glob("*.md")), scope=scope, reviewed=True
            )
            assert (
                actual == m
                and index == reg["expected_indexes"][c.id][arm]["index_version"]
                and not reused
            )
            result[c.id] = {
                "manifest": actual.model_dump(mode="json"),
                "index_version": index,
                "usage": usage.model_dump(mode="json"),
            }
    finally:
        service.close()
    write_new(OUT / ("indexes-" + arm + ".json"), result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["register", "metrics", "bge", "qwen", "bind"])
    action = parser.parse_args().action
    if action == "register":
        register()
        return
    verify()
    if action == "metrics":
        run_async(metrics())
    elif action in ARMS:
        ingest(action)
    else:
        arm_data = {a: json.loads((OUT / ("indexes-" + a + ".json")).read_bytes()) for a in ARMS}
        metric_data = json.loads((OUT / "metrics.json").read_bytes())
        b = {
            c.id: {**{a: arm_data[a][c.id] for a in ARMS}, "metric": metric_data.get(c.id)}
            for c in cases()
        }
        write_new(OUT / "bindings.json", b)
        write_new(
            OUT / "bindings-seal.json",
            {
                "sha256": sha(OUT / "bindings.json"),
                "registered_sha256": sha(OUT / "registration.json"),
                "implementation_sha256": sha(OUT / "registration-r2.json"),
                "created_at": datetime.now(UTC).isoformat(),
                "before_retrieval": True,
            },
        )


if __name__ == "__main__":
    main()
