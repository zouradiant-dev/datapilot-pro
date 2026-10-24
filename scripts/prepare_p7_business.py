"""Independent synthetic Gold from reviewed definitions and original XLSX rows.

Never imports recipes, Verifier, Agent outputs or intent rules. The 50 metric goals
are scoped business-contract E2E tasks, separate from the intent-only corpus.
"""

import hashlib
import json
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/semantics/saas_metrics.xlsx"
PERIODS = [
    ("2025-01-01", "2025-02-01"),
    ("2025-09-01", "2025-10-01"),
    ("2025-10-01", "2025-11-01"),
    ("2025-11-01", "2025-12-01"),
    ("2025-10-01", "2025-10-02"),
    ("2025-10-15", "2025-10-16"),
    ("2025-10-31", "2025-11-01"),
    ("2025-09-01", "2025-12-01"),
    ("2024-12-01", "2025-01-01"),
    ("2026-01-01", "2026-02-01"),
]
AS_OF = [
    "2025-01-01",
    "2025-02-01",
    "2025-09-30",
    "2025-10-01",
    "2025-10-15",
    "2025-10-20",
    "2025-10-31",
    "2025-11-01",
    "2024-12-01",
    "2026-02-01",
]


def records():
    wb = load_workbook(SOURCE, read_only=True, data_only=True)
    try:
        result = {}
        for ws in wb.worksheets:
            values = iter(ws.values)
            names = next(values)
            result[ws.title] = [dict(zip(names, row, strict=True)) for row in values]
        return result
    finally:
        wb.close()


def expected(rows, kind, start, end, as_of=None):
    if (as_of and not "2025-01-01" <= as_of < "2026-01-01") or (
        not as_of and not ("2025-01-01" <= start < end <= "2026-01-01")
    ):
        return {"status": "unavailable", "reason": "outside_confirmed_coverage"}
    subs = rows["subscriptions"]
    if kind == "paid_invoice_revenue":
        value = sum(
            (
                Decimal(str(r["amount_cents"])) / 100
                for r in rows["invoices"]
                if r["payment_status"] == "paid"
                and r["currency"] == "CNY"
                and start <= r["invoice_date"] < end
            ),
            Decimal(0),
        )
        return {"status": "verified", "value": str(value), "unit": "CNY"}
    if kind == "usage":
        return {
            "status": "verified",
            "value": str(
                sum(
                    r["event_count"] for r in rows["usage_events"] if start <= r["event_date"] < end
                )
            ),
            "unit": "events",
        }
    if kind == "active_subscriptions":
        count = sum(
            r["start_date"] <= as_of and (r["end_date"] is None or r["end_date"] > as_of)
            for r in subs
        )
        return {"status": "verified", "value": str(count), "unit": "subscriptions"}
    cohort = [
        r
        for r in subs
        if r["start_date"] < start and (r["end_date"] is None or r["end_date"] >= start)
    ]
    if kind == "subscription_churn":
        denominator = len(cohort)
        numerator = sum(
            r["end_date"] is not None
            and start <= r["end_date"] < end
            and r["termination_kind"] == "churned"
            for r in cohort
        )
    else:
        customers = {r["customer_id"] for r in cohort}
        denominator = len(customers)
        numerator = sum(
            not any(
                r["customer_id"] == customer
                and r["start_date"] < end
                and (r["end_date"] is None or r["end_date"] >= end)
                for r in subs
            )
            for customer in customers
        )
    if not denominator:
        return {"status": "unavailable", "reason": "zero_denominator"}
    with localcontext() as context:
        context.prec = 40
        value = (Decimal(numerator) / denominator).quantize(Decimal("0.000000000001"))
    return {
        "status": "verified",
        "value": str(value),
        "unit": "ratio",
        "numerator": numerator,
        "denominator": denominator,
    }


def main():
    rows = records()
    result = []
    for kind in (
        "paid_invoice_revenue",
        "usage",
        "active_subscriptions",
        "customer_churn",
        "subscription_churn",
    ):
        for i, (start, end) in enumerate(PERIODS):
            at = AS_OF[i] if kind == "active_subscriptions" else None
            result.append(
                {
                    "case_id": f"business-{len(result) + 1:03}",
                    "kind": kind,
                    "question": f"复核已确认口径 {kind}："
                    + (f"as_of={at}" if at else f"[{start},{end})"),
                    "window": None if at else {"start": start, "end_exclusive": end},
                    "as_of": at,
                    "expected": expected(rows, kind, start, end, at),
                    "expected_window_days": (
                        date.fromisoformat(end) - date.fromisoformat(start)
                    ).days
                    if not at
                    else None,
                    "mandatory_evidence": [
                        "dataset/source/semantic/metric/query/result hash",
                        "six_layer_verdict",
                        "original_evidence_and_verification_ids",
                    ],
                    "scope": (
                        "Explicit confirmed SaaS metric; not a Chat-first intent-quality claim"
                    ),
                }
            )
    path = ROOT / "tests/fixtures/evaluation/business-dev.jsonl"
    with path.open("x", encoding="utf-8", newline="\n") as output:
        for row in result:
            output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    manifest = {
        "tasks": len(result),
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "tasks_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "gold_method": (
            "Independent openpyxl records + Decimal/set arithmetic over "
            "docs/semantic-metrics.md reviewed definitions; no Agent/recipe imports"
        ),
        "coverage": [
            "5 metric kinds",
            "half-open date boundaries",
            "cohort deduplication/re-subscription",
            "unit/minor currency",
            "empty valid period",
            "zero denominator",
            "outside confirmed coverage",
        ],
        "formal_unseen_holdout": False,
        "execution": "not_run",
    }
    with (ROOT / "docs/research/p7-business-manifest.json").open("x", encoding="utf-8") as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {"business_tasks": len(result), "gold_independent_of_agent": True, "executed": False}
        )
    )


if __name__ == "__main__":
    main()
