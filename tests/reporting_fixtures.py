"""Public synthetic reporting fixtures; never imports an experiment or private Pin."""

import json
import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from datapilot.config import Settings
from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.ingestion.common import digest
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService as DatasetIngest
from datapilot.rag.contracts import ChunkCitation, RagScope, Target
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService, make_pin
from datapilot.reporting.contracts import DocumentFact, DocumentGoal, ReportScope
from datapilot.semantics.contracts import MetricDraft, MetricRequest, MetricWindow, SemanticDraft
from datapilot.semantics.registry import RegistryStore

ROLES = (
    "admin",
    "owner",
    "seed",
    "reader",
    "ingest",
    "upload_reader",
    "registry",
    "runtime",
    "checkpoint_owner",
    "rag_ingest",
    "rag_reader",
    "web",
    "maintenance",
)


def validate_environment(values):
    """An explicit test DB identity and isolated role profile, never .env fallback."""
    try:
        if (
            values.get("DATAPILOT_RUN_DB_TESTS") != "1"
            or values.get("DATAPILOT_TEST_ISOLATED") != "1"
        ):
            raise ValueError
        urls = {r: make_url(values[f"DATAPILOT_{r.upper()}_DATABASE_URL"]) for r in ROLES}
        first = urls["reader"]
        if not first.host or not first.database or not first.database.startswith("datapilot_test_"):
            raise ValueError
        for role, url in urls.items():
            if (
                url.drivername != "postgresql+psycopg"
                or not url.password
                or url.query
                or url.username != ("postgres" if role == "admin" else "datapilot_" + role)
                or (url.host, url.port or 5432, url.database)
                != (first.host, first.port or 5432, first.database)
            ):
                raise ValueError
        return Settings(
            _env_file=None,
            llm_mode="fake",
            api_key=None,
            **{
                r + "_database_url": str(urls[r].render_as_string(hide_password=False))
                for r in ("reader", "upload_reader", "runtime", "rag_reader")
            },
        )
    except (ValueError, KeyError, sa.exc.ArgumentError):
        raise ValueError("Explicit isolated test database and designated roles required") from None


@pytest.fixture(scope="session")
def portable_pg():
    if os.getenv("DATAPILOT_RUN_DB_TESTS") != "1":
        pytest.skip("Real PostgreSQL integration requires DATAPILOT_RUN_DB_TESTS=1")
    settings = validate_environment(os.environ)
    engine = sa.create_engine(
        settings.rag_reader_database_url.get_secret_value(),
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql("SET LOCAL statement_timeout='5s'")
            assert int(conn.exec_driver_sql("SHOW server_version_num").scalar_one()) // 10000 == 17
            assert conn.exec_driver_sql(
                "SELECT extversion FROM pg_extension WHERE extname='vector'"
            ).scalar_one()
            flags = conn.exec_driver_sql(
                "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls "
                "FROM pg_roles WHERE rolname=current_user"
            ).one()
            assert not any(flags)
    finally:
        engine.dispose()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATAPILOT_API_KEY", "")
        patch.setenv("DATAPILOT_LLM_MODE", "fake")
        patch.setenv("DATAPILOT_RUN_LIVE_TESTS", "0")
        yield settings


@pytest.fixture(scope="module")
def reporting_output(request, tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(request.module, "OUT", tmp_path_factory.mktemp(request.module.__name__))
        yield


def metric_fixture(values, folder, owner):
    """New toy data and explicit synthetic host definitions, not production approval."""
    path = folder / "invoices.csv"
    path.write_text(
        "invoice_id,amount_cents,invoice_date,payment_status,currency\n"
        "cp-i01,63745,2025-10-08,paid,CNY\n"
        "cp-i02,1199,2025-10-09,unpaid,CNY\n",
        encoding="utf-8",
    )
    parsed = parse_file(path, options=ParseOptions(header="present"))
    confirmation = confirm_schema(parsed, propose_schema(parsed), reviewed=True)
    ingest = DatasetIngest(values["DATAPILOT_INGEST_DATABASE_URL"], storage_dir=folder / "uploads")
    registry = RegistryStore(values["DATAPILOT_REGISTRY_DATABASE_URL"])
    try:
        imported = ingest.import_file(path, confirmation, ImportRequest(name=owner))
        from datapilot.datasets.repository import DatasetRepository

        scope = DatasetScope(
            bindings=[DatasetBinding(dataset_id=imported.dataset_id, version=imported.version)]
        )
        reader = DatasetRepository(values["DATAPILOT_UPLOAD_READER_DATABASE_URL"], scope)
        try:
            schema = reader.schema(imported.dataset_id)
        finally:
            reader.close()
        table = schema.tables[0]
        semantic = registry.confirm_semantics(
            SemanticDraft.model_validate_json(
                json.dumps(
                    {
                        "dataset_id": schema.dataset_id,
                        "dataset_version": schema.version,
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
                                "coverage_start": "2025-10-01",
                                "coverage_end_exclusive": "2025-11-01",
                            }
                        ],
                    }
                )
            ),
            reviewed=True,
        )
        definition = registry.confirm_metric(
            MetricDraft(
                dataset_id=schema.dataset_id,
                dataset_version=schema.version,
                semantic_version=semantic.semantic_version,
                metric_id="paid_invoice_revenue",
            ),
            reviewed=True,
        )
        request = MetricRequest(
            goal_id="revenue",
            dataset_id=schema.dataset_id,
            dataset_version=schema.version,
            semantic_version=semantic.semantic_version,
            metric_version=definition.metric_version,
            metric_id="paid_invoice_revenue",
            window=MetricWindow(start=date(2025, 10, 1), end_exclusive=date(2025, 11, 1)),
        )
        return {
            "scope": scope.model_dump(mode="json"),
            "request": request.model_dump(mode="json"),
            "semantic": semantic.model_dump(mode="json"),
            "metric": definition.model_dump(mode="json"),
            "gold_decimal": "637.45",
            "review_basis": (
                "Synthetic trusted-host fixture only; not independent human review "
                "or production definition approval"
            ),
        }
    finally:
        registry.close()
        ingest.close()


