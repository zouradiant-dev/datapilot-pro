"""Trusted public-Dev assembly and new seals; no old-pack edits or provider calls."""

import csv
import hashlib
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from p7_holdout_pack import sha
from p7_policy_smoke import Case, Gold
from p7_policy_smoke_run import base_config
from p7_policy_smoke_worker import POLICY
from p7_smoke_pack import runtime_files, write_new

from datapilot.datasets.contracts import DatasetScope
from datapilot.ingestion.common import digest
from datapilot.persistence.session import run_async
from datapilot.rag.contracts import RagScope, Target
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService, make_pin
from datapilot.reporting.contracts import CitationPolicy, CitationSource, DocumentGoal, ReportScope
from datapilot.runtime.mcp_client import dataset_session, metric_session


def oracle(path):
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return str(
        sum(
            (
                Decimal(r["amount_cents"]) / 100
                for r in rows
                if r["payment_status"] == "paid"
                and r["currency"] == "CNY"
                and "2025-10-01" <= r["invoice_date"] < "2025-11-01"
            ),
            Decimal("0"),
        )
    )


def source_pin(binding, name):
    source = next(s for s in binding["manifest"]["sources"] if s["name"] == name)
    return CitationSource(
        corpus_id=binding["scope"]["corpora"][0]["corpus_id"],
        index_version=binding["scope"]["corpora"][0]["index_version"],
        source_id=source["source_id"],
        document_id=source["document_id"],
        version=source["version"],
        source_sha256=source["text_sha256"],
    )


def assemble(dev, settings, values, output):
    """Use the existing public fixture; never consume formal Holdout Gold/assets."""
    from test_document_fact_postgres import host_fact

    output.mkdir(parents=True, exist_ok=False)
    bindings = json.loads((dev.OUT / "bindings.json").read_bytes())["bindings"]
    csv_path = dev.OUT / "cp07/invoices.csv"
    expected_value = oracle(csv_path)
    (output / "assets").mkdir()
    shutil.copyfile(csv_path, output / "assets/invoices.csv")
    cases, golds = [], {}
    for i, fixture_id in [(2, "cp09"), (3, "cp06"), (4, "cp07"), (5, "cp10"), (6, "cp12")]:
        original = next(c for c in dev.cases() if c["id"] == fixture_id)
        binding = bindings[fixture_id]
        rag, scope = dev.host_scope(original, binding)
        scope.partial_evidence_policy = "partial-facts-v1"
        scope.rag_query_policy = "original-first-v1"
        required = [source_pin(binding, name) for name in original["required"]]
        supplements = []
        if fixture_id in {"cp09", "cp07"}:
            name, quote = (
                ("rounding.md", "展示值向上取整到整MiB")
                if fixture_id == "cp09"
                else ("delivery.md", "电子账单补寄采用邮件队列")
            )
            supplements = [host_fact(binding, name, "supplement", quote)]
        scope.citation_policy = CitationPolicy(
            goal_sha256=hashlib.sha256(scope.question.encode()).hexdigest(),
            required_sources=required,
            supplementary_claims=supplements,
        )
        case = Case(
            case_id=f"tps-{i:02}",
            lane="sql_rag" if scope.metrics else "rag_only",
            scope=scope,
            rag_scope=rag,
        )
        cases.append(case)
        sources = {s["name"]: s["document_id"] for s in binding["manifest"]["sources"]}
        forbidden = [sources[original["irrelevant"]]] if original.get("irrelevant") else []
        golds[case.case_id] = Gold(
            case_id=case.case_id,
            completion=original["expected"],
            proved_facts=[f[0] for f in original["facts"] if f[1]],
            missing_facts=[f[0] for f in original["facts"] if not f[1]],
            supplements=[f.fact_id for f in supplements],
            allowed_documents=[v for v in sources.values() if v not in forbidden],
            forbidden_documents=forbidden,
        )
    combined = next(c for c in cases if c.case_id == "tps-04")
    scope = ReportScope(
        owner=combined.scope.owner,
        question="请核对2025年10月已支付CNY账单收入，排除未支付记录，返回可复核证据。",
        datasets=combined.scope.datasets,
        metrics=combined.scope.metrics,
    )
    cases.insert(0, Case(case_id="tps-01", lane="sql_only", scope=scope, rag_scope=None))
    golds["tps-01"] = Gold(case_id="tps-01", completion="completed")
    # Preserve the exact known English control and its original completed expectation.
    source = Path(__file__).resolve().parents[1] / "tests/fixtures/rag/keys.md"
    copy = output / "assets/keys.md"
    copy.write_bytes(source.read_bytes())
    owner = combined.scope.owner
    rag = RagScope(owner=owner, allow_saas=True)
    ingestor = IngestionService(values["DATAPILOT_RAG_INGEST_DATABASE_URL"], LocalEmbedding())
    try:
        m, version, _, _ = ingestor.ingest(
            Target(corpus_id=str(uuid4()), owner=owner), [copy], scope=rag, reviewed=True
        )
    finally:
        ingestor.close()
    rag.corpora = [make_pin(m, version)]
    binding = {"scope": rag.model_dump(mode="json"), "manifest": m.model_dump(mode="json")}
    q = "How should API keys be rotated?"
    scope = ReportScope(
        owner=owner,
        question=q,
        datasets=DatasetScope(),
        metrics=[],
        document_goal=DocumentGoal(
            goal_id="documents", question=q, metric_goals=[], purpose="summary"
        ),
        partial_evidence_policy="partial-facts-v1",
        rag_query_policy="original-first-v1",
        citation_policy=CitationPolicy(
            goal_sha256=hashlib.sha256(q.encode()).hexdigest(),
            required_sources=[source_pin(binding, "keys.md")],
        ),
    )
    cases.append(Case(case_id="tps-07", lane="rag_only", scope=scope, rag_scope=rag))
    golds["tps-07"] = Gold(
        case_id="tps-07",
        completion="completed",
        allowed_documents=[m.sources[0].document_id],
        known_quality_limitation=True,
    )
    denied = cases[1].model_copy(deep=True)
    denied.case_id = "tps-08"
    denied.scope.owner = denied.rag_scope.owner = "unrelated-policy-smoke-owner"
    denied.preflight_denial = "DOCUMENT_NOT_AUTHORIZED"
    cases.append(denied)
    golds["tps-08"] = Gold(case_id="tps-08", completion="blocked")
    pins = {}

    async def observe():
        from p7_smoke_run import table_snapshots

        async with dataset_session(settings, combined.scope.datasets) as tools:
            schema = await tools.schema(combined.scope.metrics[0].dataset_id)
        pins["_schema"] = schema.model_dump(mode="json")
        if schema.source_sha256 != sha(csv_path.read_bytes()):
            raise ValueError("Independent Oracle bytes differ from the materialized source")
        pins["_table_snapshots"] = await table_snapshots(settings, {"schema": pins["_schema"]})
        for case in cases:
            pins[case.case_id] = {}
            if not case.scope.metrics:
                continue
            async with metric_session(settings, case.scope.datasets) as tools:
                for request in case.scope.metrics:
                    context = await tools.context(request)
                    expected = {
                        k: getattr(context, k)
                        for k in ["source_sha256", "semantic_sha256", "metric_sha256"]
                    }
                    pins[case.case_id][request.goal_id] = expected
                    golds[case.case_id].metrics[request.goal_id] = expected | {
                        "value": expected_value,
                        "unit": "CNY",
                    }

    run_async(observe())
    write_new(output / "cases.json", [c.model_dump(mode="json") for c in cases])
    write_new(output / "gold.json", {k: v.model_dump(mode="json") for k, v in golds.items()})
    write_new(output / "pins.json", pins)
    return cases, pins


