"""OOXML preflight before openpyxl; exact numeric lexemes survive float decoding."""

import io
import posixpath
import re
import struct
import zipfile
import zlib
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import PurePosixPath
from xml.etree.ElementTree import ParseError as XMLParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import iterparse
from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string
from openpyxl.utils.datetime import CALENDAR_WINDOWS_1900
from openpyxl.utils.exceptions import InvalidFileException

from datapilot.ingestion.common import Guard
from datapilot.ingestion.contracts import ParseFailure, ParseOptions
from datapilot.ingestion.parser import RawSheet


def _tag(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _directory_limit(data: bytes, guard: Guard) -> None:
    """Bound central-directory records before ZipFile allocates one ZipInfo per entry."""
    end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    if end < 0 or len(data) - end < 22:
        raise ParseFailure("XLSX_INVALID", "Missing ZIP end record")
    _, disk, start_disk, local_count, declared, size, offset, comment = struct.unpack_from(
        "<4s4H2LH", data, end
    )
    if declared > guard.limits.max_zip_entries:
        raise ParseFailure("ZIP_ENTRY_COUNT_LIMIT", "Too many declared ZIP entries")
    if (
        disk
        or start_disk
        or local_count != declared
        or end + 22 + comment != len(data)
        or offset + size != end
        or offset == 0xFFFFFFFF
        or size == 0xFFFFFFFF
    ):
        raise ParseFailure("XLSX_INVALID", "Multi-volume, ZIP64 or inconsistent ZIP directory")
    cursor, count = offset, 0
    while cursor < end:
        guard.check()
        if cursor + 46 > end or data[cursor : cursor + 4] != b"PK\x01\x02":
            raise ParseFailure("XLSX_INVALID", "Invalid ZIP central-directory entry")
        name_len, extra_len, comment_len = struct.unpack_from("<3H", data, cursor + 28)
        cursor += 46 + name_len + extra_len + comment_len
        count += 1
        if count > guard.limits.max_zip_entries:
            raise ParseFailure("ZIP_ENTRY_COUNT_LIMIT", "Too many actual ZIP entries")
        if count > declared or cursor > end:
            raise ParseFailure("XLSX_INVALID", "ZIP directory count/length mismatch")
    if count != declared:
        raise ParseFailure("XLSX_INVALID", "ZIP directory count mismatch")


class _BoundedStream:
    def __init__(self, stream, guard: Guard):
        self.stream, self.guard, self.count = stream, guard, 0

    def read(self, size=-1):
        self.guard.check()
        data = self.stream.read(min(size if size >= 0 else 65536, 65536))
        self.count += len(data)
        if self.count > self.guard.limits.max_entry_bytes:
            raise ParseFailure("ZIP_ENTRY_LIMIT", "A decompressed ZIP entry exceeds its byte limit")
        return data


def _preflight(archive: zipfile.ZipFile, guard: Guard):
    limits = guard.limits
    entries = archive.infolist()
    if len(entries) > limits.max_zip_entries:
        raise ParseFailure("ZIP_ENTRY_COUNT_LIMIT", "Too many ZIP entries")
    seen: set[str] = set()
    total = 0
    for entry in entries:
        guard.check()
        name = entry.filename
        lower = name.casefold()
        parts = PurePosixPath(name).parts
        if (
            name.startswith("/")
            or "\\" in name
            or ":" in name
            or ".." in parts
            or lower in seen
            or PurePosixPath(name).as_posix() != name.rstrip("/")
        ):
            raise ParseFailure(
                "ZIP_PATH_INVALID", "ZIP contains an unsafe or duplicate member name"
            )
        seen.add(lower)
        total += entry.file_size
        if entry.flag_bits & 1 or entry.compress_type not in {
            zipfile.ZIP_STORED,
            zipfile.ZIP_DEFLATED,
        }:
            raise ParseFailure("ZIP_UNSUPPORTED", "Encrypted or unsupported ZIP compression")
        if entry.file_size > limits.max_entry_bytes:
            raise ParseFailure("ZIP_ENTRY_LIMIT", "ZIP entry exceeds its uncompressed byte limit")
        if total > limits.max_uncompressed_bytes:
            raise ParseFailure("ZIP_SIZE_LIMIT", "ZIP exceeds the total uncompressed byte limit")
        if entry.file_size > max(entry.compress_size, 1) * limits.max_compression_ratio:
            raise ParseFailure(
                "ZIP_RATIO_LIMIT", "ZIP compression ratio exceeds the configured limit"
            )
        if any(
            token in lower
            for token in (
                "vbaproject",
                "activex/",
                "embeddings/",
                "externallinks/",
                "connections.xml",
                "querytables/",
                "macrosheets/",
            )
        ) or lower.endswith(".bin"):
            raise ParseFailure(
                "ACTIVE_CONTENT", "Macros, external data and embedded binaries are unsupported"
            )
    if not {"[content_types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"} <= seen:
        raise ParseFailure("FORMAT_MISMATCH", "ZIP is not a supported XLSX workbook")
    numeric: dict[str, dict[str, str]] = {}
    dimensions: dict[str, tuple[int, int]] = {}
    sheets: list[tuple[str, str]] = []
    relationships: dict[str, str] = {}
    element_count = cell_count = styles = shared_strings = actual_bytes = 0
    workbook_type = False
    for entry in entries:
        guard.check()
        name = entry.filename
        with archive.open(entry) as stream:
            bounded = _BoundedStream(stream, guard)
            if not name.lower().endswith((".xml", ".rels")):
                while bounded.read(65536):
                    pass
                actual_bytes += bounded.count
                continue
            worksheet = name.startswith("xl/worksheets/") and name.endswith(".xml")
            row_max = col_max = depth = 0
            current_row = last_row = last_column = 0
            seen_cells: set[str] = set()
            coordinate = cell_type = None
            values = {}
            for event, element in iterparse(
                bounded,
                events=("start", "end"),
                forbid_dtd=True,
                forbid_entities=True,
                forbid_external=True,
            ):
                guard.check()
                tag = _tag(element)
                if event == "start":
                    depth += 1
                    element_count += 1
                    if (
                        depth == 1
                        and worksheet
                        and element.tag
                        != ("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}worksheet")
                    ):
                        raise ParseFailure("XLSX_INVALID", "Unsupported worksheet XML namespace")
                    if depth > 64 or element_count > limits.max_xml_elements:
                        raise ParseFailure(
                            "XML_LIMIT", "XML nesting/element count exceeds its limit"
                        )
                    if tag == "Relationship":
                        target = element.get("Target", "")
                        if (
                            element.get("TargetMode", "").lower() == "external"
                            or re.match(r"^[a-zA-Z]+:", target)
                            or target.startswith("//")
                        ):
                            raise ParseFailure(
                                "EXTERNAL_CONTENT", "External relationships are not accepted"
                            )
                        if name == "xl/_rels/workbook.xml.rels":
                            relationships[element.get("Id", "")] = target
                    if name == "[Content_Types].xml" and tag == "Override":
                        content_type = element.get("ContentType", "").lower()
                        if "macroenabled" in content_type or "activex" in content_type:
                            raise ParseFailure(
                                "ACTIVE_CONTENT", "Macro-enabled content is not accepted"
                            )
                        if element.get("PartName") == "/xl/workbook.xml":
                            workbook_type = content_type == (
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
                            )
                    if name == "xl/workbook.xml" and tag == "sheet":
                        rid = element.get(
                            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id",
                            "",
                        )
                        sheets.append((element.get("name", ""), rid))
                        if len(sheets) > limits.max_sheets:
                            raise ParseFailure(
                                "SHEET_LIMIT", "Workbook exceeds the worksheet limit"
                            )
                    if name == "xl/styles.xml" and tag == "xf":
                        styles += 1
                        if styles > 10000:
                            raise ParseFailure("STYLE_LIMIT", "Too many Excel styles")
                    if name == "xl/sharedStrings.xml" and tag == "si":
                        shared_strings += 1
                        if shared_strings > limits.max_cells:
                            raise ParseFailure("CELL_COUNT_LIMIT", "Too many shared strings")
                    if worksheet and tag == "row":
                        try:
                            row = int(element.get("r", "0"))
                        except ValueError as exc:
                            raise ParseFailure(
                                "XLSX_INVALID", "Invalid worksheet row coordinate"
                            ) from exc
                        if not 1 <= row <= limits.max_total_rows + 1:
                            raise ParseFailure(
                                "ROW_LIMIT", "Worksheet row coordinate exceeds its limit"
                            )
                        row_max = max(row_max, row)
                        if row <= last_row:
                            raise ParseFailure(
                                "XLSX_INVALID", "Duplicate or unsorted worksheet rows"
                            )
                        current_row, last_row, last_column = row, row, 0
                    if worksheet and tag == "c":
                        coordinate, cell_type = element.get("r", ""), element.get("t", "n")
                        match = re.fullmatch(r"([A-Z]{1,3})([1-9]\d{0,6})", coordinate)
                        if not match:
                            raise ParseFailure(
                                "XLSX_INVALID", "Unsupported worksheet cell coordinate"
                            )
                        col, row = column_index_from_string(match[1]), int(match[2])
                        if coordinate in seen_cells or row != current_row or col <= last_column:
                            raise ParseFailure(
                                "XLSX_INVALID",
                                "Duplicate, unsorted or inconsistent cell coordinates",
                            )
                        seen_cells.add(coordinate)
                        last_column = col
                        if col > limits.max_columns:
                            raise ParseFailure("COLUMN_LIMIT", "Worksheet column exceeds its limit")
                        if row > limits.max_total_rows + 1:
                            raise ParseFailure("ROW_LIMIT", "Worksheet row exceeds its limit")
                        col_max, row_max = max(col_max, col), max(row_max, row)
                        cell_count += 1
                        if cell_count > limits.max_cells:
                            raise ParseFailure("CELL_COUNT_LIMIT", "Too many workbook cells")
                else:
                    if element.text and len(element.text) > limits.max_cell_chars:
                        raise ParseFailure(
                            "CELL_SIZE_LIMIT", "An XML text node exceeds the cell limit"
                        )
                    if (
                        worksheet
                        and tag == "v"
                        and coordinate
                        and cell_type == "n"
                        and element.text
                    ):
                        if coordinate in values:
                            raise ParseFailure("XLSX_INVALID", "Duplicate numeric cell coordinate")
                        values[coordinate] = element.text
                    if worksheet and tag == "c":
                        coordinate = cell_type = None
                    element.clear()
                    depth -= 1
            actual_bytes += bounded.count
            if actual_bytes > limits.max_uncompressed_bytes:
                raise ParseFailure(
                    "ZIP_SIZE_LIMIT", "Actual uncompressed content exceeds its limit"
                )
            if worksheet:
                dimensions[name], numeric[name] = (row_max, col_max), values
    if not workbook_type or not sheets:
        raise ParseFailure(
            "FORMAT_MISMATCH", "Unsupported workbook content type or missing worksheets"
        )
    if sum(r for r, _ in dimensions.values()) > limits.max_total_rows + len(sheets):
        raise ParseFailure("ROW_LIMIT", "Combined worksheet extents exceed the total row limit")
    paths = {}
    for title, rid in sheets:
        target = relationships.get(rid, "")
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        if not title or len(title) > 128 or path not in dimensions or title in paths:
            raise ParseFailure("XLSX_INVALID", "Invalid or unsupported worksheet relationship")
        paths[title] = path
    return numeric, dimensions, paths


def read_xlsx(data: bytes, options: ParseOptions, guard: Guard) -> tuple[list[RawSheet], list[str]]:
    workbook = None
    try:
        _directory_limit(data, guard)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            numeric, dimensions, paths = _preflight(archive, guard)
        selected = options.sheets or list(paths)
        if len(set(selected)) != len(selected) or any(n not in paths for n in selected):
            raise ParseFailure("SHEET_UNKNOWN", "Selected worksheets are missing or duplicated")
        if any(n not in paths for n in options.sheet_headers):
            raise ParseFailure("SHEET_UNKNOWN", "Header settings reference an unknown worksheet")
        workbook = load_workbook(
            io.BytesIO(data), read_only=True, data_only=False, keep_links=False
        )
        result = []
        for ws in workbook.worksheets:
            if ws.title not in selected:
                continue
            raw = RawSheet(ws.title, [], hidden=ws.sheet_state != "visible")
            path = paths[ws.title]
            row_max, col_max = dimensions[path]
            if row_max and col_max:
                ws.reset_dimensions()  # Never trust the file's claimed <dimension>.
                for row_number, row in enumerate(ws.iter_rows(max_row=row_max, max_col=col_max), 1):
                    values: list[str | None] = []
                    for col, cell in enumerate(row, 1):
                        value = cell.value
                        lexical = numeric[path].get(getattr(cell, "coordinate", ""))
                        code = None
                        if cell.data_type == "f":
                            if not isinstance(value, str):
                                raise ParseFailure(
                                    "FORMULA_UNSUPPORTED",
                                    "Array/data-table formulas are unsupported",
                                )
                            code = "FORMULA_AS_TEXT"
                            raw.forced_text.add(col)
                        elif cell.data_type == "e":
                            code = "EXCEL_ERROR_AS_TEXT"
                            raw.forced_text.add(col)
                        elif (
                            lexical is not None
                            and cell.is_date
                            and workbook.epoch == CALENDAR_WINDOWS_1900
                            and Decimal("60") <= Decimal(lexical) < Decimal("61")
                        ):
                            value, code = lexical, "EXCEL_INVALID_LEAP_DAY"
                            raw.forced_text.add(col)
                        elif lexical is not None and not cell.is_date:
                            value = (
                                lexical  # Preserve numeric XML, not openpyxl's float approximation.
                            )
                            if re.fullmatch(r"0{2,63}", cell.number_format) and re.fullmatch(
                                r"\d+", lexical
                            ):
                                value = lexical.zfill(len(cell.number_format))
                                code = "FORMATTED_IDENTIFIER_AS_TEXT"
                                raw.forced_text.add(col)
                            elif cell.number_format not in {"General", "0", "0.00"}:
                                code = "NUMBER_FORMAT_REQUIRES_REVIEW"
                        elif isinstance(value, bool):
                            value = "true" if value else "false"
                        elif isinstance(value, (datetime, date, time)):
                            value = value.isoformat()
                        elif isinstance(value, timedelta):
                            value, code = str(value), "DURATION_AS_TEXT"
                            raw.forced_text.add(col)
                        elif value is not None and not isinstance(value, str):
                            value = str(value)
                        if code:
                            key = (code, col)
                            raw.annotations[key] = raw.annotations.get(key, 0) + 1
                        values.append(value)
                    guard.row(values)
                    raw.records.append((row_number, values))
            result.append(raw)
        return result, list(paths)
    except ParseFailure:
        raise
    except (
        zipfile.BadZipFile,
        XMLParseError,
        DefusedXmlException,
        InvalidFileException,
        KeyError,
        ValueError,
        TypeError,
        OSError,
        RuntimeError,
        EOFError,
        OverflowError,
        IndexError,
        zlib.error,
    ) as exc:
        raise ParseFailure(
            "XLSX_INVALID", "XLSX package/XML/cell content is invalid or unsafe"
        ) from exc
    finally:
        if workbook is not None:
            workbook.close()
