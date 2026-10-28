"""Test infrastructure guards only; no private files, database or model API."""

from pathlib import Path

import pytest
from reporting_fixtures import validate_environment


def environment():
    roles = (
        "admin",
        "owner",
        "seed",
        "reader",
        "ingest",
        "upload_reader",
        "registry",
        "runtime",
        "checkpoint_owner",
        "rag_ingest",
        "rag_reader",
        "web",
        "maintenance",
    )
    return {
        "DATAPILOT_RUN_DB_TESTS": "1",
        "DATAPILOT_TEST_ISOLATED": "1",
    } | {
        f"DATAPILOT_{r.upper()}_DATABASE_URL": "postgresql+psycopg://"
        + ("postgres" if r == "admin" else "datapilot_" + r)
        + ":synthetic-only@localhost:55449/datapilot_test_contract"
        for r in roles
    }


def test_explicit_isolated_environment_is_portable():
    assert validate_environment(environment()).llm_mode == "fake"
    assert validate_environment(environment()).api_key is None


@pytest.mark.parametrize(
    "change",
    [
        {"DATAPILOT_RUN_DB_TESTS": "0"},
        {"DATAPILOT_TEST_ISOLATED": "0"},
        {"DATAPILOT_RAG_READER_DATABASE_URL": ""},
        {"DATAPILOT_RAG_READER_DATABASE_URL": "not-a-url"},
        {
            "DATAPILOT_RAG_READER_DATABASE_URL": "postgresql+psycopg://datapilot_rag_reader:p@localhost:55449/"
            "datapilot_test_contract?host=other-host"
        },
        {
            "DATAPILOT_RUNTIME_DATABASE_URL": "postgresql+psycopg://datapilot_runtime:p@localhost:55449/production"
        },
        {
            "DATAPILOT_READER_DATABASE_URL": "postgresql+psycopg://postgres:p@localhost:55449/datapilot_test_contract"
        },
        {
            "DATAPILOT_RAG_READER_DATABASE_URL": "postgresql+psycopg://datapilot_rag_reader:p@another-host:55449/datapilot_test_contract"
        },
    ],
)
def test_missing_or_cross_instance_or_privileged_role_is_refused(change):
    with pytest.raises(ValueError, match="isolated test"):
        validate_environment(environment() | change)


def test_model_credentials_do_not_change_fake_fixture_contract():
    settings = validate_environment(environment() | {"DATAPILOT_API_KEY": "not-a-real-key"})
    assert settings.api_key is None


def test_regression_helpers_do_not_import_private_experiments():
    root = Path(__file__).parents[1]
    for name in (
        "reporting_fixtures.py",
        "test_partial_evidence_postgres.py",
        "test_citation_policy_postgres.py",
        "test_original_query_postgres.py",
        "test_document_fact_postgres.py",
    ):
        text = (root / "tests" / name).read_text(encoding="utf-8")
        assert "artifacts/p7/" not in text
        assert "evaluation/p7" not in text
        assert "LEGACY_BINDINGS" not in text
        assert "DockerDesktop" not in text
