"""New public synthetic rows; repository I/O doubles, real P3/report contracts, no PG/API."""

import copy
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from test_semantics import semantic_case as semantic_case

from datapilot.contracts import AgentFailure, QueryResult
from datapilot.datasets.contracts import DatasetBinding, DatasetQueryResult, DatasetScope
from datapilot.harness.metric_verification import make_evidence, verify_execution
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact
from datapilot.orchestration.runtime import ArtifactStore
from datapilot.reporting.contracts import MetricBridge, ReportScope
from datapilot.reporting.service import ReportService
from datapilot.semantics.contracts import MetricExecution, MetricProof
from datapilot.semantics.recipes import compile_sql
from datapilot.semantics.repository import MetricRepository


def repository_case(semantic_case, kind, issue):
    context, request = semantic_case(kind)
    values = {
        "record_id": "phase1-public-001",
        "customer_id": "phase1-customer",
        "amount": "1000",
        "invoice_date": "2025-10-05",
        "payment_status": "paid",
        "currency": "CNY",
        "event_date": "2025-10-05",
        "event_count": "2",
        "feature": "dashboard",
        "start_date": "2025-10-05",
        "end_date": None,
        "termination_kind": "cancelled",
    }
    row = {role: values[role] for role in context.entity.fields}
    rows = [] if issue == "zero" else [row, copy.deepcopy(row)] if issue == "duplicate" else [row]
    if issue == "null_id":
        rows[0]["record_id"] = None
    context = context.model_copy(deep=True)
    context.table.row_count = len(rows)
    context.source_sha256 = digest(rows)
    context.context_sha256 = digest(context.model_dump(mode="json", exclude={"context_sha256"}))
    page = QueryResult(
        columns=list(context.entity.fields),
        rows=[[r[role] for role in context.entity.fields] for r in rows],
        row_count=len(rows),
        elapsed_ms=0,
        truncated=False,
    )
    sql = SimpleNamespace(
        max_rows=100,
        engine=MagicMock(),
        _configure=MagicMock(),
        read_page=MagicMock(return_value=page),
    )
    repository = MetricRepository(SimpleNamespace(sql=sql))
    repository.context = lambda _: context
    return repository, context, request


def assert_unavailable_chain(settings, context, request, proof, expected):
    assert proof.status == "unavailable" and proof.value is None
    assert [m.code for m in proof.missing] == [expected]
    # Existing DTO serialization must retain the exact typed reason.
    assert MetricProof.model_validate_json(proof.model_dump_json()) == proof
    sql = compile_sql(context, request)
    churn = request.metric_id in {"subscription_churn", "customer_churn"}
    primary = QueryResult(
        columns=["numerator", "denominator"] if churn else ["value"],
        rows=[["0", "0"]] if churn else [["20"]],
        row_count=1,
        elapsed_ms=0,
        truncated=False,
    )
    execution = MetricExecution(
        context=context,
        request=request,
        candidate_sql=sql,
        proof=proof,
        primary=DatasetQueryResult(
            dataset_id=context.dataset_id,
            version=context.dataset_version,
            source_sha256=context.source_sha256,
            query_sha256=hashlib.sha256(sql.encode()).hexdigest(),
            result_sha256=digest(primary.model_dump(mode="json", exclude={"elapsed_ms"})),
            result=primary,
        ),
    )
    evidence = make_evidence(execution)
    assert [m.code for m in evidence.missing] == [expected]
    verification = verify_execution(execution, evidence, evidence)
    assert verification.verdict == "unavailable"
    # Six-layer policy stays unchanged; detailed business reasons travel via Evidence.
    check = next(c for c in verification.checks if c.layer == "recomputation")
    assert (check.status, check.codes) == ("not_applicable", ["data_not_verifiable"])
    scope = ReportScope(
        question="查看公开合成样例的指标及无法计算原因",
        datasets=DatasetScope(
            bindings=[
                DatasetBinding(
                    dataset_id=request.dataset_id,
                    version=request.dataset_version,
                )
            ]
        ),
        metrics=[request],
    )
    service = ReportService(
        settings,
        scope,
        {},
        {request.goal_id: context},
        {
            request.dataset_id: {"source_sha256": context.source_sha256, "version": 1},
        },
        {},
    )
    service.proofs[evidence.evidence_id] = (evidence, verification)  # Explicit metadata double.
    bridge = MetricBridge(
        request=request,
        source_sha256=context.source_sha256,
        context=context,
        evidence_id=evidence.evidence_id,
        evidence_sha256=digest(evidence),
        query_sha256=evidence.query_sha256,
        result_sha256=evidence.result_sha256,
        verification=verification,
        verification_sha256=digest(verification),
        verdict=verification.verdict,
        value=None,
        missing=evidence.missing,
        verified_at=datetime.now(UTC),
    )
    store = ArtifactStore("public-reason-test")
    ref = store.put(
        Artifact(
            run_id="public-reason-test",
            task_id=request.goal_id,
            plan_version=1,
            kind="metric",
            source="unit-proof",
            metric=bridge,
        )
    )
    report = service.build([(ref, store.get(ref))], None)
    assert report.business_completion.status == "unavailable" and not report.charts
    assert report.claims[0].kind == "unavailable" and report.claims[0].metric is None
    assert report.claims[0].codes == [expected]
    assert report.claims[0].missing_requirements == proof.missing
    assert report.business_completion.missing_evidence == {request.goal_id: [expected]}


