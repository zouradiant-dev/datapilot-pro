"""Targeted real PG/MCP/Journal acceptance; public data and existing scripted decisions only."""

from datetime import date
from uuid import uuid4

import pytest
from openpyxl import load_workbook
from test_cross_source_postgres import (
    ReportDecisions,
    proof_snapshot,
    scope_for,
)
from test_cross_source_postgres import (
    report_data as report_data,
)
from test_rag_postgres import embedding as embedding
from test_semantic_integration import SOURCE, scope
from test_semantic_integration import metric_data as metric_data

from datapilot.data.semantic_demo import mapping_draft
from datapilot.datasets.contracts import ImportRequest
from datapilot.datasets.repository import DatasetRepository
from datapilot.db.management import management_url
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService
from datapilot.persistence.backend import Backend, DurableArtifacts
from datapilot.persistence.inspection import inspect_run
from datapilot.persistence.session import run_async, run_durable
from datapilot.reporting.contracts import ReportScope
from datapilot.runtime.mcp_client import metric_session
from datapilot.semantics.contracts import MetricDraft, MetricRequest, MetricWindow
from datapilot.semantics.registry import RegistryStore

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("reason", ["zero_denominator", "duplicate_record_grain"])
def test_persisted_refusal_reason_crosses_real_mcp_and_report(
    pg_settings, metric_data, tmp_path, reason
):
    schema, _, _, request = metric_data
    if reason == "zero_denominator":
        req = request("subscription_churn")
        req.window = MetricWindow(start=date(2025, 1, 1), end_exclusive=date(2025, 1, 2))
    else:
        # New public derivative Dataset, never change the fixture or any existing table.
        path = tmp_path / "phase12-duplicates.xlsx"
        workbook = load_workbook(SOURCE)
        sheet = workbook["invoices"]
        sheet.append([c.value for c in sheet[2]])
        workbook.save(path)
        workbook.close()
        parsed = parse_file(path, options=ParseOptions(header="present"))
        confirmation = confirm_schema(parsed, propose_schema(parsed), reviewed=True)
        ingest = IngestionService(management_url("ingest"), storage_dir=tmp_path / "sources")
        try:
            imported = ingest.import_file(
                path, confirmation, ImportRequest(name="phase12-duplicate-" + uuid4().hex[:10])
            )
        finally:
            ingest.close()
        reader = DatasetRepository(
            pg_settings.upload_reader_database_url.get_secret_value(), scope(imported)
        )
        registry = RegistryStore(management_url("registry"))
        try:
            schema = reader.schema(imported.dataset_id)
            semantic = registry.confirm_semantics(mapping_draft(schema), reviewed=True)
            metric = registry.confirm_metric(
                MetricDraft(
                    dataset_id=schema.dataset_id,
                    dataset_version=schema.version,
                    semantic_version=semantic.semantic_version,
                    metric_id="paid_invoice_revenue",
                ),
                reviewed=True,
            )
            req = MetricRequest(
                goal_id="public_duplicate_revenue",
                dataset_id=schema.dataset_id,
                dataset_version=schema.version,
                semantic_version=semantic.semantic_version,
                metric_id=metric.metric_id,
                metric_version=metric.metric_version,
                window=MetricWindow(start=date(2025, 10, 1), end_exclusive=date(2025, 11, 1)),
            )
        finally:
            reader.close()
            registry.close()
    question = "核对公开合成数据中的业务指标，无法计算时保留准确原因。"
    rs = ReportScope(
        question=question, datasets=scope(schema), metrics=[req], causal_requested=False
    )
    run_id = str(uuid4())
    result = run_async(
        run_durable(pg_settings, run_id, question, report_scope=rs, transport=ReportDecisions(""))
    )
    report = result["cross_source_report"]
    assert report.business_completion.status == "unavailable" and not report.charts
    assert report.claims[0].codes == [reason] and report.claims[0].metric is None
    backend = Backend(pg_settings.runtime_database_url.get_secret_value(), run_id, rs.owner)
    try:
        bridges = [a.metric for a in DurableArtifacts(backend).export().values() if a.metric]
    finally:
        backend.close()
    assert len(bridges) == 1
    bridge = bridges[0]

    async def read_back():
        async with metric_session(pg_settings, rs.datasets) as tools:
            evidence = await tools.evidence(req.dataset_id, bridge.evidence_id)
            verification = await tools.verification(
                req.dataset_id, bridge.verification.verification_id
            )
        assert evidence.proof.status == "unavailable"
        assert [m.code for m in evidence.proof.missing] == [reason]
        assert [m.code for m in evidence.missing] == [reason]
        assert verification.verdict == bridge.verdict == "unavailable"
        check = next(c for c in verification.checks if c.layer == "recomputation")
        assert (check.status, check.codes) == ("not_applicable", ["data_not_verifiable"])

    run_async(read_back())


def test_explicit_false_report_survives_real_sources_and_readonly_inspection(
    pg_settings, report_data
):
    query = "已付款账单收入的业务口径"
    question = "核对账单收入及文档事实，不宣称资料证明了收入改善的因果关系。"
    rs = scope_for(report_data, "paid_invoice_revenue", question, query, unique=True)
    rs.causal_requested = False
    run_id = str(uuid4())
    result = run_async(
        run_durable(
            pg_settings,
            run_id,
            question,
            report_scope=rs,
            rag_scope=report_data[3],
            transport=ReportDecisions(query),
        )
    )
    report = result["cross_source_report"]
    assert report.business_completion.status == "completed"
    assert not report.business_completion.unconfirmed_claims
    assert any(c.kind == "context" and c.documents for c in report.claims)
    before = proof_snapshot(report_data[1], rs.metrics[0].goal_id)
    inspected = run_async(
        inspect_run(
            pg_settings, run_id, rs.owner, question, report_scope=rs, rag_scope=report_data[3]
        )
    )
    assert inspected["report"] == report and inspected["usage"] == result["usage"]
    assert before == proof_snapshot(report_data[1], rs.metrics[0].goal_id)
