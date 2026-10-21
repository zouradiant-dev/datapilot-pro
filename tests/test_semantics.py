"""Local deterministic contract, recipe, arithmetic and adversarial verifier tests (no PG)."""

import copy
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from datapilot.agents.sql import SQLAgent
from datapilot.contracts import AgentFailure, QueryResult, SQLProposal
from datapilot.data.semantic_demo import demo_tables, mapping_draft, write_demo
from datapilot.datasets.contracts import (
    DatasetColumn,
    DatasetQueryResult,
    DatasetSchema,
    DatasetTable,
)
from datapilot.harness.metric_verification import equal_value, make_evidence, verify_execution
from datapilot.ingestion.common import digest
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.semantics.contracts import (
    LAYERS,
    LayerCheck,
    MetricDraft,
    MetricExecution,
    MetricProof,
    MetricRequest,
    MetricVersion,
    MetricWindow,
    ReportClaim,
    SemanticVersion,
    VerificationRecord,
)
from datapilot.semantics.recipes import (
    build_context,
    compile_sql,
    metric_value,
    request_missing,
    scalar,
    semantics_match,
)
from datapilot.semantics.recompute import compute_rows
from datapilot.semantics.service import validate_claims

SOURCE = Path(__file__).parent / "fixtures/semantics/saas_metrics.xlsx"
DATASET = "c98ff08b-0111-4d8d-8491-693cf639d5cf"


@pytest.fixture
def semantic_case():
    data = parse_file(SOURCE, options=ParseOptions(header="present"))
    confirmed = confirm_schema(data, propose_schema(data), reviewed=True)
    tables = []
    rows = list(demo_tables().items())
    for index, table in enumerate(confirmed.tables):
        name, values = rows[index]
        tables.append(
            DatasetTable(
                table_id=table.table_id,
                source_name=name,
                physical_name="test_" + name,
                row_count=len(values) - 1,
                primary_key=[],
                columns=[
                    DatasetColumn(
                        position=i,
                        source_column=c.source_column,
                        original_name=c.original_name,
                        normalized_name=c.normalized_name,
                        logical_type=c.logical_type,
                        sql_type=c.logical_type,
                    )
                    for i, c in enumerate(table.columns, 1)
                ],
            )
        )
    schema = DatasetSchema(
        dataset_id=DATASET,
        name="synthetic",
        version=1,
        source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        row_count=20,
        tables=tables,
    )
    draft = mapping_draft(schema)
    semantic = SemanticVersion(
        dataset_id=DATASET,
        dataset_version=1,
        semantic_version=1,
        source_sha256=schema.source_sha256,
        definition_sha256=digest(draft),
        definition=draft,
    )

    def case(kind="paid_invoice_revenue", *, feature=None):
        definition = MetricDraft(
            dataset_id=DATASET,
            dataset_version=1,
            semantic_version=1,
            metric_id=kind,
            feature=feature,
        )
        metric = MetricVersion(
            dataset_id=DATASET,
            dataset_version=1,
            metric_id=kind,
            metric_version=1,
            semantic_version=1,
            semantic_sha256=semantic.definition_sha256,
            definition_sha256=digest(definition),
            definition=definition,
        )
        request = MetricRequest(
            goal_id=kind,
            dataset_id=DATASET,
            dataset_version=1,
            semantic_version=1,
            metric_id=kind,
            metric_version=1,
            **(
                {"as_of": date(2025, 10, 31)}
                if kind == "active_subscriptions"
                else {
                    "window": MetricWindow(start=date(2025, 10, 1), end_exclusive=date(2025, 11, 1))
                }
            ),
        )
        return build_context(schema, semantic, metric), request

    return case


def raw_rows(context):
    values = demo_tables()[context.entity.entity]
    return [
        {role: row[values[0].index(column)] for role, column in context.entity.fields.items()}
        for row in values[1:]
    ]


def execution_case(context, request):
    sql = compile_sql(context, request)
    expected = compute_rows(context, request, raw_rows(context))
    result = QueryResult(
        columns=["numerator", "denominator"] if expected.denominator else ["value"],
        rows=[[expected.numerator, expected.denominator]]
        if expected.denominator
        else [[expected.value]],
        row_count=1,
        truncated=False,
        elapsed_ms=0,
    )
    primary = DatasetQueryResult(
        dataset_id=context.dataset_id,
        version=context.dataset_version,
        source_sha256=context.source_sha256,
        query_sha256=hashlib.sha256(sql.encode()).hexdigest(),
        result_sha256=digest(result.model_dump(mode="json", exclude={"elapsed_ms"})),
        result=result,
    )
    proof = MetricProof(
        context_sha256=context.context_sha256,
        request_sha256=digest(request),
        status="computed",
        value=expected,
        source_rows=context.table.row_count,
        page_hashes=["1" * 64],
    )
    return MetricExecution(
        request=request, context=context, candidate_sql=sql, primary=primary, proof=proof
    )


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("paid_invoice_revenue", "300"),
        ("usage", "35"),
        ("active_subscriptions", "4"),
        ("customer_churn", "0.400000000000"),
        ("subscription_churn", "0.666666666667"),
    ],
)
def test_five_independent_golds_and_six_layers(semantic_case, kind, expected):
    context, request = semantic_case(kind)
    assert not context.missing
    execution = execution_case(context, request)
    assert Decimal(execution.proof.value.value) == Decimal(expected)
    assert semantics_match(execution.candidate_sql, context, request)
    evidence = make_evidence(execution)
    verification = verify_execution(execution, evidence, evidence)
    assert verification.verdict == "verified"
    assert tuple(c.layer for c in verification.checks) == LAYERS
    assert all(c.status == "passed" for c in verification.checks)


