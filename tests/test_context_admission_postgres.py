"""Real isolated PG/MCP summary admission; explicit replay decisions, never Provider calls."""

import json
from uuid import uuid4

import pytest
import sqlalchemy as sa
from langchain_core.messages import AIMessage, messages_to_dict
from test_context_benchmark import bench

from datapilot.contracts import AgentFailure
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.context import closed_batches, measure_context
from datapilot.orchestration.contracts import BudgetLimits, TaskResult
from datapilot.orchestration.coordinator import Coordinator
from datapilot.orchestration.model import Gateway
from datapilot.orchestration.runtime import Cancellation
from datapilot.runtime.mcp_client import database_session

pytestmark = pytest.mark.integration


class ReplayDecisions:
    def __init__(self):
        self.requests = []

    async def respond(self, messages, tools):
        self.requests.append(list(messages))
        if messages[0].content.startswith("CONTEXT_SUMMARY_JSON"):
            assert not tools and set(json.loads(messages[-1].content)) == {"decision_ids"}
            content = {"decisions": []}
        else:
            ref = json.loads(messages[-1].content)["artifact_refs"][0]["artifact_id"]
            content = {"artifact_ids": [ref]}
        return AIMessage(
            content=json.dumps(content),
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


def test_isolated_context_admission_roles_have_no_business_write_privilege(portable_pg):
    # Infrastructure role inspection only. Business results below use the real MCP client.
    for url in [portable_pg.reader_database_url, portable_pg.rag_reader_database_url]:
        engine = sa.create_engine(
            url.get_secret_value(),
            hide_parameters=True,
            connect_args={"connect_timeout": 5},
        )
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
                assert (
                    connection.exec_driver_sql("SELECT current_database()")
                    .scalar_one()
                    .startswith("datapilot_test_")
                )
                flags = connection.exec_driver_sql(
                    "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls "
                    "FROM pg_roles WHERE rolname=current_user"
                ).one()
                assert not any(flags)
                assert not connection.exec_driver_sql(
                    "SELECT has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE') "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='saas' AND c.relname='customers'"
                ).scalar_one()
        finally:
            engine.dispose()


@pytest.mark.parametrize("admitted", [True, False])
async def test_real_pg_mcp_l4_summary_preserves_refs_and_budget(portable_pg, admitted):
    settings = portable_pg.model_copy(
        update={"max_total_tokens": 18000, "max_model_calls": 8, "max_worker_turns": 4}
    )
    async with database_session(settings) as database:
        run_id = "new-context-dev-" + uuid4().hex[:16]
        source = await bench.snapshot(
            database, run_id, "context_dev", 4, 1800, budget=BudgetLimits(calls=4, tokens=18000)
        )
        original = messages_to_dict(source.messages)
        golden = await database.execute("SELECT COUNT(*) AS customer_count FROM customers")
        with pytest.raises(AgentFailure) as denied:
            await database.execute("DELETE FROM customers")
        assert denied.value.error.code == "SQL_UNSAFE"
        chars, _ = await bench.calibrate(source, settings, "L4")
        settings = settings.model_copy(update={"max_input_chars": chars})
        registry = bench.clone_registry(source)
        manager = bench.context(source, settings, registry)
        limits = BudgetLimits(calls=8, tokens=18000 if admitted else 200)
        ledger = BudgetLedger(limits)
        ledger.fork("worker", BudgetLimits(calls=4, tokens=limits.tokens))
        transport = ReplayDecisions()
        gateway = Gateway(transport, settings, ledger, Cancellation())
        gateway.contexts["worker"] = manager
        if not admitted:
            before = ledger.dump_state()
            with pytest.raises(AgentFailure) as caught:
                await gateway.invoke(source.messages, registry.schemas(), "worker")
            assert caught.value.error.code == "BUDGET_EXCEEDED"
            assert ledger.dump_state() == before and not transport.requests
            assert all(stat.summary_calls == 0 for stat in manager.stats)
            return

        response = await gateway.invoke(source.messages, registry.schemas(), "worker")
        assert json.loads(response.content)["artifact_ids"] == [source.expected_ref]
        assert len(transport.requests) == 2 and manager.stats[-1].levels[-1] == "L4"
        assert manager.stats[-1].summary_calls == 1
        assert ledger.snapshot().calls == 2 and ledger.snapshot().reported_tokens == 30
        assert ledger.snapshot() == ledger.snapshot("worker") and not ledger.pending
        usage = measure_context(transport.requests[-1], registry.schemas(), 1200)[1]
        assert usage.estimated_input_tokens + usage.output_reserved_tokens <= 18000
        assert closed_batches(transport.requests[-1])
        assert messages_to_dict(source.messages) == original
        refs = [ref for ref in registry.refs if ref.artifact_id == source.expected_ref]
        artifact = registry.store.get(refs[0])
        assert artifact.query.rows == golden.rows and not artifact.query.truncated
        for archive in (ref for ref in registry.context_refs if ref.kind == "context"):
            assert json.loads(manager.read_archive(archive)) == original
        result = TaskResult(
            run_id=run_id,
            task_id=source.envelope.task.task_id,
            plan_version=1,
            worker="sql",
            status="succeeded",
            evidence_refs=refs,
            usage=ledger.snapshot("worker"),
            attempts=registry.sql_attempts,
        )
        verifier = Coordinator(settings, transport, database=database, run_id=run_id)
        verifier.store = registry.store
        verdict = verifier.verify(
            {"run_id": run_id, "plan_version": 1, "results": {}, "verifications": {}},
            source.envelope.task,
            result,
        )
        assert verdict.status == "passed"
