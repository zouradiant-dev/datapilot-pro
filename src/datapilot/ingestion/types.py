"""Conservative scalar semantics. No floating-point money, locale guessing or evaluation."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from datapilot.ingestion.contracts import DateFormat, LogicalType

NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?", re.ASCII)
INTEGER = re.compile(r"[+-]?\d+", re.ASCII)
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
ISO_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", re.ASCII
)


def leading_zero(value: str) -> bool:
    return bool(re.match(r"^[+-]?0\d+(?:\.|[eE]|$)", value, re.ASCII))


def decimal_value(value: str) -> Decimal:
    if not NUMBER.fullmatch(value) or leading_zero(value):
        raise ValueError("Not an unambiguous number")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid numeric value") from exc
    _, digits, exponent = number.as_tuple()
    if not number.is_finite() or not isinstance(exponent, int):
        raise ValueError("Nonfinite numeric value")
    scale = max(-exponent, 0)
    precision = max(len(digits) + max(exponent, 0), scale, 1)
    if precision > 38 or scale > 18:
        raise ValueError("Number exceeds supported NUMERIC(38,18) envelope")
    return number


def numeric_shape(values: list[Decimal]) -> tuple[int, int]:
    scale = max((max(-n.as_tuple().exponent, 0) for n in values), default=0)
    integer = max(
        (max(len(n.as_tuple().digits) + n.as_tuple().exponent, 0) for n in values), default=1
    )
    precision = max(integer + scale, 1)
    if precision > 38 or scale > 18:
        raise ValueError("Combined column precision/scale exceeds supported limits")
    return precision, scale


def date_value(value: str, date_format: DateFormat = "YYYY-MM-DD") -> date:
    if date_format == "YYYY-MM-DD":
        if not ISO_DATE.fullmatch(value):
            raise ValueError("ISO date required")
        return date.fromisoformat(value)
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", value, re.ASCII):
        raise ValueError("Explicit slash-date format required")
    a, b, year = (int(part) for part in value.split("/"))
    return date(year, b, a) if date_format == "DD/MM/YYYY" else date(year, a, b)


def convert_value(
    value: str | None, logical_type: LogicalType, date_format: DateFormat | None = None
) -> str | int | Decimal | bool | date | datetime | None:
    if value in (None, ""):
        return None
    if logical_type == "TEXT":
        return value
    if logical_type == "NUMERIC":
        return decimal_value(value)
    if logical_type == "INTEGER":
        if not INTEGER.fullmatch(value) or leading_zero(value) or len(value.lstrip("+-")) > 19:
            raise ValueError("Lossless integer conversion required")
        number = int(value)
        if not -(2**63) <= number < 2**63:
            raise ValueError("Integer is outside the BIGINT range")
        return number
    if logical_type == "BOOLEAN":
        if value.lower() not in {"true", "false"}:
            raise ValueError("Use explicit true/false boolean values")
        return value.lower() == "true"
    if logical_type == "DATE":
        return date_value(value, date_format or "YYYY-MM-DD")
    if not ISO_TIMESTAMP.fullmatch(value):
        raise ValueError("ISO timestamp required; timezone is never guessed")
    return datetime.fromisoformat(value)


def infer(values: list[str]) -> tuple[LogicalType, list[str], int | None, int | None]:
    if not values:
        return "TEXT", ["ALL_NULL"], None, None
    if any(leading_zero(v) for v in values):
        return "TEXT", ["PROTECTED_IDENTIFIER"], None, None
    for kind in ("INTEGER", "NUMERIC", "BOOLEAN", "DATE", "TIMESTAMP"):
        try:
            converted = [convert_value(v, kind) for v in values]
            precision = scale = None
            if kind == "NUMERIC":
                precision, scale = numeric_shape(converted)
            notes = []
            if kind == "TIMESTAMP":
                awareness = {v.tzinfo is not None for v in converted}
                if False in awareness:
                    notes.append("TIMEZONE_UNSPECIFIED")
                if len(awareness) > 1:
                    return "TEXT", ["MIXED_TIMEZONES"], None, None
            return kind, notes, precision, scale
        except ValueError:
            pass
    notes = []
    if any(re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", v) for v in values):
        notes.append("AMBIGUOUS_DATE")
    if any(ISO_DATE.fullmatch(v) for v in values):
        notes.append("INVALID_OR_MIXED_DATE")
    numeric_count = sum(bool(NUMBER.fullmatch(v)) for v in values)
    if numeric_count == len(values):
        notes.append("NUMERIC_RANGE_OR_PRECISION")
    elif numeric_count:
        notes.append("MIXED_TYPES")
    if any(v.lower() in {"nan", "inf", "infinity", "-inf", "+inf"} for v in values):
        notes.append("NONFINITE_AS_TEXT")
    if any(re.search(r"[%¥￥$€]|\d,\d", v) for v in values):
        notes.append("UNIT_OR_LOCALE_REQUIRES_CONFIRMATION")
    return "TEXT", notes or ["TEXT_UNCONFIRMED"], None, None
