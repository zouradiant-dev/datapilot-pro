"""Bounded CSV/XLSX reading. Raw scalars stay text; nothing is evaluated or imported."""

import codecs
import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from datapilot.ingestion.common import Guard, read_file
from datapilot.ingestion.contracts import (
    Issue,
    ParsedColumn,
    ParsedDataset,
    ParsedTable,
    ParseFailure,
    ParseLimits,
    ParseOptions,
    UploadFileInfo,
)

RESERVED = {"select", "from", "where", "table", "user", "order", "group", "limit", "null"}


@dataclass
class RawSheet:
    name: str
    records: list[tuple[int, list[str | None]]]
    forced_text: set[int] = field(default_factory=set)
    annotations: dict[tuple[str, int], int] = field(default_factory=dict)
    hidden: bool = False


def normalize_name(original: str | None, position: int, used: set[str]) -> str:
    text = unicodedata.normalize("NFKC", original or "").lower()
    base = re.sub(r"[^a-z0-9_]+", "_", text).strip("_") or f"column_{position}"
    if base[0].isdigit() or base in RESERVED:
        base = "column_" + base
    base = base[:55]
    name, counter = base, 1
    while name in used:
        counter += 1
        name = f"{base}_{counter}"
    used.add(name)
    return name


def _scalar(value: str | None) -> bool:
    return bool(
        value
        and (
            re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value)
            or re.match(r"^\d{4}-\d{2}-\d{2}", value)
            or value.lower() in {"true", "false"}
        )
    )


def _table(raw: RawSheet, index: int, options: ParseOptions, limits: ParseLimits) -> ParsedTable:
    nonblank = [(n, r) for n, r in raw.records if any(v not in (None, "") for v in r)]
    blank = len(raw.records) - len(nonblank)
    issues: list[Issue] = []
    if blank:
        issues.append(
            Issue(code="BLANK_ROWS_SKIPPED", message=f"Skipped {blank} entirely blank rows")
        )
    if raw.hidden:
        issues.append(Issue(code="HIDDEN_SHEET", message="This worksheet is hidden in the source"))
    mode = options.sheet_headers.get(raw.name, options.header)
    header = mode == "present"
    if mode == "auto" and nonblank:
        first = nonblank[0][1]
        later = [r for _, r in nonblank[1:21]]
        labels = all(v in (None, "") or not _scalar(v) for v in first)
        header = bool(labels and later and any(_scalar(v) for row in later for v in row))
        if header:
            issues.append(
                Issue(
                    code="HEADER_INFERRED",
                    message="First row proposed as header; review names or reparse with absent.",
                )
            )
        if labels and not header:
            issues.append(
                Issue(
                    code="HEADER_AMBIGUOUS",
                    message="Header uncertain; first row kept. Reparse with present/absent.",
                )
            )
    width = len(nonblank[0][1]) if nonblank else 0
    if width > limits.max_columns:
        raise ParseFailure("COLUMN_LIMIT", "Column count exceeds the configured limit")
    if any(len(row) != width for _, row in nonblank):
        raise ParseFailure(
            "RAGGED_ROWS", "Record widths differ; select the correct delimiter/header"
        )
    names = nonblank[0][1] if header and nonblank else [None] * width
    used: set[str] = set()
    columns = [
        ParsedColumn(
            position=i + 1, original_name=name, normalized_name=normalize_name(name, i + 1, used)
        )
        for i, name in enumerate(names)
    ]
    actual_names = [n for n in names if n not in (None, "")]
    if header and len(actual_names) != len(set(actual_names)):
        issues.append(
            Issue(code="DUPLICATE_HEADERS", message="Duplicate headers received unique names")
        )
    if header and any(n in (None, "") for n in names):
        issues.append(
            Issue(code="EMPTY_HEADERS", message="Empty headers received positional names")
        )
    records = nonblank[1:] if header else nonblank
    if not records:
        issues.append(Issue(code="NO_DATA_ROWS", message="No nonblank data rows in this table"))
    for (code, column), count in sorted(raw.annotations.items()):
        issues.append(
            Issue(
                code=code,
                column=columns[column - 1].normalized_name,
                message=f"{count} source cells flagged; raw values were not evaluated",
            )
        )
    if len(issues) > limits.max_issues:
        raise ParseFailure("ISSUE_LIMIT", "Quality diagnostics exceed the configured limit")
    return ParsedTable(
        table_id=f"table_{index}",
        source_name=raw.name,
        columns=columns,
        rows=[r for _, r in records],
        source_rows=[n for n, _ in records],
        header_row=nonblank[0][0] if header and nonblank else None,
        skipped_blank_rows=blank,
        forced_text_columns=[columns[i - 1].normalized_name for i in sorted(raw.forced_text)],
        issues=issues,
    )


