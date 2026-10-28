"""Exact owner-approved Gate 2B registration; no runtime, source, grant or Gold edits."""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import uuid4

import sqlalchemy as sa
from p7_business_v2 import BASE, DEST, load_v2
from p7_campaign import settings_for_host
from p7_gate2b import ROOT, environment, inspect, write_new
from p7_holdout_pack import canonical, sha
from sqlglot import exp

from datapilot.datasets.contracts import DatasetBinding, DatasetScope
from datapilot.db import catalog
from datapilot.db.semantic_schema import metric_versions, semantic_versions
from datapilot.ingestion.common import digest
from datapilot.ingestion.contracts import SchemaConfirmation
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.types import convert_value
from datapilot.persistence.session import run_async
from datapilot.runtime.mcp_client import dataset_session
from datapilot.semantics.contracts import MetricDraft, SemanticDraft
from datapilot.semantics.registry import RegistryStore
from datapilot.tools.sql import _serialize_cell

REQUEST_SHA = "76c1e8d6ca861770e6e5c32cc9c67b7a1a2a0d1bdbebc17ae25796929ecf29c0"
OUTPUT = BASE / "p3-owner-confirmation"


def approved_entries(raw, approval):
    if sha(raw) != REQUEST_SHA or (
        approval.get("authority") != "direct_user_message"
        or approval.get("approved_by_role") != "project_owner"
        or approval.get("request_sha256") != REQUEST_SHA
        or approval.get("approved_groups") != ["A", "B"]
        or approval.get("excluded_groups") != ["C"]
        or approval.get("paid_live_authorized") is not False
        or not approval.get("source_user_decision_ref")
    ):
        raise ValueError("Exact explicit owner approval is required")
    entries = json.loads(raw)["entries"]
    if Counter(e["category"][0] for e in entries) != {"A": 26, "B": 6, "C": 2}:
        raise ValueError("Approved denominator differs")
    for e in entries:
        i = e["identity"]
        draft = (SemanticDraft if i["kind"] == "semantic" else MetricDraft).model_validate_json(
            json.dumps(e["definition"])
        )
        if (
            draft.dataset_id != i["dataset_id"]
            or draft.dataset_version != i["dataset_version"]
            or digest(draft) != i["definition_sha256"]
            or sha(canonical(i)) != e["entry_id"]
            or (i["kind"] == "metric" and draft.semantic_version != i["semantic_version"])
            or (i["kind"] == "metric" and draft.metric_id != i["metric_id"])
        ):
            raise ValueError("Definition identity/hash differs from approved manifest")
    return sorted(
        (e for e in entries if e["category"][0] in {"A", "B"}),
        key=lambda e: (
            e["identity"]["kind"] != "semantic",
            e["identity"]["dataset_id"],
            e["identity"]["dataset_version"],
            e["identity"].get("metric_id", ""),
            e["identity"].get("metric_version", e["identity"]["semantic_version"]),
        ),
    )


def cell(value, kind):
    if value is None:
        return None
    if kind == "NUMERIC":
        with localcontext() as context:
            context.prec = 60
            return format(Decimal(str(value)).normalize(), "f")
    return _serialize_cell(value)


def rows_hash(rows, kinds):
    normalized = [[cell(v, k) for v, k in zip(row, kinds, strict=True)] for row in rows]
    return sha(canonical(sorted(normalized, key=lambda row: canonical(row))))


