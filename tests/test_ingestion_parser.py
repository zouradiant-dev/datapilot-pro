import io
import zipfile

import pytest
from openpyxl import Workbook

from datapilot.ingestion.contracts import ParseFailure, ParseLimits, ParseOptions
from datapilot.ingestion.parser import parse_bytes


def workbook_bytes(sheets=None):
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in (sheets or {"Customers": [["id", "name"], ["001", "Synthetic A"]]}).items():
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue()


def rewrite_zip(data, replace=None, extra=None):
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as old,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as new,
    ):
        for item in old.infolist():
            payload = old.read(item)
            new.writestr(item.filename, (replace or {}).get(item.filename, payload))
        for name, payload in (extra or {}).items():
            new.writestr(name, payload)
    return out.getvalue()


def test_csv_bom_chinese_duplicate_empty_headers_and_blank_rows():
    text = "编号,名称,名称,\n001,甲,乙,\n\n002,丙,丁,\n"
    result = parse_bytes(
        text.encode("utf-8-sig"), "customers.csv", options=ParseOptions(header="present")
    )
    table = result.tables[0]
    assert result.upload.encoding == "utf-8-sig"
    assert table.rows[0] == ["001", "甲", "乙", ""]
    assert len(set(c.normalized_name for c in table.columns)) == 4
    assert [c.original_name for c in table.columns] == ["编号", "名称", "名称", ""]
    assert table.skipped_blank_rows == 1
    assert {i.code for i in table.issues} >= {
        "DUPLICATE_HEADERS",
        "EMPTY_HEADERS",
        "BLANK_ROWS_SKIPPED",
    }


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32", "gb18030"])
def test_encoding_detection_or_explicit_lossless_override(encoding):
    options = ParseOptions(header="present", encoding="gb18030" if encoding == "gb18030" else None)
    data = parse_bytes("编号;金额\n001;12.30\n".encode(encoding), "data.csv", options=options)
    assert data.upload.delimiter == ";" and data.tables[0].rows == [["001", "12.30"]]


def test_unknown_encoding_and_conflicting_bom_are_clear_errors():
    with pytest.raises(ParseFailure) as err:
        parse_bytes("编号,金额\n001,10\n".encode("gb18030"), "data.csv")
    assert err.value.error.code == "ENCODING_REQUIRED"
    with pytest.raises(ParseFailure) as err:
        parse_bytes("id\n001\n".encode("utf-16"), "x.csv", options=ParseOptions(encoding="utf-8"))
    assert err.value.error.code == "ENCODING_CONFLICT"


def test_quoted_newlines_delimiter_and_no_header_loss():
    parsed = parse_bytes(b'id;note\n001;"alpha\nbeta"\n', "a.csv")
    assert parsed.tables[0].rows == [["001", "alpha\nbeta"]]
    assert parsed.tables[0].source_rows == [2]
    uncertain = parse_bytes(b"Alice,Boston\nBob,Paris\n", "a.csv")
    assert len(uncertain.tables[0].rows) == 2
    assert "HEADER_AMBIGUOUS" in {i.code for i in uncertain.tables[0].issues}
    absent = parse_bytes(b"1,2\n3,4\n", "a.csv", options=ParseOptions(header="absent"))
    assert absent.tables[0].rows == [["1", "2"], ["3", "4"]]


@pytest.mark.parametrize(
    "content,options,code",
    [
        (b"id,v\n1,2,3\n", ParseOptions(delimiter=","), "RAGGED_ROWS"),
        (b'id,v\n1,"broken', ParseOptions(delimiter=","), "CSV_MALFORMED"),
        (b"id\n\x00\n", ParseOptions(), "INVALID_TEXT"),
        (b"", ParseOptions(), "EMPTY_FILE"),
    ],
)
def test_malformed_csv_is_not_silently_repaired(content, options, code):
    with pytest.raises(ParseFailure) as err:
        parse_bytes(content, "a.csv", options=options)
    assert err.value.error.code == code


@pytest.mark.parametrize(
    "limits,code",
    [
        (ParseLimits(max_file_bytes=4), "FILE_SIZE_LIMIT"),
        (ParseLimits(max_columns=1), "COLUMN_LIMIT"),
        (ParseLimits(max_total_rows=1), "ROW_LIMIT"),
        (ParseLimits(max_cells=2), "CELL_COUNT_LIMIT"),
        (ParseLimits(max_cell_chars=1), "CELL_SIZE_LIMIT"),
        (ParseLimits(max_parsed_bytes=3), "PARSED_SIZE_LIMIT"),
    ],
)
def test_csv_resource_limits(limits, code):
    with pytest.raises(ParseFailure) as err:
        parse_bytes(b"id,value\n001,12\n002,20\n", "a.csv", limits=limits)
    assert err.value.error.code == code


