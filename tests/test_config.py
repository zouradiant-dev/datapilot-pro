import pytest
from pydantic import ValidationError

from datapilot.config import Settings


def test_no_silent_fake_fallback_and_role_validation(monkeypatch):
    for key in ("DATAPILOT_API_KEY", "DATAPILOT_MODEL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValidationError):
        Settings(llm_mode="live", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(
            llm_mode="fake",
            reader_database_url="postgresql+psycopg://postgres:mock@localhost/datapilot",
            _env_file=None,
        )
    with pytest.raises(ValidationError):
        Settings(llm_mode="fake", max_sql_attempts=0, _env_file=None)
