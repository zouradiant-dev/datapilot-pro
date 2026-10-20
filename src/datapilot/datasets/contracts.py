"""Bounded dataset identities. A scope is created by the trusted host, never a tool argument."""

import re
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from datapilot.contracts import QueryResult
from datapilot.ingestion.contracts import DTO, Digest, LogicalType, Name

DatasetId = Annotated[
    str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
]
Version = Annotated[int, Field(ge=1, le=1_000_000)]


class DatasetBinding(DTO):
    dataset_id: DatasetId
    # None means resolve the current version once, then pin it for this MCP session.
    version: Version | None = None


class DatasetScope(DTO):
    bindings: list[DatasetBinding] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_datasets(self):
        if len({b.dataset_id for b in self.bindings}) != len(self.bindings):
            raise ValueError("A session binds each dataset at most once")
        return self


class ImportRequest(DTO):
    name: str = Field(min_length=1, max_length=128)
    dataset_id: DatasetId | None = None

    @field_validator("name")
    @classmethod
    def display_name(cls, value):
        if not re.fullmatch(r"[\w .-]+", value) or value.strip() != value or value in {".", ".."}:
            raise ValueError("Use a plain display name, not a path or SQL expression")
        return value


class ImportResult(DTO):
    status: Literal["ready"] = "ready"
    dataset_id: DatasetId
    version: Version
    source_sha256: Digest
    confirmation_sha256: Digest
    reused: bool
    row_count: int = Field(ge=0, le=100_000)


class DatasetSummary(DTO):
    dataset_id: DatasetId
    name: str = Field(max_length=128)
    version: Version
    source_sha256: Digest
    row_count: int = Field(ge=0, le=100_000)


class DatasetListing(DTO):
    datasets: list[DatasetSummary] = Field(max_length=100)


class DatasetColumn(DTO):
    position: int = Field(ge=1, le=100)
    source_column: Name
    original_name: str | None = Field(max_length=8192)
    normalized_name: Name
    logical_type: LogicalType
    sql_type: str = Field(max_length=64)


class DatasetTable(DTO):
    table_id: Name
    source_name: str = Field(max_length=255)
    physical_name: Name
    row_count: int = Field(ge=0, le=100_000)
    columns: list[DatasetColumn] = Field(min_length=1, max_length=100)
    primary_key: list[Name] = Field(max_length=10)


class DatasetSchema(DatasetSummary):
    physical_schema: Literal["uploads"] = "uploads"
    tables: list[DatasetTable] = Field(min_length=1, max_length=32)


class DatasetQueryResult(DTO):
    dataset_id: DatasetId
    version: Version
    source_sha256: Digest
    query_sha256: Digest
    result_sha256: Digest
    result: QueryResult