def host_scope(case, binding):
    rag = RagScope.model_validate_json(json.dumps(binding["scope"]))
    facts = []
    for fact_id, name, quote in case["facts"]:
        proof = {}
        if name:
            source = next(s for s in binding["manifest"]["sources"] if s["name"] == name)
            assert len(source["chunks"]) == 1 and quote in case["documents"][name]
            citation = ChunkCitation(
                **source["chunks"][0],
                corpus_id=rag.corpora[0].corpus_id,
                index_version=rag.corpora[0].index_version,
                source_id=source["source_id"],
                document_id=source["document_id"],
                version=source["version"],
                source_sha256=source["text_sha256"],
                model_revision=binding["manifest"]["model"]["revision"],
                chunker_sha256=digest(binding["manifest"]["chunker"]),
                score=0.0,
            )
            proof = {
                "citation": citation,
                "quotation": quote,
                "confirmation_ref": "public-synthetic-host-fixture-not-human-approval:"
                + case["id"],
            }
        facts.append(
            DocumentFact(
                fact_id=fact_id, description="Pre-registered synthetic literal fact", **proof
            )
        )
    metrics = (
        [MetricRequest.model_validate_json(json.dumps(binding["metric"]["request"]))]
        if binding["metric"]
        else []
    )
    scope = ReportScope(
        owner=rag.owner,
        question=case["question"],
        datasets=rag.datasets,
        metrics=metrics,
        causal_requested=case.get("causal", False),
        document_goal=DocumentGoal(
            goal_id="documents",
            question=case["question"],
            metric_goals=[r.goal_id for r in metrics],
            purpose="facts",
            required_facts=facts,
        ),
    )
    return rag, scope


@pytest.fixture(scope="session")
def reporting_dev(portable_pg, tmp_path_factory):
    folder = tmp_path_factory.mktemp("public-reporting-sources")
    cases = json.loads((Path(__file__).parent / "fixtures/rag/reporting-cases.json").read_bytes())[
        "cases"
    ]
    owner = "public-reporting-" + uuid4().hex[:16]
    embedding = LocalEmbedding()  # Original pinned files; no download or fake vectors.
    bindings = {}
    for case in cases:
        assets = folder / case["id"]
        assets.mkdir()
        paths = []
        for name, text in case["documents"].items():
            path = assets / name
            path.write_text(text + "\n", encoding="utf-8")
            paths.append(path)
        metric = metric_fixture(os.environ, assets, owner) if case.get("metric") else None
        datasets = (
            DatasetScope.model_validate_json(json.dumps(metric["scope"]))
            if metric
            else DatasetScope()
        )
        scope = RagScope(owner=owner, allow_saas=not bool(metric), datasets=datasets)
        target = Target(
            corpus_id=str(uuid4()),
            owner=owner,
            dataset_id=datasets.bindings[0].dataset_id if metric else None,
            dataset_version=datasets.bindings[0].version if metric else None,
        )
        ingestor = IngestionService(os.environ["DATAPILOT_RAG_INGEST_DATABASE_URL"], embedding)
        try:
            manifest, version, reused, _ = ingestor.ingest(
                target, paths, scope=scope, reviewed=True
            )
            assert not reused
        finally:
            ingestor.close()
        scope.corpora = [make_pin(manifest, version)]
        bindings[case["id"]] = {
            "scope": scope.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
            "metric": metric,
        }
    (folder / "bindings.json").write_text(
        json.dumps({"bindings": bindings}, ensure_ascii=False), encoding="utf-8"
    )
    return SimpleNamespace(OUT=folder, cases=lambda: cases, host_scope=host_scope), portable_pg
