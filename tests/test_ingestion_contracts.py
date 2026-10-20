import pytest
from pydantic import ValidationError

from datapilot.ingestion.contracts import (
    ColumnOverride,
    ParsedColumn,
    ParsedTable,
    ParseError,
    ParseLimits,
    ParseOptions,
)


@pytest.mark.parametrize(
    "payload",
    [
        {"max_columns": 101},
        {"max_total_rows": 0},
        {"max_cell_chars": 9000},
        {"max_seconds": 0},
        {"max_file_bytes": "10"},
        {"extra": True},
    ],
)
def test_limits_reject_invalid_or_unbounded_values(payload):
    with pytest.raises(ValidationError):
        ParseLimits(**payload)


def test_input_options_and_overrides_are_closed_contracts():
    with pytest.raises(ValidationError):
        ParseOptions(delimiter="💣")
    with pytest.raises(ValidationError):
        ColumnOverride(table_id="table_1", column="id", normalized_name="a; DROP TABLE x")
    with pytest.raises(ValidationError):
        ColumnOverride(table_id="table_1", column="id", logical_type="SQL")
    with pytest.raises(ValidationError):
        ParseError(code="bad", message="x" * 257)


def test_parsed_rows_and_name_mapping_are_validated():
    col = ParsedColumn(position=1, original_name="客户编号", normalized_name="column_1")
    with pytest.raises(ValidationError):
        ParsedTable(
            table_id="table_1",
            source_name="CSV",
            columns=[col],
            rows=[["001", "002"]],
            source_rows=[2],
        )
    with pytest.raises(ValidationError):
        ParsedTable(
            table_id="table_1", source_name="CSV", columns=[col, col], rows=[], source_rows=[]
        )