def seal(root, base, metadata):
    files = runtime_files(root)
    source_sha = digest(files)
    snapshot = base / ("frozen-source-" + source_sha[:12])
    cases = [
        Case.model_validate_json(json.dumps(c))
        for c in json.loads((base / "cases.json").read_bytes())
    ]
    write_new(base / "budget.json", POLICY)
    write_new(
        base / "protocol.json",
        {
            "kind": "public_nonblind_three_policy_dev_not_holdout",
            "case_order": [c.case_id for c in cases],
            "case_denominator": 8,
            "runtime_denominator": 7,
            "host_denial_denominator": 1,
            "success": (
                "exact completion, P3 amount/unit/version, required/supplement fact coverage, "
                "authorized citations and original query"
            ),
            "known_english": (
                "Gold remains completed; short-query miss is a strict quality failure, "
                "never an expected refusal"
            ),
            "ordinary_failure": "record and continue",
            "critical_failure": "stop and retain reservations/not_run",
            "independent_human_review_claimed": False,
        },
    )
    write_new(
        base / "evaluator.json",
        {
            "scorers": {
                n: files[n]
                for n in [
                    "scripts/p7_policy_smoke.py",
                    "scripts/p7_business_scoring.py",
                    "scripts/p7_business_evaluator.py",
                ]
            }
        },
    )
    asset_paths = [
        base / p
        for p in [
            "cases.json",
            "gold.json",
            "pins.json",
            "protocol.json",
            "budget.json",
            "evaluator.json",
        ]
    ]
    asset_paths += list((base / "assets").glob("*"))
    configs = {
        mode: {c.case_id: digest(base_config(c, mode, source_sha)) for c in cases}
        for mode in ["fake", "live"]
    }
    snapshot.mkdir(exist_ok=False)
    for name in files:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    manifest = {
        "schema_version": "three-policy-freeze-1",
        "created_at": datetime.now(UTC).isoformat(),
        "freeze_id": "p7-three-policy-dev-v1-" + source_sha[:12],
        "source_sha256": source_sha,
        "snapshot": snapshot.relative_to(root).as_posix(),
        "files": files,
        "assets": {p.relative_to(base).as_posix(): sha(p.read_bytes()) for p in asset_paths},
        "config_hashes": configs,
        "live_authorized": False,
        **metadata,
    }
    write_new(base / "implementation.json", manifest)
    anchor = {
        "freeze_id": manifest["freeze_id"],
        "manifest_sha256": sha((base / "implementation.json").read_bytes()),
        "manifest_path": (base / "implementation.json").relative_to(root).as_posix(),
        "live_authorized": False,
    }
    write_new(base / "anchor.json", anchor)
    (base / "empty-fixtures").mkdir()
    return anchor