def test_multiple_xlsx_sheets_selection_and_formula_text():
    data = workbook_bytes(
        {
            "客户": [["id", "name"], ["001", "A"]],
            "Invoices": [["customer_id", "amount"], ["001", "=1+2"]],
        }
    )
    result = parse_bytes(data, "saas.xlsx", options=ParseOptions(header="present"))
    assert result.upload.sheets == ["客户", "Invoices"]
    assert result.tables[1].rows == [["001", "=1+2"]]
    assert result.tables[1].forced_text_columns == ["amount"]
    assert result.tables[1].issues[-1].code == "FORMULA_AS_TEXT"
    selected = parse_bytes(data, "saas.xlsx", options=ParseOptions(sheets=["客户"]))
    assert len(selected.tables) == 1
    with pytest.raises(ParseFailure) as err:
        parse_bytes(data, "saas.xlsx", options=ParseOptions(sheets=["unknown"]))
    assert err.value.error.code == "SHEET_UNKNOWN"


def test_xlsx_numeric_lexeme_preserves_precision_before_float_conversion():
    data = workbook_bytes({"Amounts": [["amount"], [1.5]]})
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        xml = source.read("xl/worksheets/sheet1.xml").replace(
            b"<v>1.5</v>", b"<v>1234567890.123456789</v>"
        )
    data = rewrite_zip(data, {"xl/worksheets/sheet1.xml": xml})
    parsed = parse_bytes(data, "amounts.xlsx", options=ParseOptions(header="present"))
    assert parsed.tables[0].rows == [["1234567890.123456789"]]


def test_xlsx_rejects_external_relationships_macros_and_path_traversal():
    data = workbook_bytes()
    for extra, code in [
        ({"xl/vbaProject.bin": b"not executable"}, "ACTIVE_CONTENT"),
        ({"../escape.xml": b"<a/>"}, "ZIP_PATH_INVALID"),
        (
            {
                "xl/_rels/unsafe.rels": b'<Relationships><Relationship TargetMode="External" Target="https://invalid.test"/></Relationships>'
            },
            "EXTERNAL_CONTENT",
        ),
    ]:
        with pytest.raises(ParseFailure) as err:
            parse_bytes(rewrite_zip(data, extra=extra), "unsafe.xlsx")
        assert err.value.error.code == code


def test_xlsx_xml_entity_attack_is_rejected_before_workbook_loading():
    payload = b'<!DOCTYPE a [<!ENTITY secret SYSTEM "file:///not-read">]><a>&secret;</a>'
    with pytest.raises(ParseFailure) as err:
        parse_bytes(rewrite_zip(workbook_bytes(), extra={"custom.xml": payload}), "unsafe.xlsx")
    assert err.value.error.code == "XLSX_INVALID"


@pytest.mark.parametrize(
    "limits,code",
    [
        (ParseLimits(max_sheets=1), "SHEET_LIMIT"),
        (ParseLimits(max_zip_entries=2), "ZIP_ENTRY_COUNT_LIMIT"),
        (ParseLimits(max_uncompressed_bytes=2000), "ZIP_SIZE_LIMIT"),
        (ParseLimits(max_entry_bytes=1000), "ZIP_ENTRY_LIMIT"),
        (ParseLimits(max_compression_ratio=1), "ZIP_RATIO_LIMIT"),
        (ParseLimits(max_xml_elements=5), "XML_LIMIT"),
    ],
)
def test_xlsx_archive_resource_limits(limits, code):
    data = workbook_bytes({"A": [["id"], ["001"]], "B": [["id"], ["002"]]})
    with pytest.raises(ParseFailure) as err:
        parse_bytes(data, "unsafe.xlsx", limits=limits)
    assert err.value.error.code == code


def test_xlsx_sparse_positions_are_bounded_and_dimension_is_not_trusted():
    data = workbook_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        xml = source.read("xl/worksheets/sheet1.xml").replace(
            b'ref="A1:B2"', b'ref="A1:XFD1048576"'
        )
    assert (
        len(
            parse_bytes(rewrite_zip(data, {"xl/worksheets/sheet1.xml": xml}), "safe.xlsx")
            .tables[0]
            .rows
        )
        == 1
    )
    xml = xml.replace(b'r="B2"', b'r="XFD2"')
    with pytest.raises(ParseFailure) as err:
        parse_bytes(rewrite_zip(data, {"xl/worksheets/sheet1.xml": xml}), "bad.xlsx")
    assert err.value.error.code == "COLUMN_LIMIT"


def test_deadline_is_enforced_cooperatively(monkeypatch):
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr("datapilot.ingestion.common.time.monotonic", lambda: next(ticks))
    with pytest.raises(ParseFailure) as err:
        parse_bytes(b"id\n001\n", "a.csv", limits=ParseLimits(max_seconds=1.0))
    assert err.value.error.code == "PARSE_TIMEOUT"


@pytest.mark.parametrize(
    "data,name",
    [(b"not a zip", "a.xlsx"), (b"a", "a.xlsm"), (b"a", "../a.csv"), (b"PK\x03\x04", "a.csv")],
)
def test_illegal_container_or_filename_is_rejected(data, name):
    with pytest.raises(ParseFailure):
        parse_bytes(data, name)
