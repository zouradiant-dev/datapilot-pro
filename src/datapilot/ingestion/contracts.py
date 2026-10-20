"""Strict, bounded file/preview contracts. Confirmations are intent, never authorization."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PARSER_VERSION = "1.0"
LogicalType = Literal["TEXT", "INTEGER", "NUMERIC", "BOOLEAN", "DATE", "TIMESTAMP"]
HeaderMode = Literal["auto", "present", "absent"]
DateFormat = Literal["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"]
Name = Annotated[str, Field(min_length=1, max_length=63, pattern=r"^[a-z_][a-z0-9_]*$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Cell = Annotated[str, Field(max_length=8192)] | None


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class ParseLimits(DTO):
    max_file_bytes: int = Field(default=10 * 1024**2, ge=1, le=32 * 1024**2)
    max_sheets: int = Field(default=10, ge=1, le=32)
    max_columns: int = Field(default=100, ge=1, le=100)
    max_total_rows: int = Field(default=100_000, ge=1, le=100_000)
    max_cells: int = Field(default=500_000, ge=1, le=1_000_000)
    max_cell_chars: int = Field(default=8192, ge=1, le=8192)
    max_parsed_bytes: int = Field(default=32 * 1024**2, ge=1, le=64 * 1024**2)
    max_zip_entries: int = Field(default=512, ge=1, le=2048)
    max_uncompressed_bytes: int = Field(default=64 * 1024**2, ge=1, le=128 * 1024**2)
    max_entry_bytes: int = Field(default=32 * 1024**2, ge=1, le=64 * 1024**2)
    max_compression_ratio: int = Field(default=200, ge=1, le=1000)
    max_xml_elements: int = Field(default=2_000_000, ge=1, le=3_000_000)
    max_seconds: float = Field(default=30.0, gt=0, le=120)
    sample_size: int = Field(default=100, ge=1, le=1000)
    preview_rows: int = Field(default=10, ge=0, le=20)
    max_preview_bytes: int = Field(default=2 * 1024**2, ge=256, le=4 * 1024**2)
    max_issues: int = Field(default=1000, ge=1, le=2000)


class ParseOptions(DTO):
    encoding: (
        Literal[
            "utf-8",
            "utf-8-sig",
            "utf-16",
            "utf-16-le",
            "utf-16-be",
            "utf-32",
            "utf-32-le",
            "utf-32-be",
            "gb18030",
            "cp1252",
            "latin-1",
        ]
        | None
    ) = None
    delimiter: Literal[",", ";", "\t", "|"] | None = None
    header: HeaderMode = "auto"
    sheets: list[Annotated[str, Field(min_length=1, max_length=128)]] | None = Field(
        default=None, min_length=1, max_length=32
    )
    sheet_headers: dict[str, HeaderMode] = Field(default_factory=dict, max_length=32)


class ParseError(DTO):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=256)
    table_id: str | None = Field(default=None, max_length=63)
    row: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1, le=100)


class ParseFailure(Exception):
    def __init__(self, code: str, message: str, **location):
        self.error = ParseError(code=code, message=message, **location)
        super().__init__(message)


class Issue(DTO):
    code: str = Field(max_length=64)
    message: str = Field(max_length=256)
    column: str | None = Field(default=None, max_length=63)


class UploadFileInfo(DTO):
    filename: str = Field(min_length=1, max_length=255)
    file_format: Literal["csv", "xlsx"]
    size_bytes: int = Field(ge=1, le=32 * 1024**2)
    sha256: Digest
    encoding: str | None = Field(default=None, max_length=32)
    delimiter: str | None = Field(default=None, max_length=1)
    sheets: list[str] = Field(default_factory=list, max_length=32)


class ParsedColumn(DTO):
    position: int = Field(ge=1, le=100)
    original_name: str | None = Field(default=None, max_length=8192)
    normalized_name: Name


class ParsedTable(DTO):
    table_id: Name
    source_name: str = Field(min_length=1, max_length=255)
    columns: list[ParsedColumn] = Field(max_length=100)
    rows: list[list[Cell]] = Field(max_length=100_000)
    source_rows: list[Annotated[int, Field(ge=1)]] = Field(max_length=100_000)
    header_row: int | None = Field(default=None, ge=1)
    skipped_blank_rows: int = Field(default=0, ge=0)
    forced_text_columns: list[Name] = Field(default_factory=list, max_length=100)
    issues: list[Issue] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def shape(self):
        names = [c.normalized_name for c in self.columns]
        if len(names) != len(set(names)) or len(self.source_rows) != len(self.rows):
            raise ValueError("Inconsistent parsed table")
        if any(len(row) != len(names) for row in self.rows):
            raise ValueError("Ragged parsed rows")
        if any(n not in names for n in self.forced_text_columns):
            raise ValueError("Unknown forced-text column")
        return self


class ParsedDataset(DTO):
    upload: UploadFileInfo
    options: ParseOptions
    limits: ParseLimits
    parser_version: Literal["1.0"] = PARSER_VERSION
    tables: list[ParsedTable] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def resources(self):
        if len({t.table_id for t in self.tables}) != len(self.tables):
            raise ValueError("Duplicate table IDs")
        if len(self.tables) > self.limits.max_sheets:
            raise ValueError("Too many tables")
        if sum(len(t.rows) for t in self.tables) > self.limits.max_total_rows:
            raise ValueError("Too many parsed rows")
        if sum(len(row) for t in self.tables for row in t.rows) > self.limits.max_cells:
            raise ValueError("Too many parsed cells")
        if any(len(t.columns) > self.limits.max_columns for t in self.tables):
            raise ValueError("Too many parsed columns")
        return self


class ColumnProfile(DTO):
    column: ParsedColumn
    suggested_type: LogicalType
    sample_type: LogicalType
    confidence: float = Field(ge=0, le=1)
    requires_confirmation: bool
    null_count: int = Field(ge=0)
    distinct_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    examples: list[Annotated[str, Field(max_length=200)]] = Field(max_length=5)
    examples_truncated: bool
    precision: int | None = Field(default=None, ge=1, le=38)
    scale: int | None = Field(default=None, ge=0, le=18)
    minimum: str | None = Field(default=None, max_length=128)
    maximum: str | None = Field(default=None, max_length=128)
    outlier_count: int = Field(default=0, ge=0)
    issues: list[Issue] = Field(default_factory=list, max_length=32)


class TablePreview(DTO):
    table_id: Name
    source_name: str = Field(max_length=255)
    row_count: int = Field(ge=0, le=100_000)
    header_row: int | None = Field(default=None, ge=1)
    preview_source_rows: list[Annotated[int, Field(ge=1)]] = Field(max_length=20)
    columns: list[ColumnProfile] = Field(max_length=100)
    preview_rows: list[list[Cell]] = Field(max_length=20)
    preview_truncated: bool
    duplicate_rows: int = Field(ge=0)
    skipped_blank_rows: int = Field(ge=0)
    candidate_primary_keys: list[Name] = Field(max_length=10)
    issues: list[Issue] = Field(max_length=2000)


class RelationCandidate(DTO):
    relation_id: str = Field(max_length=128)
    child_table: Name
    child_column: Name
    parent_table: Name
    parent_column: Name
    matched_distinct_values: int = Field(ge=1)
    basis: Literal["matching_name_and_full_value_subset"] = "matching_name_and_full_value_subset"
    requires_confirmation: Literal[True] = True


class SchemaProposal(DTO):
    upload: UploadFileInfo
    parser_version: Literal["1.0"] = PARSER_VERSION
    options: ParseOptions
    limits: ParseLimits
    parsed_content_sha256: Digest
    proposal_sha256: Digest
    tables: list[TablePreview] = Field(min_length=1, max_length=32)
    candidate_relations: list[RelationCandidate] = Field(max_length=50)
    relation_candidates_truncated: bool = False


class ColumnOverride(DTO):
    table_id: Name
    column: Name
    logical_type: LogicalType | None = None
    normalized_name: Name | None = None
    date_format: DateFormat | None = None


class ConfirmedColumn(DTO):
    original_name: str | None = Field(max_length=8192)
    source_column: Name
    normalized_name: Name
    logical_type: LogicalType
    date_format: DateFormat | None = None
    precision: int | None = Field(default=None, ge=1, le=38)
    scale: int | None = Field(default=None, ge=0, le=18)


class ConfirmedTable(DTO):
    table_id: Name
    columns: list[ConfirmedColumn] = Field(max_length=100)
    primary_key: list[Name] = Field(default_factory=list, max_length=10)


class ConfirmationOverrides(DTO):
    columns: list[ColumnOverride] = Field(default_factory=list, max_length=1000)
    primary_keys: dict[str, list[Name]] = Field(default_factory=dict, max_length=32)
    relation_ids: list[str] = Field(default_factory=list, max_length=50)


class SchemaConfirmation(DTO):
    source_sha256: Digest
    parsed_content_sha256: Digest
    proposal_sha256: Digest
    parser_version: Literal["1.0"] = PARSER_VERSION
    options: ParseOptions
    limits: ParseLimits
    reviewed: Literal[True]
    tables: list[ConfirmedTable] = Field(min_length=1, max_length=32)
    accepted_relations: list[RelationCandidate] = Field(max_length=50)
    confirmation_sha256: Digest