def _decode(data: bytes, options: ParseOptions) -> tuple[str, str]:
    detected = None
    for bom, encoding in (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if data.startswith(bom):
            detected = encoding
            break
    if detected and options.encoding and not options.encoding.startswith(detected.split("-sig")[0]):
        raise ParseFailure(
            "ENCODING_CONFLICT", "Explicit encoding conflicts with the byte-order mark"
        )
    for bom, opposite in (
        (codecs.BOM_UTF16_LE, "utf-16-be"),
        (codecs.BOM_UTF16_BE, "utf-16-le"),
        (codecs.BOM_UTF32_LE, "utf-32-be"),
        (codecs.BOM_UTF32_BE, "utf-32-le"),
    ):
        if data.startswith(bom) and options.encoding == opposite:
            raise ParseFailure("ENCODING_CONFLICT", "Explicit byte order conflicts with the BOM")
    encoding = detected or options.encoding or "utf-8"
    try:
        text = data.decode(encoding, errors="strict")
    except UnicodeError as exc:
        raise ParseFailure(
            "ENCODING_REQUIRED", "Cannot decode losslessly; select an explicit encoding"
        ) from exc
    if any(ord(c) < 32 and c not in "\t\r\n" for c in text):
        raise ParseFailure("INVALID_TEXT", "CSV contains binary/control characters")
    return text, encoding


def _csv(data: bytes, name: str, options: ParseOptions, guard: Guard):
    if options.sheets or options.sheet_headers:
        raise ParseFailure("INVALID_OPTIONS", "Worksheet selectors only apply to XLSX")
    text, encoding = _decode(data, options)
    delimiter = options.delimiter
    if not delimiter:
        try:
            delimiter = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|").delimiter
        except csv.Error as exc:
            if any(c in text for c in ",;\t|"):
                raise ParseFailure(
                    "DELIMITER_REQUIRED", "Delimiter is uncertain; select one explicitly"
                ) from exc
            delimiter = ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    records = []
    previous_line = 0
    try:
        for row in reader:
            guard.row(row)
            records.append((previous_line + 1, row))
            previous_line = reader.line_num
    except csv.Error as exc:
        raise ParseFailure("CSV_MALFORMED", "CSV quoting/field size is invalid") from exc
    return [RawSheet(name, records)], encoding, delimiter


def parse_bytes(
    data: bytes,
    filename: str,
    *,
    options: ParseOptions | None = None,
    limits: ParseLimits | None = None,
) -> ParsedDataset:
    options, limits = options or ParseOptions(), limits or ParseLimits()
    if not isinstance(data, bytes):
        raise ParseFailure("FILE_INVALID", "File content must be bytes")
    if (
        not filename
        or len(filename) > 255
        or any(c in filename for c in "/\\:\0")
        or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in filename)
    ):
        raise ParseFailure("FILENAME_INVALID", "Use a display filename, without a path")
    if not data:
        raise ParseFailure("EMPTY_FILE", "The selected file is empty")
    if len(data) > limits.max_file_bytes:
        raise ParseFailure("FILE_SIZE_LIMIT", "File exceeds the configured byte limit")
    kind = Path(filename).suffix.lower().lstrip(".")
    if kind not in {"csv", "xlsx"}:
        raise ParseFailure("FORMAT_UNSUPPORTED", "Only CSV and non-macro XLSX files are supported")
    guard = Guard(limits)
    encoding = delimiter = None
    sheets: list[str] = []
    if kind == "csv":
        if data.startswith((b"PK\x03\x04", b"\xd0\xcf\x11\xe0")):
            raise ParseFailure("FORMAT_MISMATCH", "CSV signature indicates a binary container")
        raw, encoding, delimiter = _csv(data, Path(filename).stem, options, guard)
    else:
        from datapilot.ingestion.xlsx import read_xlsx

        if options.encoding or options.delimiter:
            raise ParseFailure("INVALID_OPTIONS", "CSV encoding/delimiter cannot apply to XLSX")
        raw, sheets = read_xlsx(data, options, guard)
    if not any(sheet.records for sheet in raw):
        raise ParseFailure("EMPTY_DATA", "No worksheet or CSV records were found")
    tables = [_table(sheet, i + 1, options, limits) for i, sheet in enumerate(raw)]
    if sum(len(t.rows) for t in tables) > limits.max_total_rows:
        raise ParseFailure("ROW_LIMIT", "Data rows exceed the configured total limit")
    guard.check()
    return ParsedDataset(
        upload=UploadFileInfo(
            filename=filename,
            file_format=kind,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            encoding=encoding,
            delimiter=delimiter,
            sheets=sheets,
        ),
        options=options,
        limits=limits,
        tables=tables,
    )


def parse_file(
    path: str | Path, *, options: ParseOptions | None = None, limits: ParseLimits | None = None
) -> ParsedDataset:
    limits = limits or ParseLimits()
    path = Path(path)
    return parse_bytes(
        read_file(path, limits.max_file_bytes), path.name, options=options, limits=limits
    )
