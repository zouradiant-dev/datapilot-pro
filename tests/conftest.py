import os

import pytest
from dotenv import load_dotenv
from reporting_fixtures import portable_pg as portable_pg
from reporting_fixtures import reporting_dev as reporting_dev
from reporting_fixtures import reporting_output as reporting_output

from datapilot.config import Settings


def _redact_test_output(value):
    text = str(value)
    for key, secret in os.environ.items():
        if secret and len(secret) >= 8 and key.endswith(("PASSWORD", "API_KEY", "DATABASE_URL")):
            text = text.replace(secret, "[REDACTED]")
    return text


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if isinstance(report.longrepr, tuple):
        report.longrepr = tuple(
            _redact_test_output(value) if isinstance(value, str) else value
            for value in report.longrepr
        )
    elif report.longrepr is not None:
        report.longrepr = _redact_test_output(report.longrepr)
    report.sections = [(label, _redact_test_output(body)) for label, body in report.sections]


@pytest.fixture
def settings():
    return Settings(llm_mode="fake", reader_database_url=None, _env_file=None)


@pytest.fixture
def pg_settings():
    load_dotenv()
    if os.getenv("DATAPILOT_RUN_DB_TESTS") != "1":
        pytest.skip("Real PostgreSQL integration requires DATAPILOT_RUN_DB_TESTS=1")
    config = Settings(llm_mode="fake")
    if not config.reader_database_url:
        pytest.fail("Integration enabled but reader DSN is missing")
    return config
