"""Real PostgreSQL + real MCP. Synthetic test versions persist; never clear the database."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
import sqlalchemy as sa

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.datasets.repository import DatasetRepository
from datapilot.db import catalog
from datapilot.db.management import management_url
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import (
    ColumnOverride,
    ConfirmationOverrides,
    ParseFailure,
    ParseOptions,
)
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService
from datapilot.runtime.mcp_client import database_session, dataset_session

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/ingestion"


@pytest.fixture
def importer(pg_settings):
    if not pg_settings.upload_reader_database_url:
        pytest.fail("P2 integration enabled but upload reader DSN is missing")
    service = IngestionService(management_url("ingest"), storage_dir=ROOT / "artifacts/p2/sources")
    yield service
    service.close()


def confirmation(path):
    data = parse_file(path, options=ParseOptions(header="present"))
    return confirm_schema(data, propose_schema(data), reviewed=True)


def request():
    return ImportRequest(name="p2-test-" + uuid4().hex)


def scope(dataset_id, version=None):
    return DatasetScope(bindings=[DatasetBinding(dataset_id=dataset_id, version=version)])


@pytest.mark.parametrize(
    "filename,rows", [("customers_utf8_bom.csv", 3), ("saas_multi_sheet.xlsx", 7)]
)
async def test_file_pg_mcp_query_and_join(importer, pg_settings, filename, rows):
    source = FIXTURES / filename
    imported = importer.import_file(source, confirmation(source), request())
    assert imported.version == 1 and imported.row_count == rows and not imported.reused
    async with dataset_session(pg_settings, scope(imported.dataset_id)) as tools:
        assert [d.dataset_id for d in (await tools.listing()).datasets] == [imported.dataset_id]
        schema = await tools.schema(imported.dataset_id)
        first = schema.tables[0]
        query = await tools.execute(
            imported.dataset_id, f'SELECT COUNT(*) AS n FROM "{first.physical_name}"'
        )
        assert query.result.rows == [[3]] and query.version == 1
        assert query.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
        key = first.columns[0]
        ids = await tools.execute(
            imported.dataset_id,
            f'SELECT "{key.normalized_name}" AS id FROM "{first.physical_name}" ORDER BY 1',
        )
        assert ids.result.rows == [["0001"], ["0002"], ["0003"]]
        if filename.endswith("csv"):
            assert key.original_name == "客户编号" and key.logical_type == "TEXT"
        else:
            sheets = {t.source_name: t for t in schema.tables}
            customers, invoices = sheets["Customers"], sheets["Invoices"]
            joined = await tools.execute(
                imported.dataset_id,
                f'SELECT c.customer_id, SUM(i.amount) AS amount FROM "{customers.physical_name}" c '
                f'JOIN "{invoices.physical_name}" i USING(customer_id) GROUP BY 1 ORDER BY 1',
            )
            # The committed XLSX XML contains 89.98999999999999. Do not silently round it.
            assert [(key, Decimal(amount)) for key, amount in joined.result.rows] == [
                ("0001", Decimal("123.45") + Decimal("89.98999999999999")),
                ("0002", Decimal("1000")),
            ]
            formula = await tools.execute(
                imported.dataset_id, f'SELECT value FROM "{sheets["Review"].physical_name}"'
            )
            assert formula.result.rows == [["=2+2"]]
        engine = sa.create_engine(
            pg_settings.upload_reader_database_url.get_secret_value(), hide_parameters=True
        )
        try:
            with engine.connect() as conn:
                # Independent real SQL oracle, not a model-produced result.
                assert (
                    conn.exec_driver_sql(
                        f'SELECT COUNT(*) FROM uploads."{first.physical_name}"'
                    ).scalar_one()
                    == 3
                )
        finally:
            engine.dispose()


async def test_scope_is_server_bound_even_with_two_authorized_datasets(importer, pg_settings):
    path = FIXTURES / "customers_utf8_bom.csv"
    a, b = [importer.import_file(path, confirmation(path), request()) for _ in range(2)]
    async with dataset_session(pg_settings, scope(b.dataset_id)) as tools:
        other = (await tools.schema(b.dataset_id)).tables[0].physical_name
    async with dataset_session(pg_settings, scope(a.dataset_id)) as tools:
        with pytest.raises(AgentFailure, match="scope"):
            await tools.schema(b.dataset_id)
        with pytest.raises(AgentFailure) as error:
            await tools.call(
                "query_dataset",
                {
                    "dataset_id": b.dataset_id,
                    "sql": f'SELECT * FROM "{other}"',
                    "scope": {"dataset_id": b.dataset_id},
                    "physical_tables": [other],
                },
            )
        assert error.value.error.code == "DATASET_NOT_AUTHORIZED"
        with pytest.raises(AgentFailure) as error:
            await tools.execute(a.dataset_id, f'SELECT * FROM uploads."{other}"')
        assert error.value.error.code == "SQL_UNSAFE"
        listing = await tools.session.list_tools()
        tool_schema = next(t for t in listing.tools if t.name == "query_dataset")
        assert set(tool_schema.inputSchema["properties"]) == {"dataset_id", "sql"}
        with pytest.raises(AgentFailure) as error:
            await tools.call("query_database", {"sql": "SELECT 1"})
        assert error.value.error.code == "TOOL_FORBIDDEN"
    async with database_session(pg_settings) as tools:
        raw = await tools.session.call_tool("list_datasets", {})
        payload = raw.structuredContent or json.loads(
            next(c.text for c in raw.content if c.type == "text")
        )
        assert payload["error"]["code"] == "DATABASE_NOT_CONFIGURED"
    both = DatasetScope(bindings=[DatasetBinding(dataset_id=r.dataset_id) for r in (a, b)])
    async with dataset_session(pg_settings, both) as tools:
        assert len((await tools.listing()).datasets) == 2
        with pytest.raises(AgentFailure) as error:
            await tools.execute(a.dataset_id, f'SELECT * FROM "{other}"')
        assert error.value.error.code == "SQL_UNSAFE"
    async with dataset_session(pg_settings, DatasetScope()) as tools:
        assert (await tools.listing()).datasets == []
        with pytest.raises(AgentFailure) as error:
            await tools.schema(a.dataset_id)
        assert error.value.error.code == "DATASET_NOT_AUTHORIZED"


async def test_mcp_dangerous_sql_bad_field_and_empty_result(importer, pg_settings):
    path = FIXTURES / "customers_utf8_bom.csv"
    imported = importer.import_file(path, confirmation(path), request())
    async with dataset_session(pg_settings, scope(imported.dataset_id)) as tools:
        table = (await tools.schema(imported.dataset_id)).tables[0].physical_name
        for statement in [
            f'DROP TABLE "{table}"',
            f'DELETE FROM "{table}"',
            f'SELECT * INTO stolen FROM "{table}"',
            f'SELECT * FROM "{table}" FOR UPDATE',
            f'WITH x AS (DELETE FROM "{table}" RETURNING *) SELECT * FROM x',
            "SELECT * FROM saas.customers",
            "SELECT * FROM catalog.datasets",
            "SELECT * FROM pg_catalog.pg_roles",
            "SELECT pg_read_file('/etc/passwd')",
            "SELECT 1;SELECT 2",
        ]:
            with pytest.raises(AgentFailure) as error:
                await tools.execute(imported.dataset_id, statement)
            assert error.value.error.code == "SQL_UNSAFE"
        with pytest.raises(AgentFailure) as error:
            await tools.execute(imported.dataset_id, f'SELECT nonexistent FROM "{table}"')
        assert error.value.error.code == "SQL_EXECUTION_ERROR"
        empty = await tools.execute(imported.dataset_id, f'SELECT * FROM "{table}" WHERE false')
        assert (
            empty.result.row_count == 0 and empty.result.rows == [] and not empty.result.truncated
        )


def test_role_grants_independently_prevent_writes_and_ddl(importer, pg_settings):
    path = FIXTURES / "customers_utf8_bom.csv"
    imported = importer.import_file(path, confirmation(path), request())
    repository = DatasetRepository(
        pg_settings.upload_reader_database_url.get_secret_value(), scope(imported.dataset_id)
    )
    try:
        table = repository.schema(imported.dataset_id).tables[0].physical_name
        with repository.sql.engine.connect() as conn:
            for statement in [
                f'DELETE FROM uploads."{table}" WHERE false',
                f'UPDATE uploads."{table}" SET column_1=column_1 WHERE false',
                "UPDATE catalog.datasets SET name=name WHERE false",
                "CREATE TABLE uploads.forbidden_test(id int)",
                "CREATE TEMP TABLE forbidden_test(id int)",
                "CREATE TABLE public.forbidden_test(id int)",
                "SET ROLE datapilot_ingest",
                "SELECT * FROM saas.customers",
            ]:
                conn.exec_driver_sql("SET TRANSACTION READ WRITE")
                with pytest.raises(sa.exc.DBAPIError):
                    conn.exec_driver_sql(statement)
                conn.rollback()
        with importer.engine.connect() as conn:
            for statement in [
                "INSERT INTO saas.customers(customer_id) VALUES(-1)",
                "SELECT * FROM rag.document_chunks",
                "CREATE TABLE public.forbidden_ingest(id int)",
                "CREATE TEMP TABLE forbidden_ingest(id int)",
                "SET ROLE datapilot_owner",
            ]:
                with pytest.raises(sa.exc.DBAPIError):
                    conn.exec_driver_sql(statement)
                conn.rollback()
        engine = sa.create_engine(
            pg_settings.reader_database_url.get_secret_value(), hide_parameters=True
        )
        try:
            with engine.connect() as conn:
                with pytest.raises(sa.exc.DBAPIError):
                    conn.exec_driver_sql(f'SELECT * FROM uploads."{table}"')
                conn.rollback()
        finally:
            engine.dispose()
    finally:
        repository.close()


def test_duplicate_and_concurrent_import_are_idempotent(importer):
    path = FIXTURES / "saas_multi_sheet.xlsx"
    reviewed, req = confirmation(path), request()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: importer.import_file(path, reviewed, req), range(2)))
    assert {r.version for r in results} == {1}
    assert sorted(r.reused for r in results) == [False, True]
    again = importer.import_file(path, reviewed, req)
    assert again.reused and again.row_count == 7
    with importer.engine.connect() as conn:
        assert (
            conn.execute(
                sa.select(sa.func.count())
                .select_from(catalog.versions)
                .where(catalog.versions.c.dataset_id == again.dataset_id)
            ).scalar_one()
            == 1
        )


def test_concurrent_first_snapshot_is_complete_and_hash_addressed(importer, tmp_path):
    source = tmp_path / "first-snapshot.csv"
    source.write_text("id,note\n0001," + uuid4().hex + "\n", encoding="utf-8")
    reviewed, req = confirmation(source), request()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: importer.import_file(source, reviewed, req), range(2)))
    assert sorted(r.reused for r in results) == [False, True]
    assert (
        importer.storage_dir / (reviewed.source_sha256 + ".csv")
    ).read_bytes() == source.read_bytes()
    assert not list(importer.storage_dir.glob("*.tmp"))


async def test_csv_exact_money_is_not_converted_through_float(importer, pg_settings):
    path = FIXTURES / "invoices_semicolon.csv"
    imported = importer.import_file(path, confirmation(path), request())
    async with dataset_session(pg_settings, scope(imported.dataset_id)) as tools:
        table = (await tools.schema(imported.dataset_id)).tables[0].physical_name
        result = await tools.execute(
            imported.dataset_id, f'SELECT SUM(amount) AS total FROM "{table}"'
        )
        assert result.result.rows == [["1213.4400"]]


@pytest.mark.parametrize("existing_dataset", [False, True])
def test_real_database_failure_rolls_back_ddl_rows_catalog_and_publication(
    importer, monkeypatch, existing_dataset
):
    req = request()
    prior = None
    if existing_dataset:
        source = FIXTURES / "customers_utf8_bom.csv"
        prior = importer.import_file(source, confirmation(source), req)
        req.dataset_id = prior.dataset_id
    path = FIXTURES / "saas_multi_sheet.xlsx"
    original = importer._write_rows
    count = 0

    def failing_rows(conn, table, rows, deadline):
        nonlocal count
        original(conn, table, rows, deadline)
        count += 1
        if count == 2:
            conn.exec_driver_sql("SELECT 1/0")  # Real PG fault after transactional DDL and inserts.

    monkeypatch.setattr(importer, "_write_rows", failing_rows)
    with pytest.raises(AgentFailure) as error:
        importer.import_file(path, confirmation(path), req)
    assert error.value.error.code == "IMPORT_DATABASE_ERROR"
    dataset_id = (
        prior.dataset_id if prior else str(uuid5(NAMESPACE_URL, "datapilot:local:" + req.name))
    )
    failed_version = 2 if prior else 1
    with importer.engine.connect() as conn:
        assert not conn.execute(
            sa.select(catalog.versions.c.version).where(
                catalog.versions.c.dataset_id == dataset_id,
                catalog.versions.c.version == failed_version,
            )
        ).all()
        assert not any(
            t.startswith(f"u_{dataset_id.replace('-', '')}_v{failed_version}_")
            for t in sa.inspect(conn).get_table_names(schema="uploads")
        )
        current = conn.execute(
            sa.select(catalog.datasets.c.current_version).where(
                catalog.datasets.c.dataset_id == dataset_id
            )
        ).scalar_one_or_none()
        assert current == (1 if prior else None)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert (importer.storage_dir / (sha + ".xlsx")).is_file()


async def test_immutable_versions_activation_and_session_pinning(importer, pg_settings, tmp_path):
    path = tmp_path / "versions.csv"
    path.write_text("id,amount\n001,1.2300\n", encoding="utf-8")
    req = request()
    v1 = importer.import_file(path, confirmation(path), req)
    async with dataset_session(pg_settings, scope(v1.dataset_id)) as old:
        t1 = (await old.schema(v1.dataset_id)).tables[0].physical_name
        path.write_text("id,amount\n002,2.3400\n003,3.4500\n", encoding="utf-8")
        reviewed_v2 = confirmation(path)
        v2 = importer.import_file(
            path, reviewed_v2, ImportRequest(name=req.name, dataset_id=v1.dataset_id)
        )
        assert v2.version == 2 and v2.source_sha256 != v1.source_sha256
        assert (await old.schema(v1.dataset_id)).version == 1
        assert (await old.execute(v1.dataset_id, f'SELECT id FROM "{t1}"')).result.rows == [["001"]]
        async with dataset_session(pg_settings, scope(v1.dataset_id)) as current:
            assert (await current.schema(v1.dataset_id)).version == 2
            importer.activate_version(DatasetBinding(dataset_id=v1.dataset_id, version=1))
            assert (await current.schema(v1.dataset_id)).version == 2
        assert importer.import_file(path, reviewed_v2, req).reused
    async with dataset_session(pg_settings, scope(v1.dataset_id)) as fresh:
        assert (await fresh.schema(v1.dataset_id)).version == 1
    async with dataset_session(pg_settings, scope(v1.dataset_id, 2)) as explicit:
        assert (await explicit.schema(v1.dataset_id)).version == 2
    with pytest.raises(AgentFailure):
        importer.activate_version(DatasetBinding(dataset_id=v1.dataset_id, version=999999))


async def test_truncation_timeout_boolean_numeric_and_output_size(importer, pg_settings, tmp_path):
    path = tmp_path / "typed.csv"
    path.write_text(
        "id,amount,enabled,date,at\n001,1.2300,true,2025-01-01,2025-01-01T12:00:00+08:00\n"
        "002,2.3400,false,2025-01-02,2025-01-02T12:00:00+08:00\n",
        encoding="utf-8",
    )
    imported = importer.import_file(path, confirmation(path), request())
    async with dataset_session(
        pg_settings.model_copy(update={"max_rows": 1}), scope(imported.dataset_id)
    ) as tools:
        table = (await tools.schema(imported.dataset_id)).tables[0].physical_name
        data = await tools.execute(
            imported.dataset_id, f'SELECT * FROM "{table}" ORDER BY id LIMIT ALL'
        )
        assert data.result.rows == [
            ["001", "1.2300", True, "2025-01-01", "2025-01-01T04:00:00+00:00"]
        ]
        assert data.result.truncated and data.result.row_count == 1
    path = tmp_path / "large.csv"
    path.write_text("id,note\n001," + "x" * 5000 + "\n", encoding="utf-8")
    large = importer.import_file(path, confirmation(path), request())
    async with dataset_session(pg_settings, scope(large.dataset_id)) as tools:
        table = (await tools.schema(large.dataset_id)).tables[0].physical_name
        with pytest.raises(AgentFailure) as error:
            await tools.execute(large.dataset_id, f'SELECT note FROM "{table}"')
        assert error.value.error.code == "RESULT_TOO_LARGE"
    path = tmp_path / "timeout.csv"
    path.write_text("id\n" + "\n".join(str(i) for i in range(500)) + "\n", encoding="utf-8")
    many = importer.import_file(path, confirmation(path), request())
    async with dataset_session(
        pg_settings.model_copy(update={"query_timeout_seconds": 0.05}), scope(many.dataset_id)
    ) as tools:
        table = (await tools.schema(many.dataset_id)).tables[0].physical_name
        with pytest.raises(AgentFailure) as error:
            await tools.execute(
                many.dataset_id,
                f'SELECT SUM(a.id*b.id*c.id*d.id) AS n FROM "{table}" a '
                f'CROSS JOIN "{table}" b CROSS JOIN "{table}" c CROSS JOIN "{table}" d',
            )
        assert error.value.error.code == "QUERY_TIMEOUT"


def test_stale_confirmation_and_header_only_file_do_not_import(importer, tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("id\n1\n", encoding="utf-8")
    reviewed = confirmation(path)
    path.write_text("id\n", encoding="utf-8")
    with pytest.raises(ParseFailure):
        importer.import_file(path, reviewed, request())
    with pytest.raises(ParseFailure) as error:
        confirmation(path)
    assert error.value.error.code == "EMPTY_TABLE_CONFIRMATION"


def test_operator_import_and_dataset_cli_returns_structured_errors(
    pg_settings, tmp_path, monkeypatch, capsys
):
    import sys

    from datapilot.cli import main

    source = FIXTURES / "invoices_semicolon.csv"
    reviewed = tmp_path / "confirmation.json"
    reviewed.write_text(confirmation(source).model_dump_json(), encoding="utf-8")
    name = request().name
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "datapilot",
            "ingest",
            "import",
            str(source),
            "--name",
            name,
            "--confirmation",
            str(reviewed),
        ],
    )
    assert main() == 0
    imported = json.loads(capsys.readouterr().out)
    dataset_id = imported["dataset_id"]
    monkeypatch.setattr(sys, "argv", ["datapilot", "datasets", "schema", dataset_id])
    assert main() == 0
    schema = json.loads(capsys.readouterr().out)
    table = schema["tables"][0]["physical_name"]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "datapilot",
            "datasets",
            "query",
            dataset_id,
            f'SELECT SUM(amount) AS total FROM "{table}"',
        ],
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["result"]["rows"] == [["1213.4400"]]
    monkeypatch.setattr(
        sys, "argv", ["datapilot", "datasets", "query", dataset_id, "DROP TABLE stolen"]
    )
    assert main() == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err)["error"]["code"] == "SQL_UNSAFE" and not captured.out
    monkeypatch.setattr(
        sys, "argv", ["datapilot", "datasets", "activate", dataset_id, "--version", "1"]
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["version"] == 1


async def test_original_header_is_data_and_confirmed_identifier_is_quoted(
    importer, pg_settings, tmp_path
):
    import csv

    path = tmp_path / "quoted.csv"
    original = "customer_id); DROP SCHEMA saas CASCADE; --"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([original])
        writer.writerow(["0001"])
    data = parse_file(path, options=ParseOptions(header="present", delimiter=","))
    proposal = propose_schema(data)
    column = data.tables[0].columns[0].normalized_name
    reviewed = confirm_schema(
        data,
        proposal,
        reviewed=True,
        overrides=ConfirmationOverrides(
            columns=[
                ColumnOverride(table_id="table_1", column=column, normalized_name="authorization")
            ]
        ),
    )
    imported = importer.import_file(path, reviewed, request())
    async with dataset_session(pg_settings, scope(imported.dataset_id)) as tools:
        table = (await tools.schema(imported.dataset_id)).tables[0]
        assert table.columns[0].original_name == original
        result = await tools.execute(
            imported.dataset_id, f'SELECT "authorization" FROM "{table.physical_name}"'
        )
        assert result.result.rows == [["0001"]]
