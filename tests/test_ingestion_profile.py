from decimal import Decimal

import pytest

from datapilot.ingestion.confirmation import confirm_file, confirm_schema
from datapilot.ingestion.contracts import (
    ColumnOverride,
    ConfirmationOverrides,
    ParseFailure,
    ParseLimits,
    ParseOptions,
)
from datapilot.ingestion.parser import parse_bytes
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.types import convert_value


def dataset(text, **kwargs):
    return parse_bytes(
        text.encode("utf-8"), "synthetic.csv", options=ParseOptions(header="present"), **kwargs
    )


def test_leading_zero_identifiers_and_exact_decimal_money():
    parsed = dataset("customer_id,amount\n001,1234567890.123456789\n002,0.000000001\n")
    proposal = propose_schema(parsed)
    identifier, amount = proposal.tables[0].columns
    assert identifier.suggested_type == "TEXT" and "PROTECTED_IDENTIFIER" in {
        i.code for i in identifier.issues
    }
    assert amount.suggested_type == "NUMERIC" and amount.precision == 19 and amount.scale == 9
    assert convert_value(parsed.tables[0].rows[0][1], "NUMERIC") == Decimal("1234567890.123456789")
    assert (
        confirm_schema(parsed, proposal, reviewed=True).tables[0].columns[0].logical_type == "TEXT"
    )


def test_sample_inference_is_overruled_by_full_column_validation():
    parsed = dataset("quantity\n1\n2\n3\nnot-a-number\n", limits=ParseLimits(sample_size=2))
    profile = propose_schema(parsed).tables[0].columns[0]
    assert profile.sample_type == "INTEGER" and profile.suggested_type == "TEXT"
    assert {i.code for i in profile.issues} >= {"SAMPLE_TYPE_MISMATCH", "MIXED_TYPES"}
    assert len(parsed.tables[0].rows) == 4
    with pytest.raises(ParseFailure) as err:
        confirm_schema(
            parsed,
            propose_schema(parsed),
            reviewed=True,
            overrides=ConfirmationOverrides(
                columns=[
                    ColumnOverride(table_id="table_1", column="quantity", logical_type="INTEGER")
                ]
            ),
        )
    assert err.value.error.code == "OVERRIDE_DATA_INVALID"


@pytest.mark.parametrize(
    "value,code",
    [
        ("NaN", "NONFINITE_AS_TEXT"),
        ("Infinity", "NONFINITE_AS_TEXT"),
        ("1e100000", "NUMERIC_RANGE_OR_PRECISION"),
        ("0.0000000000000000001", "NUMERIC_RANGE_OR_PRECISION"),
        ("2025-02-30", "INVALID_OR_MIXED_DATE"),
        ("01/02/2025", "AMBIGUOUS_DATE"),
        ("12%", "UNIT_OR_LOCALE_REQUIRES_CONFIRMATION"),
    ],
)
def test_uncertain_scalar_types_remain_text_with_reason(value, code):
    proposal = propose_schema(dataset("value\n" + value + "\n"))
    profile = proposal.tables[0].columns[0]
    assert profile.suggested_type == "TEXT" and profile.requires_confirmation
    assert code in {i.code for i in profile.issues}


def test_null_duplicate_and_outlier_reports_do_not_filter_rows():
    parsed = dataset("id,amount,empty\n1,1,\n2,1,\n3,1,\n4,1,\n5,1000,\n5,1000,\n")
    table = propose_schema(parsed).tables[0]
    assert table.row_count == 6 and table.duplicate_rows == 1
    assert table.columns[2].null_count == 6 and table.columns[2].distinct_count == 0
    assert table.columns[1].duplicate_count == 4
    assert table.columns[1].minimum == "1" and table.columns[1].maximum == "1000"
    assert len(parsed.tables[0].rows) == 6


def test_iqr_outliers_are_reported_without_mutating_values():
    table = propose_schema(dataset("n\n1\n2\n3\n4\n5\n1000\n")).tables[0]
    assert table.columns[0].outlier_count == 1 and table.row_count == 6


def test_ambiguous_dates_can_only_be_converted_with_explicit_format():
    parsed = dataset("date\n01/02/2025\n13/02/2025\n")
    proposal = propose_schema(parsed)
    assert proposal.tables[0].columns[0].suggested_type == "TEXT"
    changes = ConfirmationOverrides(
        columns=[
            ColumnOverride(
                table_id="table_1", column="date", logical_type="DATE", date_format="DD/MM/YYYY"
            )
        ]
    )
    result = confirm_schema(parsed, proposal, reviewed=True, overrides=changes)
    assert result.tables[0].columns[0].date_format == "DD/MM/YYYY"
    assert str(convert_value("01/02/2025", "DATE", "DD/MM/YYYY")) == "2025-02-01"
    changes.columns[0].date_format = "MM/DD/YYYY"
    with pytest.raises(ParseFailure):
        confirm_schema(parsed, proposal, reviewed=True, overrides=changes)


