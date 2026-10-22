"""Destructive assertions ONLY in a newly created, explicitly isolated database."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from psycopg import sql
from sqlalchemy.engine import make_url

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.db.management import grant_business_access, initialize, management_url, migrate
from datapilot.persistence.backend import execute
from datapilot.persistence.management import runtime_init
from datapilot.persistence.retention import CHECKPOINTS, EXECUTION, Retainer
from datapilot.persistence.session import run_async, run_durable

pytestmark = pytest.mark.integration


@pytest.fixture
def isolated(pg_settings, monkeypatch):
    original = make_url(management_url("admin"))
    name = "datapilot_retention_test_" + uuid4().hex[:16]
    assert name != original.database and name.startswith("datapilot_retention_test_")
    admin = sa.create_engine(original, hide_parameters=True, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn, conn.connection.driver_connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    admin.dispose()
    # Every role points to the new DB, including subprocess/MCP environment. No seed/delete/drop.
    for key, value in list(os.environ.items()):
        if key.startswith("DATAPILOT_") and key.endswith("_DATABASE_URL"):
            monkeypatch.setenv(
                key, make_url(value).set(database=name).render_as_string(hide_password=False)
            )
    assert make_url(management_url("admin")).database == name
    initialize()
    migrate()
    grant_business_access()
    runtime_init()
    config = Settings(llm_mode="fake")
    owner = sa.create_engine(management_url("owner"), hide_parameters=True)
    retainer = Retainer(management_url("maintenance"))
    try:
        yield config, owner, retainer
    finally:
        retainer.close()
        owner.dispose()
        # Deliberately keep the isolated database for audit. Never DROP a database/volume here.


def expire(owner, id_):
    with owner.begin() as conn:
        execute(
            conn,
            "UPDATE execution.runs SET expires_at=:e WHERE run_id=:r",
            r=id_,
            e=datetime.now(UTC) - timedelta(seconds=1),
        )


def test_atomic_whole_thread_purge_and_fail_closed_guards(isolated):
    config, owner, retention = isolated
    id_ = str(uuid4())
    result = run_async(run_durable(config, id_, "查询客户总数"))
    assert result["status"] == "succeeded"
    with pytest.raises(AgentFailure, match="expired"):
        retention.plan(id_)
    expire(owner, id_)
    before = retention.plan(id_)
    assert before == retention.plan(id_)  # dry-run does not mutate execution/checkpoints
    assert before["counts"]["checkpoints.checkpoints"] > 0
    assert before["counts"]["execution.artifacts"] > 0
    with pytest.raises(AgentFailure):
        retention.purge(id_, reviewed=False, confirm_hash=before["plan_hash"])
    with pytest.raises(AgentFailure):
        retention.purge(id_, reviewed=True, confirm_hash="0" * 64)
    retention.hold(id_, active=True, reason="isolated test")
    with pytest.raises(AgentFailure, match="hold"):
        retention.plan(id_)
    retention.hold(id_, active=False, reason="isolated test reviewed")
    with owner.connect() as conn:
        execute(conn, "SELECT pg_advisory_lock(hashtextextended(:r,9182))", r=id_)
        try:
            with pytest.raises(AgentFailure, match="lease"):
                retention.plan(id_)
        finally:
            execute(conn, "SELECT pg_advisory_unlock(hashtextextended(:r,9182))", r=id_)
    with owner.begin() as conn:
        execute(
            conn,
            "INSERT INTO execution.calls "
            "(run_id,call_key,fingerprint,kind,account,status) "
            "VALUES (:r,'test-unknown','unknown','tool','root','uncertain')",
            r=id_,
        )
    with pytest.raises(AgentFailure, match="reconciliation"):
        retention.plan(id_)
    # Delete ONLY this injected test row, in the new database (assert again before mutation).
    assert make_url(management_url("owner")).database.startswith("datapilot_retention_test_")
    with owner.begin() as conn:
        execute(
            conn, "DELETE FROM execution.calls WHERE run_id=:r AND call_key='test-unknown'", r=id_
        )
    plan = retention.plan(id_)

    def crash(point):
        raise RuntimeError("injected atomic rollback")

    with pytest.raises(RuntimeError, match="rollback"):
        retention.purge(id_, reviewed=True, confirm_hash=plan["plan_hash"], fault=crash)
    assert retention.plan(id_) == plan
    result = retention.purge(id_, reviewed=True, confirm_hash=plan["plan_hash"])
    assert result["status"] == "purged"
    with retention.engine.connect() as conn:
        for table in EXECUTION:
            assert (
                execute(
                    conn, f"SELECT count(*) FROM execution.{table} WHERE run_id=:r", r=id_
                ).scalar_one()
                == 0
            )
        for table in CHECKPOINTS:
            assert (
                execute(
                    conn, f"SELECT count(*) FROM checkpoints.{table} WHERE thread_id=:r", r=id_
                ).scalar_one()
                == 0
            )
        assert (
            conn.exec_driver_sql(
                "SELECT max(v) FROM checkpoints.checkpoint_migrations"
            ).scalar_one()
            == 9
        )
        assert (
            conn.exec_driver_sql("SELECT count(*) FROM execution.retention_audit").scalar_one() == 1
        )
    with pytest.raises(AgentFailure):
        retention.plan(id_)


def test_awaiting_review_and_runtime_permissions_block_cleanup(isolated):
    config, owner, retention = isolated
    id_ = str(uuid4())
    result = run_async(run_durable(config, id_, "查询客户总数", require_review=True))
    assert result["status"] == "awaiting_review"
    expire(owner, id_)
    with pytest.raises(AgentFailure, match="review|terminal"):
        retention.plan(id_)
    runtime = sa.create_engine(config.runtime_database_url.get_secret_value(), hide_parameters=True)
    with runtime.connect() as conn:
        assert not conn.exec_driver_sql(
            "SELECT has_table_privilege(current_user,'execution.runs','DELETE')"
        ).scalar_one()
        assert not conn.exec_driver_sql(
            "SELECT has_schema_privilege(current_user,'execution','CREATE')"
        ).scalar_one()
    runtime.dispose()
