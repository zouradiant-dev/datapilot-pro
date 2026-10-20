import os

import pytest
from dotenv import load_dotenv

from datapilot.config import Settings


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