def test_proposal_hashes_are_reproducible_and_preview_is_explicitly_clipped():
    parsed = dataset(
        "id,note\n001," + "x" * 300 + "\n002,short\n", limits=ParseLimits(preview_rows=1)
    )
    first = propose_schema(parsed)
    assert first == propose_schema(parsed)
    assert first.tables[0].preview_truncated
    assert first.tables[0].columns[1].examples_truncated
    assert len(first.tables[0].preview_rows[0][1]) == 200
    assert len(parsed.tables[0].rows[0][1]) == 300
    assert confirm_schema(parsed, first, reviewed=True) == confirm_schema(
        parsed, first, reviewed=True
    )


def test_preview_output_budget_is_enforced():
    with pytest.raises(ParseFailure) as err:
        propose_schema(dataset("id,note\n001,abc\n", limits=ParseLimits(max_preview_bytes=256)))
    assert err.value.error.code == "PREVIEW_SIZE_LIMIT"


def test_review_header_and_source_binding_are_not_optional(tmp_path):
    parsed = dataset("id\n001\n")
    proposal = propose_schema(parsed)
    with pytest.raises(ParseFailure) as err:
        confirm_schema(parsed, proposal, reviewed=False)
    assert err.value.error.code == "REVIEW_REQUIRED"
    unclear = parse_bytes(b"Alice,Paris\nBob,Boston\n", "synthetic.csv")
    with pytest.raises(ParseFailure) as err:
        confirm_schema(unclear, propose_schema(unclear), reviewed=True)
    assert err.value.error.code == "HEADER_CONFIRMATION_REQUIRED"
    file = tmp_path / "synthetic.csv"
    file.write_text("id\n002\n", encoding="utf-8")
    with pytest.raises(ParseFailure) as err:
        confirm_file(file, proposal, reviewed=True)
    assert err.value.error.code == "PROPOSAL_STALE"
    proposal.tables[0].columns[0].suggested_type = "INTEGER"
    with pytest.raises(ParseFailure) as err:
        confirm_schema(parsed, proposal, reviewed=True)
    assert err.value.error.code == "PROPOSAL_STALE"


def test_user_overrides_names_types_and_primary_keys_are_revalidated():
    parsed = dataset("id,amount\n1,12.50\n2,20.75\n")
    proposal = propose_schema(parsed)
    result = confirm_schema(
        parsed,
        proposal,
        reviewed=True,
        overrides=ConfirmationOverrides(
            columns=[
                ColumnOverride(
                    table_id="table_1",
                    column="id",
                    normalized_name="customer_id",
                    logical_type="TEXT",
                )
            ],
            primary_keys={"table_1": ["id"]},
        ),
    )
    assert result.tables[0].primary_key == ["customer_id"]
    assert result.tables[0].columns[0].source_column == "id"
    assert result.tables[0].columns[0].logical_type == "TEXT"
    for changes in [
        ConfirmationOverrides(columns=[ColumnOverride(table_id="table_1", column="missing")]),
        ConfirmationOverrides(
            columns=[ColumnOverride(table_id="table_1", column="id", normalized_name="amount")]
        ),
        ConfirmationOverrides(
            columns=[ColumnOverride(table_id="table_1", column="id", normalized_name="select")]
        ),
        ConfirmationOverrides(primary_keys={"table_1": ["id", "id"]}),
        ConfirmationOverrides(relation_ids=["invented"]),
    ]:
        with pytest.raises(ParseFailure):
            confirm_schema(parsed, proposal, reviewed=True, overrides=changes)


def test_key_validation_uses_all_rows_and_numeric_types():
    parsed = dataset("id\n1\n1\n")
    proposal = propose_schema(parsed)
    assert not proposal.tables[0].candidate_primary_keys
    with pytest.raises(ParseFailure) as err:
        confirm_schema(
            parsed,
            proposal,
            reviewed=True,
            overrides=ConfirmationOverrides(primary_keys={"table_1": ["id"]}),
        )
    assert err.value.error.code == "KEY_INVALID"


def test_identifiers_cannot_be_silently_coerced_to_lossy_numbers():
    parsed = dataset("id\n001\n002\n")
    with pytest.raises(ParseFailure) as err:
        confirm_schema(
            parsed,
            propose_schema(parsed),
            reviewed=True,
            overrides=ConfirmationOverrides(
                columns=[ColumnOverride(table_id="table_1", column="id", logical_type="INTEGER")]
            ),
        )
    assert err.value.error.code == "OVERRIDE_DATA_INVALID"


def test_iso_timestamp_retains_timezone_ambiguity():
    parsed = dataset("time\n2025-01-01T12:00:00\n2025-01-02T12:00:00\n")
    profile = propose_schema(parsed).tables[0].columns[0]
    assert profile.suggested_type == "TIMESTAMP"
    assert "TIMEZONE_UNSPECIFIED" in {i.code for i in profile.issues}
    mixed = dataset("time\n2025-01-01T12:00:00Z\n2025-01-02T12:00:00\n")
    assert propose_schema(mixed).tables[0].columns[0].suggested_type == "TEXT"


def test_empty_tables_can_be_previewed_but_not_confirmed():
    parsed = dataset("id,amount\n")
    proposal = propose_schema(parsed)
    assert proposal.tables[0].row_count == 0
    with pytest.raises(ParseFailure) as err:
        confirm_schema(parsed, proposal, reviewed=True)
    assert err.value.error.code == "EMPTY_TABLE_CONFIRMATION"
