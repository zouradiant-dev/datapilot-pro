"""Pure deterministic dataset generation, followed by an explicit PostgreSQL seed step."""

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa

from datapilot.db.schema import BUSINESS_TABLES, metadata, seed_runs

PRICES = {"starter": 9900, "pro": 49900, "enterprise": 199900}


@dataclass(frozen=True)
class Dataset:
    tables: dict[str, list[dict]]
    manifest: dict


def generate_dataset(*, seed: int = 42, customers: int = 240) -> Dataset:
    if not 12 <= customers <= 100_000:
        raise ValueError("customers must be between 12 and 100000")
    rng = random.Random(seed)
    tables = {name: [] for name in BUSINESS_TABLES}
    sid = 0
    for cid in range(1, customers + 1):
        segment = ("small", "midmarket", "enterprise")[(cid - 1) % 3]
        industry = ("retail", "software", "services")[(cid // 3) % 3]
        start_month = 1 if cid <= customers // 2 else rng.randint(2, 9)
        tables["customers"].append(
            dict(
                customer_id=cid,
                name=f"Synthetic Company {cid:04d}",
                segment=segment,
                industry=industry,
                region=rng.choice(("east", "north", "south")),
                created_at=date(2025, start_month, 1),
            )
        )
        plan = "enterprise" if segment == "enterprise" else "pro"
        churn = cid % 7 == 0 or (segment == "small" and industry == "retail" and cid % 2 == 0)
        downgrade = not churn and cid % 5 == 0
        end_month = rng.randint(max(start_month + 1, 10), 12) if churn or downgrade else None
        sid += 1
        tables["subscriptions"].append(
            dict(
                subscription_id=sid,
                customer_id=cid,
                plan=plan,
                monthly_price_cents=PRICES[plan],
                start_date=date(2025, start_month, 1),
                end_date=date(2025, end_month, 1) if end_month else None,
                status="churned" if churn else "downgraded" if downgrade else "active",
            )
        )
        periods = [(sid, plan, start_month, end_month or 13)]
        if downgrade:
            sid += 1
            tables["subscriptions"].append(
                dict(
                    subscription_id=sid,
                    customer_id=cid,
                    plan="starter",
                    monthly_price_cents=PRICES["starter"],
                    start_date=date(2025, end_month, 1),
                    end_date=None,
                    status="active",
                )
            )
            periods.append((sid, "starter", end_month, 13))
        for period_sid, period_plan, first, last in periods:
            for month in range(first, last):
                when = date(2025, month, 1)
                tables["invoices"].append(
                    dict(
                        invoice_id=len(tables["invoices"]) + 1,
                        subscription_id=period_sid,
                        invoice_date=when,
                        amount_cents=PRICES[period_plan],
                        currency="CNY",
                        status="unpaid" if rng.random() < 0.05 else "paid",
                    )
                )
                baseline = {"small": 80, "midmarket": 300, "enterprise": 1200}[segment]
                decay = 0.35 if segment == "small" and industry == "retail" and month >= 7 else 1
                for feature in ("dashboard", "export", "api"):
                    tables["usage_events"].append(
                        dict(
                            event_id=len(tables["usage_events"]) + 1,
                            subscription_id=period_sid,
                            event_date=when,
                            feature=feature,
                            event_count=int(baseline * decay * rng.uniform(0.8, 1.2)),
                        )
                    )
            negative = churn or (segment == "small" and industry == "retail")
            tables["customer_feedback"].append(
                dict(
                    feedback_id=len(tables["customer_feedback"]) + 1,
                    customer_id=cid,
                    subscription_id=period_sid,
                    submitted_at=date(2025, last - 1, 15),
                    category="performance" if negative else "usability",
                    score=2 if negative else 4,
                    comment="Export latency and onboarding friction"
                    if negative
                    else "Dashboards save time",
                )
            )
    content = json.dumps(tables, default=str, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return Dataset(
        tables=tables,
        manifest={
            "seed": seed,
            "period_start": "2025-01-01",
            "period_end_exclusive": "2026-01-01",
            "counts": {name: len(rows) for name, rows in tables.items()},
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "currency": "CNY",
        },
    )


def seed_database(url: str, dataset: Dataset) -> dict:
    """Atomic insert only; refuse a nonempty database. No truncate/overwrite capability."""
    engine = sa.create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 5})
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL lock_timeout='5s'")
            conn.exec_driver_sql("SELECT pg_advisory_xact_lock(17358001)")
            for name in (*BUSINESS_TABLES, "seed_runs"):
                table = metadata.tables["saas." + name]
                if conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one():
                    raise ValueError("Seed refuses a nonempty database")
            for name in BUSINESS_TABLES:
                conn.execute(metadata.tables["saas." + name].insert(), dataset.tables[name])
            conn.execute(seed_runs.insert().values(seed_id=1, manifest=dataset.manifest))
        return dataset.manifest
    finally:
        engine.dispose()