def zero_coverage_check(task, semantic, metric, records):
    entity = next(e for e in semantic["entities"] if e["entity"] == "invoices")
    window = task.metrics[0].window
    if not (
        entity["coverage_start"]
        <= window.start.isoformat()
        < window.end_exclusive.isoformat()
        <= entity["coverage_end_exclusive"]
        and entity["timezone"] == "UTC"
        and entity["amount_storage"] == "minor"
        and metric["paid_values"] == ["paid"]
        and metric["currency"] == "CNY"
    ):
        raise ValueError("Zero-value coverage/unit definition conflict")
    selected = [
        row
        for row in records
        if row["payment_status"] in metric["paid_values"]
        and window.start.isoformat() <= row["invoice_date"] < window.end_exclusive.isoformat()
        and row["currency"] == "CNY"
    ]
    value = sum((Decimal(str(r["amount"])) for r in selected), Decimal(0)) / Decimal(100)
    if selected or value != 0:
        raise ValueError("Materialized source conflicts with explicit zero-value case")
    return {
        "case_id": task.case_id,
        "definition_conflict": False,
        "source_rows": len(records),
        "selected_paid_rows": 0,
        "independent_decimal_value": str(value),
        "unit": "CNY",
        "window": window.model_dump(mode="json"),
        "coverage_authority": "explicit project-owner attestation; not inferred from row absence",
        "p3_verified_claim": False,
    }


async def validate_sources(entries, tasks, pins):
    checks, records = [], {}
    settings = settings_for_host()
    for alias, pin in pins["datasets"].items():
        path = DEST / "assets" / pin["asset_path"]
        if sha(path.read_bytes()) != pin["source_sha256"]:
            raise ValueError("Approved original asset changed")
        confirmation = SchemaConfirmation.model_validate_json(
            json.dumps(pins["confirmations"][alias])
        )
        if (
            confirmation.confirmation_sha256 != pin["confirmation_sha256"]
            or digest(confirmation.model_dump(mode="json", exclude={"confirmation_sha256"}))
            != confirmation.confirmation_sha256
        ):
            raise ValueError("Upload confirmation changed")
        data = parse_file(path, options=confirmation.options, limits=confirmation.limits)
        binding = DatasetScope(
            bindings=[DatasetBinding(dataset_id=pin["dataset_id"], version=pin["dataset_version"])]
        )
        async with dataset_session(settings, binding) as tools:
            schema = await tools.schema(pin["dataset_id"])
            if (schema.version, schema.source_sha256) != (
                pin["dataset_version"],
                pin["source_sha256"],
            ):
                raise ValueError("Materialized version/source hash changed")
            records[alias] = {}
            for raw, confirmed in zip(data.tables, confirmation.tables, strict=True):
                table = next(t for t in schema.tables if t.table_id == confirmed.table_id)
                names = [c.normalized_name for c in confirmed.columns]
                if names != [c.normalized_name for c in table.columns]:
                    raise ValueError("Confirmed physical columns differ")
                typed = [
                    [
                        convert_value(v, c.logical_type, c.date_format)
                        for v, c in zip(row, confirmed.columns, strict=True)
                    ]
                    for row in raw.rows
                ]

                def quote(name):
                    return exp.to_identifier(name, quoted=True).sql(dialect="postgres")

                sql = (
                    "SELECT "
                    + ",".join(map(quote, names))
                    + " FROM uploads."
                    + quote(table.physical_name)
                )
                result = await tools.execute(pin["dataset_id"], sql)
                kinds = [c.logical_type for c in confirmed.columns]
                expected = rows_hash(typed, kinds)
                if (
                    result.result.truncated
                    or result.result.row_count != len(typed)
                    or rows_hash(result.result.rows, kinds) != expected
                ):
                    raise ValueError("Materialized rows differ from original source")
                records[alias][table.table_id] = [
                    dict(zip(names, [_serialize_cell(v) for v in row], strict=True))
                    for row in typed
                ]
                checks.append(
                    {
                        "dataset_alias": alias,
                        "dataset_id": pin["dataset_id"],
                        "dataset_version": schema.version,
                        "source_sha256": schema.source_sha256,
                        "table_id": table.table_id,
                        "rows": len(typed),
                        "normalized_rows_sha256": expected,
                        "query_sha256": result.query_sha256,
                        "result_sha256": result.result_sha256,
                    }
                )
    for entry in entries:
        p = pins["datasets"][entry["dataset_alias"]]
        if entry["source_sha256"] != p["source_sha256"]:
            raise ValueError("Approval source differs")
    by_case = {t.case_id: t for t in tasks}
    targeted = []
    for id_ in ("bh2-016", "bh2-052"):
        p = pins["datasets"]["empty_ledger"]
        targeted.append(
            zero_coverage_check(
                by_case[id_],
                p["semantic_definitions"][0]["definition"],
                p["metric_definitions"][0]["definition"],
                records["empty_ledger"]["table_1"],
            )
        )
    task = by_case["bh2-047"]
    text = (DEST / "assets/documents/data_v2/billing.md").read_text(encoding="utf-8")
    if (
        "四月生效" not in task.question
        or "生效期：2023年4月。" not in text
        or task.metrics[0].window.end_exclusive.isoformat() != "2023-04-01"
    ):
        raise ValueError("Rule effective date conflicts with scoped question")
    targeted.append(
        {
            "case_id": "bh2-047",
            "definition_conflict": False,
            "measurement_window": task.metrics[0].window.model_dump(mode="json"),
            "document_effective_month": "2023-04",
            "document_sha256": sha(text.encode()),
            "rule_applied_retroactively": False,
            "meaning": (
                "March corrected snapshot revenue; April rule is quoted background, "
                "not a March metric filter"
            ),
        }
    )
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "physical_tables": checks,
        "targeted_checks": targeted,
        "model_calls": 0,
        "registry_writes": 0,
    }


