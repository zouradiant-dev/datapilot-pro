"""Real PostgreSQL 17 + MCP + deterministic recipes; never a live-model result."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa

from datapilot.agents.sql import SQLAgent
from datapilot.contracts import AgentFailure
from datapilot.data.semantic_demo import mapping_draft
from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.datasets.repository import DatasetRepository
from datapilot.db.management import management_url
from datapilot.harness.metric_verification import make_evidence, verify_execution
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService
from datapilot.runtime.mcp_client import metric_session, server_environment
from datapilot.semantics.contracts import MetricDraft, MetricRequest, MetricWindow
from datapilot.semantics.recipes import compile_sql, semantics_match
from datapilot.semantics.registry import RegistryStore, verify_registry_role
from datapilot.semantics.repository import MetricRepository
from datapilot.semantics.service import analyze

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/semantics/saas_metrics.xlsx"


def scope(schema):
    return DatasetScope(
        bindings=[DatasetBinding(dataset_id=schema.dataset_id, version=schema.version)]
    )


@pytest.fixture
def metric_data(pg_settings):
    service = IngestionService(management_url("ingest"), storage_dir=ROOT / "artifacts/p3/sources")
    parsed = parse_file(SOURCE, options=ParseOptions(header="present"))
    confirmation = confirm_schema(parsed, propose_schema(parsed), reviewed=True)
    imported = service.import_file(
        SOURCE, confirmation, ImportRequest(name="p3-semantic-acceptance")
    )
    repository = DatasetRepository(
        pg_settings.upload_reader_database_url.get_secret_value(),
        DatasetScope(
            bindings=[DatasetBinding(dataset_id=imported.dataset_id, version=imported.version)]
        ),
    )
    schema = repository.schema(imported.dataset_id)
    store = RegistryStore(management_url("registry"))
    semantic = store.confirm_semantics(mapping_draft(schema), reviewed=True)

    def request(kind, *, feature=None):
        metric = store.confirm_metric(
            MetricDraft(
                dataset_id=schema.dataset_id,
                dataset_version=schema.version,
                semantic_version=semantic.semantic_version,
                metric_id=kind,
                feature=feature,
            ),
            reviewed=True,
        )
        return MetricRequest(
            goal_id=kind,
            dataset_id=schema.dataset_id,
            dataset_version=schema.version,
            semantic_version=semantic.semantic_version,
            metric_id=kind,
            metric_version=metric.metric_version,
            **(
                {"as_of": date(2025, 10, 31)}
                if kind == "active_subscriptions"
                else {
                    "window": MetricWindow(start=date(2025, 10, 1), end_exclusive=date(2025, 11, 1))
                }
            ),
        )

    yield schema, store, repository, request
    store.close()
    repository.close()
    service.close()


async def test_real_xlsx_pg_mcp_five_metrics_evidence_and_unanswerable(metric_data, pg_settings):
    schema, store, repository, request = metric_data
    requests = [
        request(kind)
        for kind in (
            "paid_invoice_revenue",
            "subscription_churn",
            "customer_churn",
            "active_subscriptions",
            "usage",
            "mrr",
        )
    ]
    report = await analyze(pg_settings, store, requests)
    golds = ["300", "0.666666666667", "0.4", "4", "35"]
    for outcome, expected in zip(report.outcomes[:5], golds, strict=True):
        assert outcome.verification.verdict == "verified", outcome.model_dump_json()
        assert Decimal(outcome.value.value) == Decimal(expected)
        artifact = store.get_evidence(outcome.evidence_id)
        assert artifact.source_sha256 == schema.source_sha256 and artifact.query_sha256
        assert artifact.result_sha256 and artifact.metric_version == outcome.request.metric_version
        assert store.get_verification(outcome.verification.verification_id) == outcome.verification
        assert outcome.evidence_id in report.markdown
    assert report.outcomes[-1].verification.verdict == "unavailable"
    assert report.outcomes[-1].value is None
    assert "mrr_definition_missing" in {m.code for m in report.outcomes[-1].missing}
    # Independent literal SQL gold through the original controlled Dataset repository.
    table = next(t for t in schema.tables if t.source_name == "invoices")
    result = repository.execute(
        schema.dataset_id,
        f'SELECT SUM(amount_cents) / 100.0 AS value FROM uploads."{table.physical_name}" '
        "WHERE payment_status='paid' AND currency='CNY' "
        "AND invoice_date >= DATE '2025-10-01' AND invoice_date < DATE '2025-11-01'",
    )
    assert Decimal(result.result.rows[0][0]) == Decimal("300")
    requests_path = ROOT / "artifacts/p3/acceptance-requests.json"
    requests_path.write_text(
        json.dumps([r.model_dump(mode="json") for r in requests], indent=2), encoding="utf-8"
    )
    (ROOT / "artifacts/p3/acceptance-report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )


async def test_real_csv_pg_metric_and_feature_version(metric_data, pg_settings):
    _, store, _, request = metric_data
    source = SOURCE.parent / "invoices.csv"
    parsed = parse_file(source, options=ParseOptions(header="present"))
    confirmation = confirm_schema(parsed, propose_schema(parsed), reviewed=True)
    service = IngestionService(management_url("ingest"), storage_dir=ROOT / "artifacts/p3/sources")
    try:
        imported = service.import_file(source, confirmation, ImportRequest(name="p3-semantic-csv"))
        repo = DatasetRepository(
            pg_settings.upload_reader_database_url.get_secret_value(),
            DatasetScope(
                bindings=[DatasetBinding(dataset_id=imported.dataset_id, version=imported.version)]
            ),
        )
        try:
            schema = repo.schema(imported.dataset_id)
            # CSV's source_name is its filename, not a guessed business entity.
            schema.tables[0].source_name = "invoices"
            sem = store.confirm_semantics(mapping_draft(schema), reviewed=True)
            metric = store.confirm_metric(
                MetricDraft(
                    dataset_id=schema.dataset_id,
                    dataset_version=schema.version,
                    semantic_version=sem.semantic_version,
                    metric_id="paid_invoice_revenue",
                ),
                reviewed=True,
            )
            req = MetricRequest(
                goal_id="csv_revenue",
                dataset_id=schema.dataset_id,
                dataset_version=schema.version,
                semantic_version=sem.semantic_version,
                metric_id="paid_invoice_revenue",
                metric_version=metric.metric_version,
                window=MetricWindow(start=date(2025, 10, 1), end_exclusive=date(2025, 11, 1)),
            )
            report = await analyze(pg_settings, store, [req])
            assert report.outcomes[0].verification.verdict == "verified"
            assert Decimal(report.outcomes[0].value.value) == 300
        finally:
            repo.close()
    finally:
        service.close()
    filtered = request("usage", feature="dashboard")
    report = await analyze(pg_settings, store, [filtered])
    assert report.outcomes[0].value.value == "30"


def test_registry_review_versions_and_role_boundaries(metric_data):
    schema, store, _, request = metric_data
    draft = mapping_draft(schema)
    with pytest.raises(AgentFailure, match="review"):
        store.confirm_semantics(draft, reviewed=False)
    first = store.confirm_semantics(draft, reviewed=True)
    assert store.confirm_semantics(draft, reviewed=True) == first
    updated = draft.model_copy(deep=True)
    updated.entities[0].coverage_start = date(2025, 2, 1)
    new = store.confirm_semantics(updated, reviewed=True)
    assert new.semantic_version != first.semantic_version
    old_req = request("paid_invoice_revenue")
    assert old_req.semantic_version == first.semantic_version
    with store.engine.begin() as conn:
        verify_registry_role(conn)
        assert not conn.exec_driver_sql(
            "SELECT COALESCE(bool_or(has_table_privilege(current_user,c.oid,'SELECT')),false) "
            "FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid WHERE n.nspname='saas'"
        ).scalar_one()
        for suffix in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not conn.execute(
                sa.text("SELECT has_table_privilege(current_user,'catalog.evidence',:p)"),
                {"p": suffix},
            ).scalar_one()
        for schema_name in ("catalog", "uploads", "saas"):
            assert not conn.execute(
                sa.text("SELECT has_schema_privilege(current_user,:s,'CREATE')"), {"s": schema_name}
            ).scalar_one()
    # A direct read of business data is denied even outside an explicit read-only transaction.
    with store.engine.connect() as conn, pytest.raises(sa.exc.DBAPIError):
        conn.exec_driver_sql("SELECT COUNT(*) FROM saas.customers")
    for role in ("reader", "upload_reader", "ingest"):
        engine = sa.create_engine(management_url(role), hide_parameters=True)
        try:
            with engine.connect() as conn:
                assert not conn.exec_driver_sql(
                    "SELECT has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE') "
                    "FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid "
                    "WHERE n.nspname='catalog' AND c.relname='metric_versions'"
                ).scalar_one()
        finally:
            engine.dispose()


async def test_scoped_metadata_evidence_and_writer_credentials_never_reach_mcp(
    metric_data, pg_settings, monkeypatch
):
    schema, store, _, request = metric_data
    req = request("paid_invoice_revenue")
    monkeypatch.setenv("DATAPILOT_REGISTRY_DATABASE_URL", "must-not-leak")
    assert not any("REGISTRY" in k for k in server_environment(pg_settings))
    async with metric_session(pg_settings, scope(schema)) as tools:
        context = await tools.context(req)
        assert len(context.table.columns) == 5
        execution = await SQLAgent(None, tools).run_metric(req)
        artifact = make_evidence(execution)
        store.append_evidence(artifact)
        assert await tools.evidence(schema.dataset_id, artifact.evidence_id) == artifact
        with pytest.raises(AgentFailure):
            await tools.call("confirm_metric", {})
        with pytest.raises(AgentFailure):
            await tools.evidence(str(uuid4()), artifact.evidence_id)
        bad = req.model_copy(update={"dataset_version": schema.version + 1})
        with pytest.raises(AgentFailure) as error:
            await tools.context(bad)
        assert error.value.error.code == "DATASET_NOT_AUTHORIZED"
        with pytest.raises(AgentFailure):
            await tools.execute(schema.dataset_id, "DELETE FROM saas.customers")
        with pytest.raises(AgentFailure):
            await tools.execute(schema.dataset_id, "SELECT * FROM catalog.metric_versions")


@pytest.mark.parametrize("mutation", ["paid_filter", "join", "right_boundary", "unit"])
def test_real_wrong_sql_rejected_by_semantics_and_independent_arithmetic(metric_data, mutation):
    _, _, repository, request = metric_data
    req = request("paid_invoice_revenue")
    metric_repo = MetricRepository(repository)
    context = metric_repo.context(req)
    sql = compile_sql(context, req)
    if mutation == "paid_filter":
        sql = sql.replace("'paid'", "'unpaid'")
    elif mutation == "unit":
        sql = sql.replace(" / 100", " / 1")
    elif mutation == "right_boundary":
        sql = sql.replace(" < CAST(", " <= CAST(")
    else:
        sql = sql.replace(
            " AS s", f' AS s JOIN uploads."{context.table.physical_name}" t ON TRUE', 1
        )
    assert not semantics_match(sql, context, req)
    from datapilot.semantics.contracts import MetricExecution

    execution = MetricExecution(
        request=req,
        context=context,
        candidate_sql=sql,
        primary=repository.execute(req.dataset_id, sql),
        proof=metric_repo.proof(req),
    )
    artifact = make_evidence(execution)
    check = verify_execution(execution, artifact, artifact)
    assert check.verdict == "rejected"
    assert check.checks[2].status == "failed" and check.checks[3].status == "failed"


def test_recomputation_paginates_and_rejects_quota(metric_data, pg_settings, monkeypatch):
    schema, _, _, request = metric_data
    req = request("usage")
    repo = DatasetRepository(
        pg_settings.upload_reader_database_url.get_secret_value(), scope(schema), max_rows=2
    )
    try:
        metrics = MetricRepository(repo)
        proof = metrics.proof(req)
        assert proof.status == "computed" and proof.source_rows == 5 and len(proof.page_hashes) == 3
        monkeypatch.setattr("datapilot.semantics.repository.PROOF_MAX_BYTES", 1)
        assert metrics.proof(req).status == "unavailable"
        # Trusted metadata cache corruption simulation; must fail closed, never claim verification.
        selected = repo.pinned[schema.dataset_id]
        next(t for t in selected.tables if t.source_name == "usage_events").row_count = 20_001
        proof = metrics.proof(req)
        assert proof.status == "unavailable" and proof.missing[0].code == "proof_quota"
    finally:
        repo.close()


async def test_causal_zero_denominator_and_missing_history_explained(metric_data, pg_settings):
    schema, store, _, request = metric_data
    causal = request("usage")
    causal.intent = "explain_cause"
    zero = request("subscription_churn")
    zero.window = MetricWindow(start=date(2025, 1, 1), end_exclusive=date(2025, 1, 2))
    report = await analyze(pg_settings, store, [causal, zero])
    assert all(o.value is None and o.verification.verdict == "unavailable" for o in report.outcomes)
    assert "causal_evidence_missing" in {m.code for m in report.outcomes[0].missing}
    assert "denominator is zero" in report.markdown
    draft = mapping_draft(schema)
    next(
        e for e in draft.entities if e.entity == "subscriptions"
    ).subscription_identity = "plan_period"
    sem = store.confirm_semantics(draft, reviewed=True)
    metric = store.confirm_metric(
        MetricDraft(
            dataset_id=schema.dataset_id,
            dataset_version=schema.version,
            semantic_version=sem.semantic_version,
            metric_id="subscription_churn",
        ),
        reviewed=True,
    )
    req = request("subscription_churn")
    req.semantic_version = sem.semantic_version
    req.metric_version = metric.metric_version
    report = await analyze(pg_settings, store, [req])
    assert report.outcomes[0].verification.verdict == "unavailable"
    assert "history_unconfirmed" in {m.code for m in report.outcomes[0].missing}


@pytest.mark.parametrize(
    "issue,code",
    [
        ("field", "field_missing"),
        ("coverage", "coverage_unconfirmed"),
        ("unit", "amount_unit_unconfirmed"),
        ("currency", "currency_unconfirmed"),
        ("date", "field_type_invalid"),
        ("grain", "grain_unconfirmed"),
    ],
)
async def test_real_incomplete_confirmed_definitions_never_get_numbers(
    metric_data, pg_settings, issue, code
):
    schema, store, _, request = metric_data
    draft = mapping_draft(schema)
    mapping = next(e for e in draft.entities if e.entity == "invoices")
    if issue == "field":
        mapping.fields.pop("amount")
    elif issue == "coverage":
        # Both ends change together through strict JSON validation.
        raw = draft.model_dump(mode="json")
        entity = next(e for e in raw["entities"] if e["entity"] == "invoices")
        entity.update(coverage_start=None, coverage_end_exclusive=None)
        draft = type(draft).model_validate_json(json.dumps(raw))
    elif issue == "unit":
        mapping.amount_storage = None
    elif issue == "currency":
        mapping.fields.pop("currency")
    elif issue == "date":
        mapping.fields["invoice_date"] = "customer_id"
    else:
        mapping.grain = ["amount_cents"]
    sem = store.confirm_semantics(draft, reviewed=True)
    metric = store.confirm_metric(
        MetricDraft(
            dataset_id=schema.dataset_id,
            dataset_version=schema.version,
            semantic_version=sem.semantic_version,
            metric_id="paid_invoice_revenue",
        ),
        reviewed=True,
    )
    req = request("paid_invoice_revenue")
    req.semantic_version, req.metric_version = sem.semantic_version, metric.metric_version
    report = await analyze(pg_settings, store, [req])
    outcome = report.outcomes[0]
    assert outcome.value is None and outcome.verification.verdict == "unavailable"
    assert code in {m.code for m in outcome.missing}
    assert store.get_evidence(outcome.evidence_id).query_sql is None
