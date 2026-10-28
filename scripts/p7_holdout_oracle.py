"""Independent source-record oracle; never imports Agent, recipes or business Verifier."""

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

import sqlglot
from sqlglot import exp

from datapilot.tools.sql import validate_sql

TABLES = {
    "invoices": {
        "invoice_id": "TEXT",
        "customer_id": "TEXT",
        "amount": "DECIMAL",
        "invoice_date": "DATE",
        "payment_status": "TEXT",
        "currency": "TEXT",
    },
    "subscriptions": {
        "subscription_id": "TEXT",
        "customer_id": "TEXT",
        "start_date": "DATE",
        "end_date": "DATE",
        "termination_kind": "TEXT",
    },
    "usage_events": {
        "event_id": "TEXT",
        "event_date": "DATE",
        "event_count": "INT",
        "feature": "TEXT",
    },
    "customers": {"customer_id": "TEXT", "segment": "TEXT"},
}


def oracle(records, policy, request):
    kind = policy["metric_id"]
    entity = (
        "invoices"
        if kind == "paid_invoice_revenue"
        else "usage_events"
        if kind == "usage"
        else "subscriptions"
    )
    unit = (
        policy.get("currency", "CNY")
        if kind in {"paid_invoice_revenue", "mrr"}
        else "events"
        if kind == "usage"
        else "subscriptions"
        if kind == "active_subscriptions"
        else "ratio"
    )

    def unavailable(reason):
        return {"disposition": "unavailable", "reason": reason, "value": None, "unit": unit}

    if kind == "mrr":
        return unavailable("recurring_contract_definition_missing")
    if entity not in records:
        return unavailable("entity_missing")
    if entity == "invoices" and policy.get("amount_storage") not in {"minor", "major"}:
        return unavailable("amount_unit_unconfirmed")
    if entity == "invoices" and policy.get("currency", "CNY") != "CNY":
        return unavailable("currency_not_supported")
    if entity == "subscriptions" and not policy.get("history_complete", True):
        return unavailable("complete_contract_history_missing")
    window = request.get("window")
    start, end = (window["start"], window["end_exclusive"]) if window else (None, None)
    at = request.get("as_of")
    lower, upper = policy["coverage"]
    if (at and not lower <= at < upper) or (window and not lower <= start < end <= upper):
        return unavailable("outside_confirmed_coverage")
    rows = records[entity]
    key = {
        "invoices": "invoice_id",
        "subscriptions": "subscription_id",
        "usage_events": "event_id",
    }[entity]
    if len({r[key] for r in rows}) != len(rows):
        return unavailable("duplicate_record_grain")
    if entity == "invoices" and any(
        r["amount"] is None or Decimal(str(r["amount"])) < 0 for r in rows
    ):
        return unavailable("invalid_amount")
    if kind == "usage" and any(
        type(r["event_count"]) is not int or r["event_count"] < 0 for r in rows
    ):
        return unavailable("invalid_event_count")
    result = {"disposition": "verified", "unit": unit}
    if kind == "paid_invoice_revenue":
        amount = sum(
            (
                Decimal(str(r["amount"]))
                for r in rows
                if start <= r["invoice_date"] < end
                and r["payment_status"] in policy.get("paid_values", ["paid"])
                and r["currency"] == policy.get("currency", "CNY")
            ),
            Decimal(0),
        )
        result["value"] = str(amount / (100 if policy["amount_storage"] == "minor" else 1))
    elif kind == "usage":
        result["value"] = str(
            sum(
                r["event_count"]
                for r in rows
                if start <= r["event_date"] < end
                and (policy.get("feature") is None or r["feature"] == policy["feature"])
            )
        )
    elif kind == "active_subscriptions":
        result["value"] = str(
            sum(
                r["start_date"] <= at and (r["end_date"] is None or r["end_date"] > at)
                for r in rows
            )
        )
    else:
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
                and r["termination_kind"] in policy.get("churn_values", ["churned"])
                for r in cohort
            )
        else:
            customers = {r["customer_id"] for r in cohort}
            denominator = len(customers)
            remaining = {
                r["customer_id"]
                for r in rows
                if r["start_date"] < end and (r["end_date"] is None or r["end_date"] >= end)
            }
            numerator = len(customers - remaining)
        if not denominator:
            return unavailable("zero_denominator")
        with localcontext() as context:
            context.prec = 40
            result["value"] = str(
                (Decimal(numerator) / denominator).quantize(
                    Decimal(".000000000001"), rounding=ROUND_HALF_EVEN
                )
            )
        result.update(numerator=numerator, denominator=denominator)
    if window:
        result["window_days"] = (date.fromisoformat(end) - date.fromisoformat(start)).days
    return result