@pytest.mark.parametrize("mutation", ["paid_filter", "join", "right_boundary", "unit"])
def test_sql_semantic_mutations_rejected(semantic_case, mutation):
    context, request = semantic_case()
    sql = compile_sql(context, request)
    if mutation == "paid_filter":
        sql = sql.replace("'paid'", "'unpaid'")
    elif mutation == "right_boundary":
        sql = sql.replace(" < CAST(", " <= CAST(")
    elif mutation == "unit":
        sql = sql.replace(" / 100", " / 1")
    else:
        sql = sql.replace(
            " AS s", f' AS s JOIN uploads."{context.table.physical_name}" t ON TRUE', 1
        )
    assert sql != compile_sql(context, request)
    assert not semantics_match(sql, context, request)


@pytest.mark.parametrize(
    "kind",
    [
        "paid_invoice_revenue",
        "usage",
        "customer_churn",
        "subscription_churn",
        "active_subscriptions",
    ],
)
def test_context_projects_only_necessary_columns(semantic_case, kind):
    context, _ = semantic_case(kind)
    names = {c.normalized_name for c in context.table.columns}
    assert names == set(context.entity.fields.values())
    if kind == "paid_invoice_revenue":
        assert "customer_id" not in names and '"subscription_id"' not in context.model_dump_json()


def test_mrr_and_causal_questions_are_explicitly_unavailable(semantic_case):
    context, request = semantic_case("mrr")
    assert "mrr_definition_missing" in {m.code for m in context.missing}
    with pytest.raises(AgentFailure):
        compile_sql(context, request)
    context, request = semantic_case()
    request.intent = "explain_cause"
    problems = request_missing(context, request)
    execution = MetricExecution(context=context, request=request, missing=problems)
    evidence = make_evidence(execution)
    assert verify_execution(execution, evidence, evidence).verdict == "unavailable"
    assert evidence.value is None and problems[0].code == "causal_evidence_missing"


@pytest.mark.parametrize(
    "issue", ["history", "coverage", "amount_unit", "date_type", "missing_field"]
)
def test_unconfirmed_or_insufficient_mapping_does_not_guess(semantic_case, issue):
    context, request = semantic_case(
        "subscription_churn" if issue == "history" else "paid_invoice_revenue"
    )
    # Exercise the real context builder from modified confirmed definition data.
    from datapilot.semantics.recipes import BLUEPRINTS

    assert BLUEPRINTS[request.metric_id]
    if issue == "coverage":
        request.window.start = date(2024, 1, 1)
        assert request_missing(context, request)[0].code == "outside_coverage"
        return
    # A context tamper cannot bypass the versioned context digest verifier.
    if issue == "history":
        context.entity.history_complete = False
    elif issue == "amount_unit":
        context.entity.amount_storage = "major"
    elif issue == "date_type":
        context.table.columns[0].logical_type = "TEXT"
    else:
        context.entity.fields.pop("amount")
    execution = MetricExecution(context=context, request=request, missing=[])
    evidence = make_evidence(execution)
    assert verify_execution(execution, evidence, evidence).verdict == "rejected"


@pytest.mark.parametrize("issue", ["duplicate", "null", "negative", "fractional", "bad_date"])
def test_raw_data_quality_is_mandatory(semantic_case, issue):
    context, request = semantic_case("usage")
    rows = raw_rows(context)
    if issue == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif issue == "null":
        rows[0]["event_count"] = None
    elif issue == "negative":
        rows[0]["event_count"] = -1
    elif issue == "fractional":
        rows[0]["event_count"] = "1.5"
    else:
        rows[0]["event_date"] = "10/01/2025"
    with pytest.raises(ValueError):
        compute_rows(context, request, rows)


def test_zero_cohort_not_zero_percent_and_feature_filter(semantic_case):
    context, request = semantic_case("subscription_churn")
    with pytest.raises(ValueError, match="denominator is zero"):
        compute_rows(context, request, [])
    context, request = semantic_case("usage", feature="dashboard")
    assert compute_rows(context, request, raw_rows(context)).value == "30"


