import io
import random
import struct
import zipfile

import pytest
from openpyxl import Workbook

from datapilot.ingestion.contracts import ParseFailure, ParseLimits, ParseOptions
from datapilot.ingestion.parser import parse_bytes
from datapilot.ingestion.profiling import propose_schema


def book() -> bytes:
    wb = Workbook()
    sheet = wb.active
    sheet.append(["identifier", "date", "formula"])
    sheet.append([1, 60, '=WEBSERVICE("https://invalid.test")'])
    sheet["A2"].number_format = "00000"
    sheet["B2"].number_format = "yyyy-mm-dd"
    out = io.BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue()


def replace_sheet(data: bytes, transform) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w") as target:
        for entry in source.infolist():
            value = source.read(entry)
            if entry.filename == "xl/worksheets/sheet1.xml":
                value = transform(value)
            target.writestr(entry.filename, value)
    return out.getvalue()


def test_zero_formats_excel_phantom_date_and_formula_do_not_lose_source_semantics(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("File parsing must not contact external services")

    monkeypatch.setattr("socket.create_connection", no_network)
    data = parse_bytes(book(), "synthetic.xlsx", options=ParseOptions(header="present"))
    table = data.tables[0]
    assert table.rows == [["00001", "60", '=WEBSERVICE("https://invalid.test")']]
    assert {i.code for i in table.issues} >= {
        "FORMATTED_IDENTIFIER_AS_TEXT",
        "EXCEL_INVALID_LEAP_DAY",
        "FORMULA_AS_TEXT",
    }
    assert all(c.suggested_type == "TEXT" for c in propose_schema(data).tables[0].columns)


@pytest.mark.parametrize(
    "transform",
    [
        lambda xml: xml.replace(b'r="C2"', b'r="A2"'),
        lambda xml: xml.replace(b'r="A2"', b'r="A1"'),
        lambda xml: xml.replace(
            b'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"',
            b'xmlns="https://invalid.test"',
        ),
        lambda xml: xml.replace(b's="1"', b's="99999"'),
    ],
)
def test_invalid_cell_coordinates_namespace_or_styles_fail_clearly(transform):
    with pytest.raises(ParseFailure) as err:
        parse_bytes(replace_sheet(book(), transform), "invalid.xlsx")
    assert err.value.error.code == "XLSX_INVALID"


@pytest.mark.parametrize(
    "limits,code",
    [
        (ParseLimits(max_columns=2), "COLUMN_LIMIT"),
        (ParseLimits(max_total_rows=1), "ROW_LIMIT"),
        (ParseLimits(max_cells=3), "CELL_COUNT_LIMIT"),
    ],
)
def test_workbook_dimension_and_cell_counts_apply_before_loading(limits, code):
    data = book()
    if code == "ROW_LIMIT":
        data = replace_sheet(
            data,
            lambda xml: (
                xml.replace(b'r="2"', b'r="3"')
                .replace(b'r="A2"', b'r="A3"')
                .replace(b'r="B2"', b'r="B3"')
                .replace(b'r="C2"', b'r="C3"')
            ),
        )
    with pytest.raises(ParseFailure) as err:
        parse_bytes(data, "invalid.xlsx", limits=limits)
    assert err.value.error.code == code


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_fixed_seed_small_malformed_corpus_never_escapes_parse_contract(extension):
    rng = random.Random(42)
    for _ in range(32):
        payload = bytes(rng.randrange(256) for _ in range(128))
        try:
            parse_bytes(payload, "synthetic." + extension)
        except ParseFailure as exc:
            assert exc.error.code and len(exc.error.message) <= 256


def test_explicit_wrong_utf16_endianness_is_not_silently_overridden():
    with pytest.raises(ParseFailure) as err:
        parse_bytes(
            "id\n001\n".encode("utf-16"),
            "synthetic.csv",
            options=ParseOptions(encoding="utf-16-be"),
        )
    assert err.value.error.code == "ENCODING_CONFLICT"


def test_zip_entry_counts_are_checked_before_zipinfo_allocation(monkeypatch):
    original = book()
    end = original.rfind(b"PK\x05\x06")
    excessive = bytearray(original)
    struct.pack_into("<2H", excessive, end + 8, 600, 600)
    inconsistent = bytearray(original)
    struct.pack_into("<2H", inconsistent, end + 8, 1, 1)

    def never_allocate(*args, **kwargs):
        raise AssertionError("Invalid directory must fail before ZipFile allocates records")

    monkeypatch.setattr("datapilot.ingestion.xlsx.zipfile.ZipFile", never_allocate)
    for payload, code in ((excessive, "ZIP_ENTRY_COUNT_LIMIT"), (inconsistent, "XLSX_INVALID")):
        with pytest.raises(ParseFailure) as err:
            parse_bytes(bytes(payload), "synthetic.xlsx")
        assert err.value.error.code == code