def literal(value, kind="TEXT"):
    value = exp.Null() if value is None else exp.Literal.string(str(value))
    return exp.Cast(this=value, to=exp.DataType.build(kind)).sql(dialect="postgres")


def reference_sql(records, policy, request):
    """Only a bounded literal relation, never an existing business/catalog table."""
    entity = (
        "invoices"
        if policy["metric_id"] == "paid_invoice_revenue"
        else "usage_events"
        if policy["metric_id"] == "usage"
        else "subscriptions"
    )
    tables = [entity] + (["customers"] if policy.get("reference_join") else [])
    definitions = []
    for name in tables:
        columns = TABLES[name]
        rows = records[name]
        if not 1 <= len(rows) <= 40:
            raise ValueError("Bounded nonempty synthetic oracle relations only")
        values = ",".join(
            "(" + ",".join(literal(r.get(c), t) for c, t in columns.items()) + ")" for r in rows
        )
        definitions.append(f"oracle_{name}(" + ",".join(columns) + ") AS (VALUES " + values + ")")
    source = f"oracle_{entity}"
    kind = policy["metric_id"]
    window = request.get("window")
    start, end = (
        (literal(window["start"], "DATE"), literal(window["end_exclusive"], "DATE"))
        if window
        else (None, None)
    )
    if kind == "paid_invoice_revenue":
        paid = ",".join(literal(s) for s in policy.get("paid_values", ["paid"]))
        join = (
            " JOIN oracle_customers c ON c.customer_id=i.customer_id"
            if policy.get("reference_join")
            else ""
        )
        divisor = 100 if policy["amount_storage"] == "minor" else 1
        query = (
            f"SELECT COALESCE(SUM(i.amount),0)/{divisor} AS value FROM {source} i{join} "
            f"WHERE i.invoice_date>={start} AND i.invoice_date<{end} "
            f"AND i.payment_status IN ({paid}) "
            f"AND i.currency={literal(policy.get('currency', 'CNY'))}"
        )
    elif kind == "usage":
        feature = (
            "" if policy.get("feature") is None else f" AND feature={literal(policy['feature'])}"
        )
        query = (
            f"SELECT COALESCE(SUM(event_count),0) AS value FROM {source} "
            f"WHERE event_date>={start} AND event_date<{end}{feature}"
        )
    elif kind == "active_subscriptions":
        at = literal(request["as_of"], "DATE")
        query = (
            f"SELECT COUNT(*) AS value FROM {source} WHERE start_date<={at} "
            f"AND (end_date IS NULL OR end_date>{at})"
        )
    elif kind == "subscription_churn":
        churn = ",".join(literal(s) for s in policy.get("churn_values", ["churned"]))
        cohort = f"start_date<{start} AND (end_date IS NULL OR end_date>={start})"
        query = (
            f"SELECT COUNT(*) AS denominator,(SELECT COUNT(*) FROM {source} "
            f"WHERE {cohort} AND end_date>={start} AND end_date<{end} "
            f"AND termination_kind IN ({churn})) AS numerator FROM {source} WHERE {cohort}"
        )
    elif kind == "customer_churn":
        query = (
            f"SELECT COUNT(DISTINCT a.customer_id) AS denominator,"
            f"(SELECT COUNT(*) FROM (SELECT c.customer_id FROM {source} c "
            f"WHERE c.start_date<{start} AND (c.end_date IS NULL OR c.end_date>={start}) "
            f"EXCEPT SELECT b.customer_id FROM {source} b "
            f"WHERE b.start_date<{end} AND (b.end_date IS NULL OR b.end_date>={end})) lost) "
            f"AS numerator FROM {source} a "
            f"WHERE a.start_date<{start} AND (a.end_date IS NULL OR a.end_date>={start})"
        )
    else:
        raise ValueError("No reference SQL for an unsupported metric")
    sql = validate_sql("WITH " + ",".join(definitions) + " " + query)
    tree = sqlglot.parse_one(sql, read="postgres")
    if any(t.db or not t.name.startswith("oracle_") for t in tree.find_all(exp.Table)):
        raise ValueError("Oracle may not read any physical table")
    return sql
