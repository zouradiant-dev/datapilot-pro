"""Local policy/confirmation tests. No database or real model is used here."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseFailure, ParseOptions
from datapilot.ingestion.parser import parse_bytes
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import validate_confirmation
from datapilot.runtime.mcp_client import server_environment
from datapilot.tools.sql import SQLPolicy, validate_sql

TABLE = "u_12345678123456781234567812345678_v1_t1"
POLICY = SQLPolicy("uploads", frozenset({TABLE}))
DATASET = "12345678-1234-5678-1234-567812345678"


@pytest.mark.parametrize(
    "statement",
    [
        f"SELECT COUNT(*) AS n FROM {TABLE}",
        f'WITH x AS (SELECT * FROM uploads."{TABLE}") SELECT COUNT(*) AS n FROM x',
        f'SELECT a.id FROM "{TABLE}" a JOIN uploads."{TABLE}" b ON a.id=b.id',
    ],
)
def test_scoped_queries_are_qualified(statement):
    assert f'uploads."{TABLE}"' in validate_sql(statement, POLICY)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM saas.customers",
        "SELECT * FROM catalog.datasets",
        "SELECT * FROM pg_catalog.pg_roles",
        "SELECT * FROM uploads.not_selected",
        f"SELECT * FROM {TABLE} UNION ALL SELECT * FROM uploads.not_selected",
        f"SELECT * FROM {TABLE} WHERE EXISTS(SELECT 1 FROM uploads.not_selected)",
        f"WITH {TABLE} AS (SELECT * FROM uploads.not_selected) SELECT * FROM {TABLE}",
        "WITH not_selected AS (SELECT 1) SELECT * FROM uploads.not_selected",
        f"INSERT INTO {TABLE} SELECT 1",
        f"SELECT * FROM {TABLE} FOR UPDATE",
        f"COPY {TABLE} TO '/tmp/file'",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT set_config('role','datapilot_ingest',false)",
    ],
)
def test_scope_cannot_be_expanded_by_sql(statement):
    with pytest.raises(AgentFailure) as error:
        validate_sql(statement, POLICY)
    assert error.value.error.code == "SQL_UNSAFE"


@pytest.mark.parametrize("name", ["../x", "x/y", "D:\\x", "x;DROP TABLE y", 'x"', ".", ".."])
def test_display_name_injection_rejected(name):
    with pytest.raises(ValidationError):
        ImportRequest(name=name)


def test_scope_is_bounded_unique_and_not_a_sql_allowlist():
    binding = DatasetBinding(dataset_id=DATASET, version=1)
    with pytest.raises(ValidationError):
        DatasetScope(bindings=[binding, binding])
    with pytest.raises(ValidationError):
        DatasetScope.model_validate({"physical_tables": [TABLE]})
    with pytest.raises(ValidationError):
        DatasetBinding(dataset_id="../file")
    with pytest.raises(ValueError):
        SQLPolicy("uploads", frozenset({'x"; DROP TABLE y'}))
    with pytest.raises(ValueError):
        SQLPolicy("saas", frozenset({TABLE}))


def test_confirmation_is_recomputed_not_trusted_as_an_authorization_token():
    data = parse_bytes(
        b"id,amount\n001,1.2300\n", "synthetic.csv", options=ParseOptions(header="present")
    )
    confirmed = confirm_schema(data, propose_schema(data), reviewed=True)
    assert validate_confirmation(data, confirmed) == confirmed
    forged = confirmed.model_copy(deep=True)
    forged.tables[0].columns[1].precision = 2
    with pytest.raises(ParseFailure):
        validate_confirmation(data, forged)
    changed = parse_bytes(b"id,amount\n002,1.2300\n", "synthetic.csv", options=data.options)
    with pytest.raises(ParseFailure):
        validate_confirmation(changed, confirmed)


def test_no_admin_ingest_or_scope_inheritance_in_mcp_environment(monkeypatch):
    for suffix in ["ADMIN_DATABASE_URL", "INGEST_DATABASE_URL", "API_KEY", "DATASET_SCOPE"]:
        monkeypatch.setenv("DATAPILOT_" + suffix, "untrusted-parent-value")
    env = server_environment(Settings(llm_mode="fake", _env_file=None))
    assert not any(k.endswith(("DATABASE_URL", "API_KEY", "DATASET_SCOPE")) for k in env)


def test_upload_role_must_not_use_an_administrative_dsn():
    with pytest.raises(ValidationError):
        Settings(
            llm_mode="fake",
            upload_reader_database_url="postgresql+psycopg://postgres:mock@localhost/db",
            _env_file=None,
        )


def test_frozen_day1_migration_unchanged():
    # The hash is the committed P1 baseline, not mutable application metadata.
    import hashlib

    root = Path(__file__).resolve().parents[1]
    actual = (root / "migrations/versions/0001_business_and_vectors.py").read_bytes()
    assert (
        hashlib.sha256(actual.replace(b"\r\n", b"\n")).hexdigest()
        == "a91900b4ce239deb48d749d20ddb7c02e0a2bff41d52d0ea9ba9b97b34453f49"
    )
    assert json.loads((root / "tests/fixtures/ingestion/manifest.json").read_text())["synthetic"]


@pytest.mark.parametrize("tamper", ["dataset", "version", "result_hash", "row_shape"])
async def test_untrusted_mcp_result_must_match_scope_version_shape_and_hash(tamper):
    from types import SimpleNamespace

    from datapilot.ingestion.common import digest
    from datapilot.runtime.mcp_client import MCPDatasetTools

    result = {
        "columns": ["n"],
        "rows": [[1]],
        "row_count": 1,
        "truncated": False,
        "elapsed_ms": 0.0,
    }
    payload = {
        "dataset_id": DATASET,
        "version": 1,
        "source_sha256": "a" * 64,
        "query_sha256": "b" * 64,
        "result_sha256": digest({k: v for k, v in result.items() if k != "elapsed_ms"}),
        "result": result,
    }
    if tamper == "dataset":
        payload["dataset_id"] = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    elif tamper == "version":
        payload["version"] = 2
    elif tamper == "result_hash":
        payload["result_sha256"] = "0" * 64
    else:
        payload["result"]["row_count"] = 2

    class FakeSession:
        async def call_tool(self, name, arguments):
            return SimpleNamespace(isError=False, structuredContent={"result": payload}, content=[])

    tools = MCPDatasetTools(
        FakeSession(),
        2,
        scope=DatasetScope(bindings=[DatasetBinding(dataset_id=DATASET, version=1)]),
    )
    with pytest.raises(AgentFailure) as error:
        await tools.execute(DATASET, "SELECT 1 AS n")
    assert error.value.error.code == "TOOL_OUTPUT_INVALID"
