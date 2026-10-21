"""Real PG and real separate Python processes. Model decisions explicitly Fake, not live."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from langchain_core.messages import AIMessage, HumanMessage

from datapilot.contracts import AgentFailure
from datapilot.db.management import management_url
from datapilot.orchestration.contracts import Artifact, BudgetLimits
from datapilot.persistence.backend import (
    Backend,
    DurableArtifacts,
    DurableLedger,
    execute,
)
from datapilot.persistence.journal import Journal
from datapilot.persistence.session import run_async, run_durable

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]


def probe(action, id_, *options, expected=0):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/recovery_probe.py"), action, id_, *options],
        cwd=ROOT,
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )
    assert result.returncode == expected, result.stdout[-2000:] + result.stderr[-1500:]
    return json.loads(result.stdout) if result.stdout.strip() else None


def backend(settings, id_):
    return Backend(settings.runtime_database_url.get_secret_value(), id_, "local-user")


@pytest.fixture
def durable_settings(pg_settings):
    if not pg_settings.runtime_database_url:
        pytest.fail("P5B real PG tests require runtime identity and explicit runtime-init")
    return pg_settings


def test_real_cross_process_pause_restore_and_repeated_resume(durable_settings):
    id_ = str(uuid4())
    paused = probe("start", id_, "--pause-after", "worker")
    assert paused["status"] == "paused" and paused["usage"]["calls"] == 2
    complete = probe("resume", id_)
    again = probe("resume", id_)
    assert complete["status"] == "succeeded" and complete["completion"]["status"] == "completed"
    assert complete["result"]["result"]["rows"] == [[240]]
    assert complete["results"] == paused["results"]
    assert complete["usage"] == paused["usage"] == again["usage"]
    assert again["results"] == complete["results"]


@pytest.mark.parametrize(
    "cut,occurrence", [("model_committed", 1), ("model_committed", 2), ("tool_committed", 2)]
)
def test_committed_call_before_checkpoint_is_reused_without_duplicate_charge(
    durable_settings, cut, occurrence
):
    id_ = str(uuid4())
    probe("start", id_, "--cut", cut, "--occurrence", str(occurrence), expected=91)
    complete = probe("resume", id_)
    assert complete["status"] == "succeeded" and complete["usage"]["calls"] == 2
    assert complete["result"]["result"]["rows"] == [[240]]
    b = backend(durable_settings, id_)
    try:
        with b.transaction() as conn:
            rows = execute(
                conn, "SELECT kind,status FROM execution.calls WHERE run_id=:run", run=id_
            ).all()
        assert sum(kind == "model" for kind, status in rows) == 2
        assert all(status == "complete" for kind, status in rows)
    finally:
        b.close()


@pytest.mark.parametrize(
    "cut,occurrence", [("model_issued", 1), ("model_response", 1), ("tool_artifact", 2)]
)
def test_unknown_external_result_blocks_resume_and_retains_budget(
    durable_settings, cut, occurrence
):
    id_ = str(uuid4())
    probe("start", id_, "--cut", cut, "--occurrence", str(occurrence), expected=91)
    stopped = probe("resume", id_, expected=2)
    assert stopped["error"]["code"] == "RECOVERY_UNCERTAIN"
    b = backend(durable_settings, id_)
    try:
        ledger = DurableLedger(
            b,
            BudgetLimits(
                calls=durable_settings.max_model_calls, tokens=durable_settings.max_total_tokens
            ),
        )
        before = ledger.snapshot()
        stopped = probe("resume", id_, expected=2)
        assert stopped["error"]["code"] == "RECOVERY_UNCERTAIN"
        assert ledger.snapshot() == before
        if cut.startswith("model"):
            assert before.calls == 1 and before.total_tokens > 0 and not before.usage_complete
        else:
            assert before.calls == 1
    finally:
        b.close()


def test_interrupt_waits_for_trusted_approval_in_new_process(durable_settings):
    id_ = str(uuid4())
    wait = probe("start", id_, "--review")
    assert wait["status"] == "awaiting_review" and wait["usage"]["calls"] == 0
    wait_again = probe("resume", id_)
    assert wait_again["status"] == "awaiting_review" and wait_again["usage"]["calls"] == 0
    approved = probe("resume", id_, "--approve")
    assert approved["status"] == "succeeded" and approved["usage"]["calls"] == 2


def test_cancel_survives_restart_and_identity_policy_changes_fail_closed(durable_settings):
    id_ = str(uuid4())
    probe("start", id_, "--pause-after", "planner")
    for kwargs, code in [
        ({"owner": "another-owner"}, "RECOVERY_FORBIDDEN"),
        ({"question": "changed goal"}, "RECOVERY_IDENTITY"),
    ]:
        with pytest.raises(AgentFailure) as exc:
            run_async(run_durable(durable_settings, id_, resume=True, **kwargs))
        assert exc.value.error.code == code
    changed = durable_settings.model_copy(update={"max_rows": durable_settings.max_rows + 1})
    with pytest.raises(AgentFailure, match="changed"):
        run_async(run_durable(changed, id_, resume=True))
    b = backend(durable_settings, id_)
    try:
        b.cancel()
    finally:
        b.close()
    assert probe("resume", id_, expected=2)["error"]["code"] == "CANCELLED"


def test_p5a_l4_archive_and_budget_survive_process_loss(durable_settings):
    id_ = str(uuid4())
    paused = probe("start", id_, "--long", "--pause-after", "worker")
    complete = probe("resume", id_, "--long")
    assert complete["status"] == "succeeded"
    assert paused["usage"] == complete["usage"]
    assert any(
        "L4" in e.get("compression", {}).get("levels", [])
        for e in complete["trace"]
        if e.get("compression")
    )
    b = backend(durable_settings, id_)
    try:
        archives = [a for a in DurableArtifacts(b).export().values() if a.kind == "context"]
        assert archives and any("long_3" in a.values["messages"] for a in archives)
    finally:
        b.close()


def test_atomic_budget_idempotent_settlement_and_parallel_run_lease(durable_settings):
    id_ = str(uuid4())
    b = backend(durable_settings, id_)
    b.register({"test": "budget"}, BudgetLimits(calls=2, tokens=5000))
    ledger = DurableLedger(b, BudgetLimits(calls=2, tokens=5000))
    ledger.fork("1:a", BudgetLimits(calls=2, tokens=5000))

    def reserve(_):
        other = backend(durable_settings, id_)
        try:
            local = DurableLedger(other, BudgetLimits(calls=2, tokens=5000))
            return local.reserve("1:a", "small", 100)
        finally:
            other.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            tickets = list(pool.map(reserve, range(2)))
        assert ledger.snapshot().calls == 2
        ledger.settle(tickets[0], 15)
        before = ledger.snapshot()
        ledger.settle(tickets[0], 15)
        assert before == ledger.snapshot()
        with pytest.raises(AgentFailure):
            ledger.settle(tickets[0], 16)
        with pytest.raises(AgentFailure):
            ledger.reserve("1:a", "over", 100)
        with b.lease():
            other = backend(durable_settings, id_)
            try:
                with pytest.raises(AgentFailure, match="Another process"):
                    with other.lease():
                        pass
            finally:
                other.close()
    finally:
        b.close()


def test_runtime_has_no_business_or_ddl_privileges(durable_settings):
    b = backend(durable_settings, str(uuid4()))
    try:
        with b.engine.connect() as conn:
            flags = conn.exec_driver_sql(
                "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls "
                "FROM pg_roles WHERE rolname=current_user"
            ).one()
            assert not any(flags)
            assert not conn.exec_driver_sql(
                "SELECT has_schema_privilege(current_user,'checkpoints','CREATE')"
            ).scalar_one()
            assert not conn.exec_driver_sql(
                "SELECT has_schema_privilege(current_user,'saas','USAGE')"
            ).scalar_one()
            assert not conn.exec_driver_sql(
                "SELECT has_schema_privilege(current_user,'uploads','USAGE')"
            ).scalar_one()
    finally:
        b.close()


def test_parallel_one_success_one_safety_failure_survives_restart(durable_settings):
    id_ = str(uuid4())
    paused = probe("start", id_, "--parallel", "--pause-after", "worker")
    assert paused["results"]["1:good"]["status"] == "succeeded"
    assert paused["results"]["1:denied"]["error"]["code"] == "SQL_UNSAFE"
    final = probe("resume", id_, "--parallel")
    assert final["status"] == "failed" and final["completion"]["status"] == "blocked"
    assert final["results"] == paused["results"] and final["usage"] == paused["usage"]


@pytest.mark.parametrize("kind", ["artifact", "call", "ledger", "expired"])
def test_corruption_missing_scope_and_expiry_are_rejected(durable_settings, kind):
    id_ = str(uuid4())
    probe("start", id_, "--pause-after", "worker")
    admin = sa.create_engine(management_url("owner"), hide_parameters=True)
    try:
        with admin.begin() as conn:
            if kind == "artifact":
                execute(
                    conn,
                    "UPDATE execution.artifacts SET "
                    "payload=jsonb_set(payload,'{source}','\"corrupted\"') "
                    "WHERE run_id=:run AND kind='query'",
                    run=id_,
                )
            elif kind == "call":
                execute(
                    conn,
                    "UPDATE execution.calls SET payload='{}'::jsonb "
                    "WHERE run_id=:run AND kind='model'",
                    run=id_,
                )
            elif kind == "ledger":
                execute(
                    conn,
                    "UPDATE execution.ledger SET payload=jsonb_set(payload,'{sha256}','\"bad\"') "
                    "WHERE run_id=:run",
                    run=id_,
                )
            else:
                execute(
                    conn,
                    "UPDATE execution.runs SET expires_at=now()-interval '1 second' "
                    "WHERE run_id=:run",
                    run=id_,
                )
        result = probe("resume", id_, expected=2)
        assert result["error"]["code"] in {
            "EVIDENCE_INVALID",
            "RECOVERY_CORRUPT",
            "BUDGET_INVALID",
            "RECOVERY_EXPIRED",
        }
    finally:
        admin.dispose()


def test_runtime_connection_loss_releases_lease_and_fails_closed(durable_settings):
    id_ = str(uuid4())
    b = backend(durable_settings, id_)
    b.register({"test": "disconnect"}, BudgetLimits())
    admin = sa.create_engine(management_url("admin"), hide_parameters=True)
    try:
        with pytest.raises(sa.exc.SQLAlchemyError):
            with b.lease():
                pid = b.lease_connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
                with admin.begin() as conn:
                    assert execute(conn, "SELECT pg_terminate_backend(:pid)", pid=pid).scalar_one()
                b.assert_lease()
        with b.lease():
            b.assert_lease()
    finally:
        admin.dispose()
        b.close()


def test_artifact_append_only_quota_and_owner(durable_settings):
    id_ = str(uuid4())
    b = backend(durable_settings, id_)
    b.register({"test": "artifact-quota"}, BudgetLimits())
    try:
        store = DurableArtifacts(b)
        item = Artifact(
            run_id=id_,
            task_id="sql",
            plan_version=1,
            kind="schema",
            source="test-host",
            values={"schema": "synthetic"},
        )
        ref = store.put(item)
        assert store.put(item) == ref and store.get(ref) == item
        for n in range(1, 96):
            store.put(item.model_copy(update={"source": f"test-{n}"}))
        with pytest.raises(AgentFailure, match="quota"):
            store.put(item.model_copy(update={"source": "overflow"}))
        with b.engine.connect() as conn:
            assert not conn.exec_driver_sql(
                "SELECT has_table_privilege(current_user,'execution.artifacts','UPDATE')"
            ).scalar_one()
    finally:
        b.close()


def test_pg_disconnect_after_issued_model_never_releases_or_reissues(durable_settings):
    id_ = str(uuid4())
    b = backend(durable_settings, id_)
    limits = BudgetLimits(calls=4, tokens=5000)
    b.register({"test": "disconnect-issued"}, limits)
    ledger = DurableLedger(b, limits)
    journal = Journal(b, ledger, DurableArtifacts(b))
    admin = sa.create_engine(management_url("admin"), hide_parameters=True)
    try:
        with pytest.raises(sa.exc.SQLAlchemyError):
            with b.lease():
                key, ticket, _ = journal.begin_model(
                    "root", [HumanMessage(content="synthetic")], [], "synthetic", 100, None
                )
                with pytest.raises(AgentFailure, match="issued"):
                    ledger.release_unissued(ticket)
                pid = b.lease_connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
                with admin.begin() as conn:
                    execute(conn, "SELECT pg_terminate_backend(:pid)", pid=pid)
                journal.finish_model(key, ticket, AIMessage(content="not committed"), 15, 1)
        with b.lease():
            with pytest.raises(AgentFailure, match="Unconfirmed"):
                journal.recover()
            usage = ledger.snapshot()
            with pytest.raises(AgentFailure):
                journal.recover()
            assert usage == ledger.snapshot() and usage.calls == 1
            assert usage.total_tokens > 0 and not usage.usage_complete
    finally:
        admin.dispose()
        b.close()


def test_provider_overage_remains_charged_and_blocks_resume(durable_settings):
    id_ = str(uuid4())
    b = backend(durable_settings, id_)
    limits = BudgetLimits(calls=2, tokens=5000)
    b.register({"test": "overage"}, limits)
    ledger = DurableLedger(b, limits)
    journal = Journal(b, ledger, DurableArtifacts(b))
    response = AIMessage(
        content="synthetic",
        usage_metadata={
            "input_tokens": 5000,
            "output_tokens": 1000,
            "total_tokens": 6000,
        },
    )
    try:
        with b.lease():
            key, ticket, _ = journal.begin_model(
                "root", [HumanMessage(content="synthetic")], [], "synthetic", 100, None
            )
            with pytest.raises(AgentFailure, match="exceeded"):
                journal.finish_model(key, ticket, response, 6000, 1)
            with pytest.raises(AgentFailure, match="exceeded"):
                journal.recover()
            assert ledger.snapshot().total_tokens == 6000
            assert ledger.snapshot().reported_tokens == 6000
    finally:
        b.close()


def test_uncertain_request_prevents_in_process_replan_and_new_charge(durable_settings):
    id_ = str(uuid4())
    b = backend(durable_settings, id_)
    limits = BudgetLimits(calls=4, tokens=5000)
    b.register({"test": "unknown-no-replan"}, limits)
    ledger = DurableLedger(b, limits)
    journal = Journal(b, ledger, DurableArtifacts(b))
    try:
        with b.lease():
            key, ticket, _ = journal.begin_model(
                "root", [HumanMessage(content="synthetic")], [], "synthetic", 100, None
            )
            journal.finish_model(key, ticket, None, None, 1)
            usage = ledger.snapshot()
            with pytest.raises(AgentFailure, match="blocks new"):
                journal.begin_model(
                    "root", [HumanMessage(content="replan")], [], "replan", 100, None
                )
            assert usage == ledger.snapshot() and usage.calls == 1
    finally:
        b.close()
