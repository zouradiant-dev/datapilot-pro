"""Real PostgreSQL only. Run after bootstrap/migration/seed; no database mocks here."""

import pytest
import sqlalchemy as sa

from datapilot.contracts import AgentFailure
from datapilot.data.generator import generate_dataset, seed_database
from datapilot.db.health import database_health
from datapilot.db.management import management_url
from datapilot.graph import run_question
from datapilot.runtime.mcp_client import database_session
from datapilot.tools.sql import SQLRepository

pytestmark = pytest.mark.integration


def test_management_reentry_and_cli_health(pg_settings, monkeypatch, capsys):
    """Bootstrap/migration reentry is safe; seed reentry explicitly fails without modifying data."""
    import json
    import sys

    from datapilot.cli import main
    from datapilot.db.management import grant_business_access, initialize, migrate

    initialize()
    migrate()
    grant_business_access()
    monkeypatch.setattr(sys, "argv", ["datapilot", "health"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["customers"] == 240
    monkeypatch.setattr(sys, "argv", ["datapilot", "seed"])
    assert main() == 2
    assert "Configuration/database error" in capsys.readouterr().err


@pytest.fixture
def repository(pg_settings):
    tool = SQLRepository(pg_settings.reader_database_url.get_secret_value())
    yield tool
    tool.close()


def test_postgres17_pgvector_schema_and_reader_permissions(pg_settings):
    url = pg_settings.reader_database_url.get_secret_value()
    health = database_health(url)
    assert health["postgres_version_num"] // 10000 == 17 and health["pgvector"]
    assert health["customers"] == 240
    engine = sa.create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as conn:
            assert not conn.exec_driver_sql(
                "SELECT has_schema_privilege(current_user,'rag','USAGE')"
            ).scalar_one()
            assert not conn.exec_driver_sql(
                "SELECT has_table_privilege(current_user,'saas.customers','INSERT,UPDATE,DELETE')"
            ).scalar_one()
        # Read-only setting can be changed by a user; grants must independently prevent writes.
        with engine.connect() as conn:
            conn.exec_driver_sql("SET TRANSACTION READ WRITE")
            with pytest.raises(sa.exc.DBAPIError):
                conn.exec_driver_sql("DELETE FROM saas.customers WHERE false")
            conn.rollback()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "question, expected_sql",
    [
        ("查询客户总数", "SELECT COUNT(*) FROM saas.customers"),
        (
            "计算2025-10收入",
            "SELECT COALESCE(SUM(amount_cents),0) FROM saas.invoices "
            "WHERE status='paid' AND invoice_date >= DATE '2025-10-01' "
            "AND invoice_date < DATE '2025-11-01'",
        ),
        (
            "查询2025-07-01到2025-10-01新增订阅",
            "SELECT COUNT(*) FROM saas.subscriptions "
            "WHERE start_date >= DATE '2025-07-01' AND start_date < DATE '2025-10-01'",
        ),
        (
            "按客户分群查询活跃订阅 JOIN",
            "SELECT c.segment,COUNT(*) FROM saas.customers c "
            "JOIN saas.subscriptions s USING(customer_id) WHERE s.status='active' "
            "GROUP BY c.segment ORDER BY c.segment",
        ),
    ],
)
async def test_fake_model_real_mcp_and_postgres(pg_settings, question, expected_sql):
    # Independent SQL oracle, executed against the real database, not a canned fake result.
    engine = sa.create_engine(
        pg_settings.reader_database_url.get_secret_value(), hide_parameters=True
    )
    try:
        with engine.connect() as conn:
            expected = [[str(v) for v in r] for r in conn.exec_driver_sql(expected_sql).fetchall()]
    finally:
        engine.dispose()
    result = await run_question(pg_settings, question)
    assert result["mode"] == "fake" and result["status"] == "succeeded", result["error"]
    assert [[str(v) for v in r] for r in result["result"].result.rows] == expected


async def test_real_mcp_security_bad_field_and_repair(pg_settings):
    async with database_session(pg_settings) as tool:
        with pytest.raises(AgentFailure) as error:
            await tool.execute("DELETE FROM customers")
        assert error.value.error.code == "SQL_UNSAFE"
        with pytest.raises(AgentFailure) as error:
            await tool.execute("SELECT nonexistent_field FROM customers")
        assert error.value.error.code == "SQL_EXECUTION_ERROR"
    result = await run_question(
        pg_settings,
        "查询客户总数",
        scripted_sql=[
            "SELECT nonexistent_field FROM customers",
            "SELECT nonexistent_field FROM customers",
        ],
    )
    assert result["status"] == "failed" and result["error"].code == "SQL_EXECUTION_ERROR"
    assert result["result"].attempts == 2 and result["result"].result is None
    repaired = await run_question(
        pg_settings,
        "查询客户总数",
        scripted_sql=[
            "SELECT nonexistent_field FROM customers",
            "SELECT COUNT(*) AS n FROM customers",
        ],
    )
    assert repaired["status"] == "succeeded" and repaired["result"].attempts == 2


def test_timeout_limit_and_seed_refuses_overwrite(pg_settings):
    url = pg_settings.reader_database_url.get_secret_value()
    tool = SQLRepository(url, max_rows=3, timeout_seconds=0.001)
    try:
        with pytest.raises(AgentFailure) as error:
            tool.execute(
                "SELECT SUM(a.customer_id*b.customer_id*c.customer_id) AS n "
                "FROM customers a CROSS JOIN customers b CROSS JOIN customers c"
            )
        assert error.value.error.code == "QUERY_TIMEOUT"
    finally:
        tool.close()
    tool = SQLRepository(url, max_rows=3)
    try:
        limited = tool.execute("SELECT customer_id FROM customers ORDER BY customer_id LIMIT ALL")
        assert limited.row_count == 3 and limited.truncated
    finally:
        tool.close()
    with pytest.raises(ValueError, match="nonempty"):
        seed_database(management_url("seed"), generate_dataset())


def test_postgres_results_and_foreign_key_constraints(repository, pg_settings):
    assert "customer_id -> customers.customer_id" in repository.schema()
    result = repository.execute(
        "WITH c AS (SELECT customer_id FROM customers) SELECT COUNT(*) AS n FROM c"
    )
    assert result.rows == [[240]]
    with pytest.raises(AgentFailure) as error:
        repository.execute("SELECT customer_id,customer_id FROM customers")
    assert error.value.error.code == "VERIFICATION_ERROR"
    engine = sa.create_engine(management_url("owner"), hide_parameters=True)
    try:
        with engine.connect() as conn:
            with pytest.raises(sa.exc.IntegrityError):
                conn.exec_driver_sql(
                    "INSERT INTO saas.subscriptions VALUES "
                    "(-1,-1,'pro',49900,'2025-01-01',NULL,'active')"
                )
            conn.rollback()
    finally:
        engine.dispose()


def test_vector_storage_and_distance(pg_settings):
    engine = sa.create_engine(management_url("owner"), hide_parameters=True)
    try:
        with engine.connect() as conn:
            tx = conn.begin()
            try:
                conn.exec_driver_sql(
                    "INSERT INTO rag.document_chunks VALUES "
                    "(-1,'test://a','test document','test-only',3,'[1,0,0]'::public.vector)"
                )
                distance = conn.exec_driver_sql(
                    "SELECT embedding <=> '[1,0,0]'::public.vector FROM rag.document_chunks "
                    "WHERE chunk_id=-1"
                ).scalar_one()
                assert distance == pytest.approx(0)
            finally:
                tx.rollback()  # No test vectors persist in the business dataset.
    finally:
        engine.dispose()
