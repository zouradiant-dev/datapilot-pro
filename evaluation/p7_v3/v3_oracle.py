"""Independent raw synthetic-source Decimal and SQL oracle. No product recipe imports."""

from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from v3_sources import variants

WINDOWS = {
    "feb": ("2032-02-01", "2032-03-01"),
    "march": ("2032-03-01", "2032-04-01"),
    "march_first": ("2032-03-01", "2032-03-02"),
    "leap_day": ("2032-02-29", "2032-03-01"),
    "outside": ("2030-12-01", "2031-01-01"),
}
ASOF = {"change": "2032-02-10", "last": "2032-02-29", "end": "2032-03-01"}


def source_rows(alias, name):
    rows = variants()[alias][name]
    return [dict(zip(rows[0], row, strict=True)) for row in rows[1:]]


def answer(alias, kind, version, period):
    unit = (
        "EUR"
        if kind == "paid_invoice_revenue" and version == 2
        else "CNY"
        if kind == "paid_invoice_revenue"
        else "events"
        if kind == "usage"
        else "subscriptions"
        if kind == "active_subscriptions"
        else "CNY/month"
        if kind == "mrr"
        else "ratio"
    )
    reason = (
        "mrr_definition_missing"
        if kind == "mrr"
        else "currency_unsupported"
        if unit == "EUR"
        else "amount_unit_unconfirmed"
        if alias == "unconfirmed_unit" and kind == "paid_invoice_revenue"
        else "history_unconfirmed"
        if alias == "incomplete_history"
        and kind in {"customer_churn", "subscription_churn", "active_subscriptions"}
        else "outside_coverage"
        if period == "outside"
        else "duplicate_record_grain"
        if alias == "duplicate" and kind == "usage"
        else "data_not_verifiable"
        if alias == "null_amount" and kind == "paid_invoice_revenue"
        else None
    )
    if reason:
        return {"disposition": "unavailable", "unit": unit, "value": None, "reason": reason}
    start, end = WINDOWS.get(period, (None, None))
    with localcontext() as ctx:
        ctx.prec = 60
        if kind == "paid_invoice_revenue":
            chosen = [
                r
                for r in source_rows(alias, "invoices")
                if start <= r["invoice_date"] < end
                and r["payment_status"] == "paid"
                and r["currency"] == "CNY"
            ]
            value = sum((Decimal(str(r["amount_cents"])) for r in chosen), Decimal(0))
            if alias != "major":
                value /= 100
        elif kind == "usage":
            feature = {1: "export_batch", 2: "webhook_delivery", 3: None}[version]
            value = Decimal(
                sum(
                    r["event_count"]
                    for r in source_rows(alias, "usage_events")
                    if start <= r["event_date"] < end
                    and (feature is None or r["feature"] == feature)
                )
            )
        elif kind == "active_subscriptions":
            value = Decimal(
                sum(
                    r["start_date"] <= ASOF[period]
                    and (r["end_date"] is None or r["end_date"] > ASOF[period])
                    for r in source_rows(alias, "subscriptions")
                )
            )
        else:
            rows = source_rows(alias, "subscriptions")
            cohort = [
                r
                for r in rows
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
                initial = {r["customer_id"] for r in cohort}
                remaining = {
                    r["customer_id"]
                    for r in rows
                    if r["start_date"] < end and (r["end_date"] is None or r["end_date"] >= end)
                }
                denominator, numerator = len(initial), len(initial - remaining)
            if not denominator:
                return {
                    "disposition": "unavailable",
                    "unit": unit,
                    "value": None,
                    "reason": "zero_denominator",
                }
            value = (Decimal(numerator) / Decimal(denominator)).quantize(
                Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN
            )
            return {
                "disposition": "verified",
                "unit": unit,
                "value": format(value, "f"),
                "numerator": numerator,
                "denominator": denominator,
            }
        return {"disposition": "verified", "unit": unit, "value": format(value, "f")}


def query(alias, kind, version, period, schema):
    """Independent query against actual scoped uploads; not the SQL Agent recipe."""
    tables = {t["source_name"]: '"' + t["physical_name"] + '"' for t in schema["tables"]}
    name = tables[
        "invoices"
        if kind == "paid_invoice_revenue"
        else "usage_events"
        if kind == "usage"
        else "subscriptions"
    ]
    start, end = WINDOWS.get(period, (None, None))
    if kind == "paid_invoice_revenue":
        scale = "" if alias == "major" else "::numeric/100"
        return (
            f"SELECT COALESCE(SUM(amount_cents),0){scale} AS oracle_value FROM {name} "
            f"WHERE invoice_date >= DATE '{start}' AND invoice_date < DATE '{end}' "
            "AND payment_status='paid' AND currency='CNY'"
        )
    if kind == "usage":
        feature = {1: "export_batch", 2: "webhook_delivery", 3: None}[version]
        extra = f" AND feature='{feature}'" if feature else ""
        return (
            f"SELECT COALESCE(SUM(event_count),0) AS oracle_value FROM {name} "
            f"WHERE event_date >= DATE '{start}' AND event_date < DATE '{end}'{extra}"
        )
    if kind == "active_subscriptions":
        return (
            f"SELECT COUNT(*) AS oracle_value FROM {name} WHERE start_date<=DATE '{ASOF[period]}' "
            f"AND (end_date IS NULL OR end_date>DATE '{ASOF[period]}')"
        )
    cohort = f"start_date<DATE '{start}' AND (end_date IS NULL OR end_date>=DATE '{start}')"
    if kind == "subscription_churn":
        return (
            f"SELECT COUNT(*) FILTER (WHERE end_date>=DATE '{start}' "
            f"AND end_date<DATE '{end}' AND termination_kind='churned') AS n,"
            f"COUNT(*) AS d FROM {name} WHERE {cohort}"
        )
    return (
        f"WITH initial AS (SELECT DISTINCT customer_id FROM {name} WHERE {cohort}), "
        f"retained AS (SELECT DISTINCT customer_id FROM {name} WHERE start_date<DATE '{end}' "
        f"AND (end_date IS NULL OR end_date>=DATE '{end}')) "
        "SELECT COUNT(*)-COUNT(retained.customer_id) AS n,COUNT(*) AS d "
        "FROM initial LEFT JOIN retained ON initial.customer_id=retained.customer_id"
    )
