"""Real PG/MCP checks of trusted P3 definitions; synthetic uploaded source only."""

import copy
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_semantic_integration import metric_data as metric_data

from datapilot.contracts import AgentFailure
from datapilot.db.management import management_url
from datapilot.ingestion.common import digest
from datapilot.orchestration.context_contracts import ContextScope, MetricBinding, SourcePin
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.persistence.backend import Backend, DurableLedger, execute, json_value
from datapilot.persistence.journal import Journal
from datapilot.persistence.session import check_versions, run_async, run_durable
from datapilot.semantics.repository import MetricRepository

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("change", ["source", "metric", "scope", "capability"])
def test_fresh_dataset_metric_and_authority_are_checked_before_resume(
    pg_settings, metric_data, change
):
    schema, _, repository, request = metric_data
    req = request("paid_invoice_revenue")
    context = MetricRepository(repository).context(req)
    metadata = {
        "sql": {
            "scope": ContextScope(
                profile="dataset",
                sources=(
                    SourcePin(
                        dataset_id=schema.dataset_id,
                        version=schema.version,
                        source_sha256=schema.source_sha256,
                    ),
                ),
            ).model_dump(mode="json"),
            "metrics": [MetricBinding(request=req, context=context).model_dump(mode="json")],
        }
    }
    id_ = str(uuid4())
    paused = run_async(
        run_durable(
            pg_settings, id_, "查询客户总数", context_metadata=metadata, interrupt_after=["planner"]
        )
    )
    assert paused["status"] == "paused" and paused["usage"]["calls"] == 0
    changed = copy.deepcopy(metadata)
    if change == "source":
        changed["sql"]["scope"]["sources"][0]["source_sha256"] = "0" * 64
    elif change == "metric":
        ctx = changed["sql"]["metrics"][0]["context"]
        ctx["metric_sha256"] = "0" * 64
        ctx["context_sha256"] = digest({k: v for k, v in ctx.items() if k != "context_sha256"})
    elif change == "scope":
        changed["sql"]["scope"]["owner"] = "not-delegated"
    else:
        changed["sql"]["allowed_tools"] = ["arbitrary_shell"]
    with pytest.raises(AgentFailure) as rejected:
        run_async(run_durable(pg_settings, id_, resume=True, context_metadata=changed))
    assert rejected.value.error.code in {"RECOVERY_VERSION", "RECOVERY_FORBIDDEN"}
    # An unchanged, freshly queried definition remains valid. No model API is used here.
    run_async(check_versions(pg_settings, metadata))


def test_hash_valid_but_inconsistent_child_budget_is_not_trusted(pg_settings):
    id_ = str(uuid4())
    limits = BudgetLimits(calls=4, tokens=5000)
    b = Backend(pg_settings.runtime_database_url.get_secret_value(), id_, "local-user")
    admin = sa.create_engine(management_url("owner"), hide_parameters=True)
    try:
        b.register({"test": "budget-consistency"}, limits)
        ledger = DurableLedger(b, limits)
        ledger.fork("1:sql", limits)
        # Only the isolated test run is altered, never business data or existing executions.
        with admin.begin() as conn:
            payload = execute(
                conn, "SELECT payload FROM execution.ledger WHERE run_id=:run", run=id_
            ).scalar_one()
            payload["state"]["accounts"]["1:sql"]["usage"]["calls"] = 1
            payload["sha256"] = digest(payload["state"])
            execute(
                conn,
                "UPDATE execution.ledger SET payload=CAST(:p AS jsonb) WHERE run_id=:run",
                p=json_value(payload),
                run=id_,
            )
        with pytest.raises(AgentFailure, match="ledger"):
            Journal(b, ledger, None).recover()
    finally:
        admin.dispose()
        b.close()


def test_unknown_settlement_does_not_create_a_receipt(pg_settings):
    id_ = str(uuid4())
    b = Backend(pg_settings.runtime_database_url.get_secret_value(), id_, "local-user")
    try:
        limits = BudgetLimits()
        b.register({"test": "unknown-settlement"}, limits)
        ledger = DurableLedger(b, limits)
        with pytest.raises(AgentFailure):
            ledger.settle("never-reserved", 0)
        assert "never-reserved" not in ledger.receipts and ledger.snapshot().calls == 0
    finally:
        b.close()
