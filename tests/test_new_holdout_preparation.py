"""Public compilation controls; expectations stay outside candidate input contracts."""

import json
from decimal import Decimal

from test_holdout_candidate_preparation import candidate as candidate
from test_new_holdout_scoring import new_partial as new_partial
from test_p7_current_citation_scoring import example as example
from test_p7_partial_evidence_scoring import partial as partial
from test_p7_scorer_versions import case as case

from evaluation.p7_v3_current.holdout_contracts import compile_drafts
from evaluation.p7_v3_current.holdout_preparation import LANES
from evaluation.p7_v3_current.holdout_review import raw_numeric


def test_compile_sixty_drafts_does_not_approve_goals_or_leak_gold(new_partial, candidate):
    task = new_partial.task
    dataset = {"dataset_id": "00000000-0000-4000-8000-000000000009", "version": 1}
    metric = {
        "goal_id": "metric_1",
        "dataset_id": dataset["dataset_id"],
        "dataset_version": dataset["version"],
        "semantic_version": 1,
        "metric_id": "usage",
        "metric_version": 3,
        "window": {"start": "2032-02-01", "end_exclusive": "2032-03-01"},
    }
    corpus = {"scope": task.rag_scope.model_dump(mode="json")}
    corpus["scope"]["datasets"] = {"bindings": [dataset]}
    rows, previous = [], []
    for lane, prefix in LANES.items():
        for i in range(1, 21):
            cid = f"g2-bh-{prefix}-{i:03}"
            rows.append(
                {
                    "id": cid,
                    "lane": lane,
                    "question": task.question,
                    "tags": [],
                    "expected_status": "partial",
                    "oracle": {"private_sentinel": "GOLD_ONLY"},
                    "source_groups": ["public"] if lane != "sql_only" else [],
                    "document_goal": {"purpose": "fact_lookup"},
                    "required_facts": [{"fact_id": "fact_1", "span_intent": "Known public fact"}],
                }
            )
            previous.append(
                {
                    "case_id": cid,
                    "document_facts": [],
                    **({"metric_request": metric} if lane != "rag_only" else {}),
                }
            )
    cases, reviews, metadata = compile_drafts(
        rows, {"corpora": {"public": corpus}}, previous, [], candidate
    )
    assert len(cases) == len(reviews) == 60
    assert metadata["live_allowed"] is False
    serialized = json.dumps([c.model_dump(mode="json") for c in cases])
    assert "GOLD_ONLY" not in serialized
    assert "expected_status" not in serialized
    assert sum(c.document_goal is not None for c in cases) == 40
    assert all(c.report_scope.goal_scope_attestation is None for c in cases)
    assert all(c.report_scope.partial_evidence_policy == "legacy" for c in cases)
    assert all(r["proposed_scope_is_approved"] is False for r in reviews)
    assert all(r["launch"] == "NOT_READY" for r in reviews)


def test_revised_raw_oracle_preserves_right_open_dates_currency_and_subscription_end():
    sheets = {
        "invoices": [
            {
                "invoice_date": "2032-02-01",
                "amount_cents": 101,
                "payment_status": "paid",
                "currency": "CNY",
            },
            {
                "invoice_date": "2032-02-02",
                "amount_cents": 900,
                "payment_status": "pending",
                "currency": "CNY",
            },
            {
                "invoice_date": "2032-02-02",
                "amount_cents": 800,
                "payment_status": "paid",
                "currency": "EUR",
            },
            {
                "invoice_date": "2032-02-03",
                "amount_cents": 700,
                "payment_status": "paid",
                "currency": "CNY",
            },
        ],
        "usage_events": [
            {"event_date": "2032-02-01", "event_count": 5},
            {"event_date": "2032-02-03", "event_count": 9},
        ],
        "subscriptions": [
            {"start_date": "2032-02-01", "end_date": "2032-02-02"},
            {"start_date": "2032-02-02", "end_date": None},
        ],
    }
    window = {"window": {"start": "2032-02-01", "end_exclusive": "2032-02-03"}}
    assert raw_numeric({"metric_id": "paid_invoice_revenue", **window}, sheets) == Decimal("1.01")
    assert raw_numeric({"metric_id": "usage", "metric_version": 3, **window}, sheets) == 5
    assert raw_numeric({"metric_id": "active_subscriptions", "as_of": "2032-02-02"}, sheets) == 1