@pytest.mark.parametrize(
    "issue",
    ["number", "unit", "truncated", "query_hash", "result_hash", "proof_version", "evidence_id"],
)
def test_tampered_tools_and_references_rejected(semantic_case, issue):
    context, request = semantic_case()
    execution = execution_case(context, request)
    if issue == "number":
        execution.proof.value.value = "30000"
    elif issue == "unit":
        execution.proof.value.unit = "USD"
    elif issue == "truncated":
        execution.primary.result.truncated = True
    elif issue == "query_hash":
        execution.primary.query_sha256 = "0" * 64
    elif issue == "result_hash":
        execution.primary.result_sha256 = "0" * 64
    elif issue == "proof_version":
        execution.proof.context_sha256 = "0" * 64
    evidence = make_evidence(execution)
    referenced = evidence.model_copy(deep=True)
    if issue == "evidence_id":
        referenced.evidence_id = str(uuid4())
    assert verify_execution(execution, evidence, referenced).verdict == "rejected"


@pytest.mark.parametrize(
    "issue",
    ["causal", "missing_goal", "invented_id", "wrong_value", "wrong_goal", "invented_verification"],
)
def test_report_causality_coverage_and_reference_checks(semantic_case, issue):
    context, request = semantic_case()
    execution = execution_case(context, request)
    evidence = make_evidence(execution)
    verification = verify_execution(execution, evidence, evidence)
    claim = ReportClaim(
        goal_id=request.goal_id,
        kind="metric",
        evidence_id=evidence.evidence_id,
        verification_id=verification.verification_id,
        value=evidence.value.model_copy(deep=True),
    )
    claims = [claim]
    if issue == "causal":
        claim.kind = "causal"
    elif issue == "missing_goal":
        claims = []
    elif issue == "invented_id":
        claim.evidence_id = str(uuid4())
    elif issue == "wrong_value":
        claim.value.value = "30000"
    elif issue == "invented_verification":
        claim.verification_id = str(uuid4())
    else:
        claim.goal_id = "other"

    def lookup(key):
        if key != evidence.evidence_id:
            raise AgentFailure("REFERENCE_NOT_FOUND", "No such evidence")
        return evidence

    with pytest.raises(AgentFailure):
        validate_claims([request], claims, lookup, lambda key: verification)


def test_dto_bounds_confirmation_and_derived_verdict(semantic_case):
    context, request = semantic_case()
    with pytest.raises(ValidationError):
        MetricRequest.model_validate_json(
            request.model_dump_json().replace('"metric_version":1', '"metric_version":0')
        )
    with pytest.raises(ValidationError):
        VerificationRecord(
            verification_id=str(uuid4()),
            evidence_id=str(uuid4()),
            dataset_id=DATASET,
            dataset_version=1,
            request_sha256=digest(request),
            verdict="verified",
            checks=[LayerCheck(layer=layer, status="failed") for layer in LAYERS],
        )
    assert equal_value(
        metric_value(context, request, execution_case(context, request).primary.result),
        compute_rows(context, request, raw_rows(context)),
    )


async def test_worker_uses_minimal_context_and_rejects_model_join(semantic_case):
    context, request = semantic_case()

    class Tools:
        async def context(self, request):
            return context

        async def execute(self, *args):
            pytest.fail("Rejected SQL must never reach the database")

    class Model:
        def generate(self, schema, *, system, user):
            assert "CONFIRMED CONTEXT" in user and "customer_id" not in user
            return SQLProposal(sql="SELECT COUNT(*) FROM uploads.other_dataset")

    result = await SQLAgent(Model(), Tools()).run_metric(request)
    assert result.primary is None and result.missing


def test_committed_synthetic_fixtures_reproducible(tmp_path):
    write_demo(tmp_path)
    for path in SOURCE.parent.iterdir():
        assert path.read_bytes() == (tmp_path / path.name).read_bytes()
    assert json.loads(json.dumps(demo_tables()))["invoices"][1][2] == 10000


@pytest.mark.parametrize("value", [True, 1.1, "1e999999999", "NaN", "1" * 81, "-Infinity"])
def test_untrusted_numeric_payloads_are_bounded(value):
    with pytest.raises(ValueError):
        scalar(value)


def test_subscription_nonchurn_and_unknown_termination_policies(semantic_case):
    context, request = semantic_case("subscription_churn")
    rows = raw_rows(context)
    rows[0]["termination_kind"] = "downgraded"
    assert compute_rows(context, request, rows).numerator == 3
    rows = raw_rows(context)
    rows[0]["termination_kind"] = "not_confirmed"
    with pytest.raises(ValueError, match="unclassified"):
        compute_rows(context, request, rows)


def test_empty_complete_sources_return_zero_but_churn_has_no_denominator(semantic_case):
    for kind in ("paid_invoice_revenue", "usage", "active_subscriptions"):
        context, request = semantic_case(kind)
        assert compute_rows(context, request, []).value == "0"