def validate_registry(entries, store):
    """Check the exact current prefix before any append; reject conflicting versions."""
    with store.engine.begin() as connection:
        store._configure(connection)
        state = {}
        for entry in entries:
            i = entry["identity"]
            table = semantic_versions if i["kind"] == "semantic" else metric_versions
            version_col = (
                table.c.semantic_version if i["kind"] == "semantic" else table.c.metric_version
            )
            condition = [
                table.c.dataset_id == i["dataset_id"],
                table.c.dataset_version == i["dataset_version"],
            ]
            if i["kind"] == "metric":
                condition.append(table.c.metric_id == i["metric_id"])
            key = (i["kind"], i["dataset_id"], i["dataset_version"], i.get("metric_id"))
            if key not in state:
                state[key] = dict(
                    connection.execute(
                        sa.select(version_col, table.c.definition_sha256).where(*condition)
                    ).all()
                )
            versions = state[key]
            requested = i.get("metric_version", i["semantic_version"])
            if requested in versions:
                if versions[requested] != i["definition_sha256"]:
                    raise ValueError("Existing Registry version conflicts with approved hash")
            elif requested != max(versions, default=0) + 1:
                raise ValueError("Exact original Registry append sequence cannot satisfy approval")
            versions[requested] = i["definition_sha256"]