@pytest.mark.parametrize("kind", ["subscription_churn", "customer_churn"])
def test_zero_denominator_propagates_to_report(semantic_case, settings, kind):
    repository, context, request = repository_case(semantic_case, kind, "zero")
    assert_unavailable_chain(
        settings, context, request, repository.proof(request), "zero_denominator"
    )


@pytest.mark.parametrize("kind", ["paid_invoice_revenue", "usage"])
def test_duplicate_grain_propagates_to_report(semantic_case, settings, kind):
    repository, context, request = repository_case(semantic_case, kind, "duplicate")
    assert_unavailable_chain(
        settings, context, request, repository.proof(request), "duplicate_record_grain"
    )


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("zero_denominator duplicate_record_grain"),
        ArithmeticError("unknown arithmetic"),
    ],
)
def test_unknown_errors_do_not_infer_business_codes(semantic_case, settings, monkeypatch, failure):
    repository, context, request = repository_case(semantic_case, "paid_invoice_revenue", "normal")

    def fail(*_):
        raise failure

    monkeypatch.setattr("datapilot.semantics.repository.compute_rows", fail)
    assert_unavailable_chain(
        settings, context, request, repository.proof(request), "data_not_verifiable"
    )


def test_null_identity_keeps_generic_rejection(semantic_case, settings):
    repository, context, request = repository_case(semantic_case, "usage", "null_id")
    assert_unavailable_chain(
        settings, context, request, repository.proof(request), "data_not_verifiable"
    )


def test_unknown_agent_failure_keeps_query_failure_code(semantic_case, monkeypatch):
    repository, _, request = repository_case(semantic_case, "usage", "normal")

    def fail(*_):
        raise AgentFailure("zero_denominator", "unrelated agent failure")

    monkeypatch.setattr("datapilot.semantics.repository.compute_rows", fail)
    proof = repository.proof(request)
    assert proof.status == "unavailable" and proof.value is None
    assert [m.code for m in proof.missing] == ["proof_query_failed"]


def test_unhandled_programming_failure_cannot_return_verified_proof(semantic_case, monkeypatch):
    repository, _, request = repository_case(semantic_case, "usage", "normal")

    def fail(*_):
        raise RuntimeError("programming failure")

    monkeypatch.setattr("datapilot.semantics.repository.compute_rows", fail)
    with pytest.raises(RuntimeError, match="programming failure"):
        repository.proof(request)


def test_normal_computation_remains_unchanged(semantic_case):
    repository, _, request = repository_case(semantic_case, "usage", "normal")
    proof = repository.proof(request)
    assert proof.status == "computed" and not proof.missing and proof.value.value == "2"
