"""Public synthetic SaaS semantic acceptance data; contains no customer information."""

import csv
import io
import re
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook

from datapilot.semantics.contracts import SemanticDraft


def demo_tables():
    return {
        "invoices": [
            [
                "invoice_id",
                "customer_id",
                "amount_cents",
                "invoice_date",
                "payment_status",
                "currency",
            ],
            ["i1", "c1", 10000, "2025-10-01", "paid", "CNY"],
            ["i2", "c2", 20000, "2025-10-31", "paid", "CNY"],
            ["i3", "c3", 99900, "2025-11-01", "paid", "CNY"],
            ["i4", "c4", 40000, "2025-09-30", "paid", "CNY"],
            ["i5", "c5", 50000, "2025-10-15", "unpaid", "CNY"],
            ["i6", "c6", 0, "2025-10-20", "paid", "CNY"],
        ],
        "subscriptions": [
            ["subscription_id", "customer_id", "start_date", "end_date", "termination_kind"],
            ["s1", "c1", "2025-01-01", "2025-10-01", "churned"],
            ["s2", "c2", "2025-01-01", "2025-10-15", "churned"],
            ["s3", "c2", "2025-10-20", None, "active"],
            ["s4", "c3", "2025-01-01", None, "active"],
            ["s5", "c3", "2025-09-01", "2025-10-10", "churned"],
            ["s6", "c4", "2025-10-01", None, "active"],
            ["s7", "c5", "2025-01-01", "2025-11-01", "churned"],
            ["s8", "c6", "2025-01-01", "2025-10-31", "churned"],
            ["s9", "c7", "2025-11-01", None, "active"],
        ],
        "usage_events": [
            ["event_id", "event_date", "event_count", "feature"],
            ["e1", "2025-10-01", 10, "dashboard"],
            ["e2", "2025-10-31", 20, "dashboard"],
            ["e3", "2025-11-01", 1000, "dashboard"],
            ["e4", "2025-09-30", 99, "dashboard"],
            ["e5", "2025-10-15", 5, "api"],
        ],
    }


def write_demo(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.created = wb.properties.modified = datetime(2025, 1, 1)
    for name, rows in demo_tables().items():
        sheet = wb.create_sheet(name)
        for row in rows:
            sheet.append(row)
        with (directory / (name + ".csv")).open("w", encoding="utf-8", newline="") as output:
            csv.writer(output, lineterminator="\n").writerows(rows)
    buffer = io.BytesIO()
    wb.save(buffer)
    with (
        ZipFile(io.BytesIO(buffer.getvalue())) as source,
        ZipFile(directory / "saas_metrics.xlsx", "w") as target,
    ):
        for name in sorted(source.namelist()):
            info = ZipInfo(name, date_time=(2025, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.compress_type = ZIP_DEFLATED
            content = source.read(name)
            if name == "docProps/core.xml":
                content = re.sub(
                    rb"(<dcterms:modified[^>]*>).*?(</dcterms:modified>)",
                    rb"\g<1>2025-01-01T00:00:00Z\2",
                    content,
                )
            target.writestr(info, content)


def mapping_draft(schema):
    """Only for the documented synthetic fixture; real uploads require user mappings."""
    tables = {t.source_name: t for t in schema.tables}
    fields = {
        "invoices": {
            "record_id": "invoice_id",
            "amount": "amount_cents",
            "invoice_date": "invoice_date",
            "payment_status": "payment_status",
            "currency": "currency",
        },
        "subscriptions": {
            "record_id": "subscription_id",
            "customer_id": "customer_id",
            "start_date": "start_date",
            "end_date": "end_date",
            "termination_kind": "termination_kind",
        },
        "usage_events": {
            "record_id": "event_id",
            "event_date": "event_date",
            "event_count": "event_count",
            "feature": "feature",
        },
    }
    entities = []
    for name, table in tables.items():
        if name not in fields:
            continue
        definition = {
            "entity": name,
            "table_id": table.table_id,
            "fields": fields[name],
            "grain": [fields[name]["record_id"]],
            "coverage_start": "2025-01-01",
            "coverage_end_exclusive": "2026-01-01",
        }
        if name == "subscriptions":
            definition.update(history_complete=True, subscription_identity="contract")
        if name == "invoices":
            definition["amount_storage"] = "minor"
        entities.append(definition)
    import json

    return SemanticDraft.model_validate_json(
        json.dumps(
            {
                "dataset_id": schema.dataset_id,
                "dataset_version": schema.version,
                "entities": entities,
            }
        )
    )