def check_exclusions(store):
    """No write to a deliberately absent definition or non-existent version is permitted."""
    tasks, pins, _ = load_v2()
    request = json.loads((BASE / "private/p3-confirmation-request.json").read_bytes())
    with store.engine.begin() as connection:
        store._configure(connection)
        for entry in request["entries"]:
            if not entry["category"].startswith("C_"):
                continue
            i = entry["identity"]
            table = semantic_versions if i["kind"] == "semantic" else metric_versions
            conditions = [
                table.c.dataset_id == i["dataset_id"],
                table.c.dataset_version == i["dataset_version"],
            ]
            if i["kind"] == "semantic":
                conditions.append(table.c.semantic_version == i["semantic_version"])
            else:
                conditions.extend(
                    [
                        table.c.metric_id == i["metric_id"],
                        table.c.metric_version == i["metric_version"],
                    ]
                )
            if connection.scalar(sa.select(sa.func.count()).select_from(table).where(*conditions)):
                raise ValueError("Excluded C definition exists; stop and reconcile")
        by_id = {t.case_id: t for t in tasks}
        bad_metric = by_id["bh2-019"].metrics[0]
        if connection.scalar(
            sa.select(sa.func.count())
            .select_from(metric_versions)
            .where(
                metric_versions.c.dataset_id == bad_metric.dataset_id,
                metric_versions.c.dataset_version == bad_metric.dataset_version,
                metric_versions.c.metric_id == bad_metric.metric_id,
                metric_versions.c.metric_version == bad_metric.metric_version,
            )
        ):
            raise ValueError("Deliberately absent metric version exists")
        bad_source = by_id["bh2-048"].metrics[0]
        if connection.scalar(
            sa.select(sa.func.count())
            .select_from(catalog.versions)
            .where(
                catalog.versions.c.dataset_id == bad_source.dataset_id,
                catalog.versions.c.version == bad_source.dataset_version,
            )
        ):
            raise ValueError("Deliberately absent Dataset version exists")
    return {
        "excluded_c_definitions_absent": 2,
        "metric_999999_absent": True,
        "dataset_999999_absent": True,
    }


def apply(entries, approval, source_receipt):
    if source_receipt.get("registry_writes") != 0 or any(
        c["definition_conflict"] for c in source_receipt["targeted_checks"]
    ):
        raise ValueError("Source checks did not admit registration")
    store = RegistryStore(environment()["DATAPILOT_REGISTRY_DATABASE_URL"])
    try:
        check_exclusions(store)
        validate_registry(entries, store)
        for entry in entries:
            path = OUTPUT / (entry["entry_id"] + ".json")
            if path.exists():
                raise ValueError("Prior entry receipt exists; inspect instead of reapplying")
            i = entry["identity"]
            kind = i["kind"]
            draft = (SemanticDraft if kind == "semantic" else MetricDraft).model_validate_json(
                json.dumps(entry["definition"])
            )
            # The actual direct owner approval supplies reviewed to the ORIGINAL API.
            # No UPDATE/DDL, persisted flag changes, Registry bypass or new confirmation mechanism.
            record = (
                store.confirm_semantics(draft, reviewed=True)
                if kind == "semantic"
                else store.confirm_metric(draft, reviewed=True)
            )
            actual_version = (
                record.semantic_version if kind == "semantic" else record.metric_version
            )
            if (
                actual_version != i.get("metric_version", i["semantic_version"])
                or record.definition_sha256 != i["definition_sha256"]
            ):
                raise ValueError("Unexpected original Registry identity; stop and reconcile")
            write_new(
                path,
                {
                    "entry_id": entry["entry_id"],
                    "request_sha256": REQUEST_SHA,
                    "owner_approval_sha256": digest(approval),
                    "source_check_sha256": digest(source_receipt),
                    "record": record.model_dump(mode="json"),
                    "confirmed_at": datetime.now(UTC).isoformat(),
                },
            )
        write_new(OUTPUT / "exclusions-after.json", check_exclusions(store))
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "apply"])
    options = parser.parse_args()
    inspect()
    approval = json.loads((ROOT / "docs/research/p7-p3-owner-approval.json").read_bytes())
    entries = approved_entries(
        (BASE / "private/p3-confirmation-request.json").read_bytes(), approval
    )
    tasks, pins, _ = load_v2()
    result = run_async(validate_sources(entries, tasks, pins))
    receipt_path = OUTPUT / ("source-check-" + options.action + ".json")
    if receipt_path.exists():
        receipt_path = OUTPUT / ("source-check-" + options.action + "-" + uuid4().hex + ".json")
    write_new(receipt_path, result)
    if options.action == "apply":
        apply(entries, approval, result)
    print(
        json.dumps(
            {
                "checked_entries": len(entries),
                "tables": len(result["physical_tables"]),
                "registered_entries": len(entries) if options.action == "apply" else 0,
                "paid_calls": 0,
            }
        )
    )
