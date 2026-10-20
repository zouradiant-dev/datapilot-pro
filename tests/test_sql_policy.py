import pytest

from datapilot.contracts import AgentFailure
from datapilot.tools.sql import validate_sql


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM customers",
        "DROP TABLE customers",
        "UPDATE customers SET name='x'",
        "SELECT 1; SELECT 2",
        "SELECT 1; DELETE FROM customers",
        "COPY customers TO '/tmp/x'",
        "SELECT pg_sleep(1)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT lo_export(1,'x')",
        "SELECT * FROM pg_catalog.pg_authid",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM rag.document_chunks",
        "SELECT * FROM seed_runs",
        "SELECT set_config('role','postgres',false)",
        "SELECT public.count(*) FROM customers",
        "WITH x AS (DELETE FROM customers RETURNING *) SELECT * FROM x",
        "WITH pg_authid AS (SELECT 1) SELECT * FROM pg_catalog.pg_authid",
        "SELECT * INTO stolen FROM customers",
        "SELECT * FROM customers FOR UPDATE",
        "WITH RECURSIVE c AS (SELECT 1 UNION ALL SELECT 2 FROM c) SELECT * FROM c",
        "SELECT * FROM generate_series(1,10000000)",
        "SELECT $1",
        "SELECT 'pg_authid'::regclass",
        "GRANT SELECT ON customers TO PUBLIC",
        "garbage",
        "",
    ],
)
def test_reject_unsafe(sql):
    with pytest.raises(AgentFailure) as error:
        validate_sql(sql)
    assert error.value.error.code == "SQL_UNSAFE"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS n FROM customers",
        "SELECT COALESCE(SUM(amount_cents),0) AS cents FROM invoices "
        "WHERE status='paid' AND invoice_date >= '2025-10-01' AND invoice_date < '2025-11-01'",
        "SELECT customer_id FROM customers WHERE segment='small' OR region='east'",
        "SELECT c.segment,COUNT(s.subscription_id) AS n FROM customers c "
        "JOIN subscriptions s ON c.customer_id=s.customer_id GROUP BY c.segment",
        "WITH c AS (SELECT customer_id FROM customers) SELECT COUNT(*) AS n FROM c",
        "SELECT SUM(amount_cents) AS cents FROM saas.invoices "
        "WHERE invoice_date >= '2025-10-01'::date",
        "SELECT DATE_TRUNC('month', invoice_date) AS month, SUM(amount_cents) AS cents "
        "FROM invoices GROUP BY 1",
        "SELECT customer_id FROM customers UNION ALL SELECT customer_id FROM subscriptions",
    ],
)
def test_allow_and_qualify_business_select(sql):
    checked = validate_sql(sql)
    assert "saas." in checked
