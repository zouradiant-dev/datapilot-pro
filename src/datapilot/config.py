"""Validated settings; management credentials never enter model or graph state."""

from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATAPILOT_", env_file=".env", extra="ignore")

    llm_mode: Literal["live", "fake"] = "live"
    api_key: SecretStr | None = None
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    reader_database_url: SecretStr | None = None
    upload_reader_database_url: SecretStr | None = None
    model_timeout_seconds: float = Field(default=30, gt=0, le=120)
    query_timeout_seconds: float = Field(default=2, gt=0, le=30)
    mcp_timeout_seconds: float = Field(default=10, gt=0, le=60)
    max_model_calls: int = Field(default=8, ge=1, le=20)
    max_input_chars: int = Field(default=16000, ge=100, le=64000)
    max_output_tokens: int = Field(default=1200, ge=16, le=4096)
    max_total_tokens: int = Field(default=18000, ge=100, le=100000)
    max_sql_attempts: int = Field(default=2, ge=1, le=3)
    max_steps: int = Field(default=20, ge=1, le=30)
    max_rows: int = Field(default=100, ge=1, le=1000)
    max_tasks: int = Field(default=8, ge=1, le=12)
    max_parallel_workers: int = Field(default=2, ge=1, le=4)
    max_worker_turns: int = Field(default=4, ge=2, le=8)
    max_replans: int = Field(default=1, ge=0, le=3)

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.reader_database_url:
            url = make_url(self.reader_database_url.get_secret_value())
            if url.drivername != "postgresql+psycopg" or url.username != "datapilot_reader":
                raise ValueError("MCP requires the PostgreSQL psycopg reader role")
        if self.upload_reader_database_url:
            url = make_url(self.upload_reader_database_url.get_secret_value())
            if url.drivername != "postgresql+psycopg" or url.username != "datapilot_upload_reader":
                raise ValueError("Dataset MCP requires the isolated upload reader role")
        if self.llm_mode == "live":
            if not self.api_key or not self.api_key.get_secret_value().strip() or not self.model:
                raise ValueError("Live mode requires DATAPILOT_API_KEY and DATAPILOT_MODEL")
            if not self.base_url.startswith(("https://", "http://localhost:", "http://127.0.0.1:")):
                raise ValueError("Use HTTPS for remote model endpoints")
        return self
