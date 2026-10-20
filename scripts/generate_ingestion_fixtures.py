"""Generate public synthetic P1 fixtures, with fixed workbook metadata and ZIP timestamps."""

import hashlib
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import tostring

from defusedxml.ElementTree import fromstring
from openpyxl import Workbook


def build_fixtures() -> dict[str, bytes]:
    customers = (
        "客户编号,客户分群,注册日期\n0001,small,2025-01-01\n"
        "0002,midmarket,2025-02-01\n0003,enterprise,2025-03-01\n"
    )
    invoices = (
        "invoice_id;customer_id;amount;invoice_date\nINV-1;0001;123.4500;2025-10-01\n"
        "INV-2;0001;89.9900;2025-10-15\nINV-3;0002;1000.0000;2025-10-20\n"
    )
    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.properties.created = workbook.properties.modified = datetime(2025, 1, 1)
    workbook.properties.creator = "DataPilot synthetic fixture generator"
    rows = {
        "Customers": [
            ["customer_id", "segment", "signup_date"],
            ["0001", "small", "2025-01-01"],
            ["0002", "midmarket", "2025-02-01"],
            ["0003", "enterprise", "2025-03-01"],
        ],
        "Invoices": [
            ["invoice_id", "customer_id", "amount", "invoice_date"],
            ["INV-1", "0001", 123.45, "2025-10-01"],
            ["INV-2", "0001", 89.99, "2025-10-15"],
            ["INV-3", "0002", 1000, "2025-10-20"],
        ],
        "Review": [["note", None, "value"], ["Formula kept as text", None, "=2+2"]],
    }
    for title, values in rows.items():
        sheet = workbook.create_sheet(title)
        for row in values:
            sheet.append(row)
    raw = io.BytesIO()
    workbook.save(raw)
    workbook.close()
    fixed = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(raw.getvalue())) as source,
        zipfile.ZipFile(fixed, "w") as target,
    ):
        for name in sorted(source.namelist()):
            entry = zipfile.ZipInfo(name, date_time=(2025, 1, 1, 0, 0, 0))
            # Keep the committed Windows ZIP metadata identical on every host.
            entry.create_system = 0
            entry.compress_type = zipfile.ZIP_DEFLATED
            payload = source.read(name)
            if name == "docProps/core.xml":
                properties = fromstring(payload)
                for field in ("created", "modified"):
                    properties.find(
                        "{http://purl.org/dc/terms/}" + field
                    ).text = "2025-01-01T00:00:00Z"
                payload = tostring(properties, encoding="utf-8")
            target.writestr(entry, payload)
    return {
        "customers_utf8_bom.csv": customers.encode("utf-8-sig"),
        "invoices_semicolon.csv": invoices.encode("utf-8"),
        "saas_multi_sheet.xlsx": fixed.getvalue(),
    }


def main() -> None:
    directory = Path(__file__).resolve().parents[1] / "tests/fixtures/ingestion"
    directory.mkdir(parents=True, exist_ok=True)
    content = build_fixtures()
    for name, data in content.items():
        (directory / name).write_bytes(data)
    manifest = {
        "synthetic": True,
        "period": "2025",
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in content.items()
        },
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Generated 3 synthetic files and a SHA256 manifest")


if __name__ == "__main__":
    main()
