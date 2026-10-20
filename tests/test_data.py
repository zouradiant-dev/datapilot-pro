from datetime import date

import pytest

from datapilot.data.generator import generate_dataset


def test_determinism_and_business_relations():
    dataset = generate_dataset()
    assert dataset == generate_dataset()
    assert (
        dataset.manifest["content_sha256"] != generate_dataset(seed=43).manifest["content_sha256"]
    )
    t = dataset.tables
    assert len(t["customers"]) == 240
    customers = {c["customer_id"]: c for c in t["customers"]}
    subscriptions = {s["subscription_id"]: s for s in t["subscriptions"]}
    assert {s["status"] for s in subscriptions.values()} == {"active", "churned", "downgraded"}
    for s in subscriptions.values():
        assert s["customer_id"] in customers
        assert s["start_date"] >= customers[s["customer_id"]]["created_at"]
    for table, date_field in (
        ("invoices", "invoice_date"),
        ("usage_events", "event_date"),
        ("customer_feedback", "submitted_at"),
    ):
        for row in t[table]:
            s = subscriptions[row["subscription_id"]]
            assert s["start_date"] <= row[date_field] < (s["end_date"] or date(2026, 1, 1))
            if table == "customer_feedback":
                assert row["customer_id"] == s["customer_id"]
    usage = {"early": [], "late": []}
    for row in t["usage_events"]:
        c = customers[subscriptions[row["subscription_id"]]["customer_id"]]
        if c["segment"] == "small" and c["industry"] == "retail":
            usage["early" if row["event_date"].month < 7 else "late"].append(row["event_count"])
    assert sum(usage["early"]) / len(usage["early"]) > 2 * sum(usage["late"]) / len(usage["late"])


def test_bad_size():
    with pytest.raises(ValueError):
        generate_dataset(customers=0)
