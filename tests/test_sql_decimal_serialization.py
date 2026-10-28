"""Public synthetic NUMERIC boundary cases; no sealed inputs or model calls."""

from decimal import Decimal, localcontext

import pytest

from datapilot.contracts import AgentFailure
from datapilot.semantics.recipes import scalar
from datapilot.tools import sql


def test_scaled_zero_roundtrips_through_existing_strict_parser():
    value = Decimal("0E-20")
    text = sql._serialize_cell(value)
    assert text == "0.00000000000000000000"
    assert scalar(text) == value


@pytest.mark.parametrize(
    "value",
    [
        "0",
        "0.00",
        "-0E-20",
        "0E+50",
        "1.2300",
        "-12.3400",
        "1.2345E+5",
        "1E-78",
        "-1E-77",
        "1E+79",
        "-1E+78",
        "12345678901234567890123456789012345678901234567890123456789012345678901234567890",
        "0.0000000000000000001234567890123456789012345678901234567890",
    ],
)
def test_finite_numeric_preserves_precision_and_fixed_point(value):
    number = Decimal(value)
    with localcontext() as context:
        context.prec = 2  # Formatting must not use context precision to round the coefficient.
        text = sql._serialize_cell(number)
    assert text == format(number, "f")
    assert len(text) <= 80 and "e" not in text.lower()
    assert scalar(text) == number


@pytest.mark.parametrize("value", ["NaN", "sNaN", "-NaN123", "Infinity", "-Infinity"])
def test_nonfinite_numeric_is_a_controlled_rejection(value):
    with pytest.raises(AgentFailure) as caught:
        sql._serialize_cell(Decimal(value))
    assert caught.value.error.code == "VERIFICATION_ERROR"


@pytest.mark.parametrize(
    "value",
    [
        "1E+1000000",
        "1E-1000000",
        "0E+1000000",
        "0E-1000000",
        "1E+80",
        "1E-79",
        "-1E+79",
        "-1E-78",
        "9" * 81,
        "9" * 80 + ".0",
    ],
)
def test_oversized_numeric_is_rejected_before_fixed_point_expansion(value, monkeypatch):
    def forbidden_format(*args, **kwargs):
        pytest.fail("Oversized Decimal must be rejected before allocating fixed-point output")

    monkeypatch.setattr(sql, "format", forbidden_format, raising=False)
    with pytest.raises(AgentFailure) as caught:
        sql._serialize_cell(Decimal(value))
    assert caught.value.error.code == "RESULT_TOO_LARGE"


def test_text_quota_and_unsupported_cells_still_fail_closed():
    assert sql._serialize_cell("x" * 4096) == "x" * 4096
    with pytest.raises(AgentFailure) as caught:
        sql._serialize_cell("x" * 4097)
    assert caught.value.error.code == "RESULT_TOO_LARGE"
    with pytest.raises(AgentFailure):
        sql._serialize_cell(object())
    for untrusted in ("0E-20", "NaN", "1" * 81, 0.0):
        with pytest.raises(ValueError):
            scalar(untrusted)  # No widening of the P3 parser for model/text/float input.


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_mcp_numeric_text_matches_existing_parser(pg_settings):
    from datapilot.runtime.mcp_client import database_session

    async with database_session(pg_settings) as tool:
        for value in ("0E-20", "0", "12.3400", "1E-78", "9" * 70):
            result = await tool.execute(f"SELECT CAST('{value}' AS DECIMAL) AS value")
            assert result.row_count == 1 and not result.truncated
            text = result.rows[0][0]
            assert len(text) <= 80 and "e" not in text.lower()
            assert scalar(text) == Decimal(value)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_mcp_rejects_nonfinite_and_expansion(pg_settings):
    from datapilot.runtime.mcp_client import database_session

    async with database_session(pg_settings) as tool:
        for value, code in (
            ("NaN", "VERIFICATION_ERROR"),
            ("Infinity", "VERIFICATION_ERROR"),
            ("1E+1000", "RESULT_TOO_LARGE"),
            ("1E-1000", "RESULT_TOO_LARGE"),
        ):
            with pytest.raises(AgentFailure) as caught:
                await tool.execute(f"SELECT CAST('{value}' AS DECIMAL) AS value")
            assert caught.value.error.code == code
