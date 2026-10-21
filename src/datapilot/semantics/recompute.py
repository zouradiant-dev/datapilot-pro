"""Independent raw-row arithmetic; no SQL predicates or model-generated expressions."""

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from datapilot.semantics.contracts import MetricContext, MetricRequest, MetricValue
from datapilot.semantics.recipes import scalar, unit


def compute_rows(context: MetricContext, request: MetricRequest, rows: list[dict]) -> MetricValue:
    ids = [r.get("record_id") for r in rows]
    if any(v is None or v == "" for v in ids) or len(ids) != len(set(ids)):
        raise ValueError("Record IDs must be nonnull and unique; duplicate grain cannot be summed")
    date_roles = {"invoice_date", "event_date", "start_date", "end_date"}
    for row in rows:
        for role in context.entity.fields:
            value = row[role]
            if value is None:
                if role != "end_date":
                    raise ValueError("Required semantic field is null")
                continue
            if (
                role in {"record_id", "customer_id"}
                and isinstance(value, str)
                and not value.strip()
            ):
                raise ValueError("Business identifiers cannot be empty")
            if role in date_roles:
                row[role] = date.fromisoformat(value)
            elif role in {"amount", "event_count"}:
                number = scalar(value)
                if number < 0 or (role == "event_count" and number != number.to_integral_value()):
                    raise ValueError(
                        "Negative amounts/refunds and fractional usage need another policy"
                    )
                if (
                    role == "amount"
                    and context.entity.amount_storage == "minor"
                    and number != number.to_integral_value()
                ):
                    raise ValueError("Minor currency units must be integral")
                row[role] = number
        if (
            "start_date" in row
            and row.get("end_date") is not None
            and row["end_date"] < row["start_date"]
        ):
            raise ValueError("Subscription interval ends before it starts")
        if request.metric_id == "subscription_churn" and row.get("end_date") is not None:
            allowed = context.definition.churn_values + context.definition.non_churn_end_values
            if row["termination_kind"] not in allowed:
                raise ValueError("Ended subscription has an unclassified termination kind")
    start = request.window.start if request.window else None
    end = request.window.end_exclusive if request.window else None
    days = (end - start).days if start else None
    with localcontext() as arithmetic:
        arithmetic.prec = 60
        if request.metric_id == "paid_invoice_revenue":
            selected = [
                r
                for r in rows
                if r["payment_status"] in context.definition.paid_values
                and start <= r["invoice_date"] < end
                and r.get("currency", context.entity.currency_constant)
                == context.definition.currency
            ]
            number = sum((r["amount"] for r in selected), Decimal(0))
            if context.entity.amount_storage == "minor":
                number /= Decimal(100)
        elif request.metric_id == "usage":
            number = sum(
                (
                    r["event_count"]
                    for r in rows
                    if start <= r["event_date"] < end
                    and (
                        context.definition.feature is None
                        or r["feature"] == context.definition.feature
                    )
                ),
                Decimal(0),
            )
        elif request.metric_id == "active_subscriptions":
            number = Decimal(
                sum(
                    r["start_date"] <= request.as_of
                    and (r["end_date"] is None or r["end_date"] > request.as_of)
                    for r in rows
                )
            )
        else:
            cohort = [
                r
                for r in rows
                if r["start_date"] < start and (r["end_date"] is None or r["end_date"] >= start)
            ]
            if request.metric_id == "subscription_churn":
                denominator = len(cohort)
                numerator = sum(
                    r["end_date"] is not None
                    and start <= r["end_date"] < end
                    and r["termination_kind"] in context.definition.churn_values
                    for r in cohort
                )
            elif request.metric_id == "customer_churn":
                customers = {r["customer_id"] for r in cohort}
                retained = {
                    r["customer_id"]
                    for r in rows
                    if r["start_date"] < end and (r["end_date"] is None or r["end_date"] >= end)
                }
                denominator, numerator = len(customers), len(customers - retained)
            else:
                raise ValueError("No deterministic recipe")
            if not denominator:
                raise ValueError("Empty starting cohort: churn denominator is zero")
            ratio = (Decimal(numerator) / Decimal(denominator)).quantize(
                Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN
            )
            return MetricValue(
                value=format(ratio, "f"),
                unit="ratio",
                numerator=numerator,
                denominator=denominator,
                window_days=days,
            )
    return MetricValue(value=format(number, "f"), unit=unit(context), window_days=days)
