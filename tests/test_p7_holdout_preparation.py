"""Small public contract fixtures; never open or execute the actual sealed business set."""

import importlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return (
        importlib.import_module("p7_holdout_oracle"),
        importlib.import_module("p7_holdout_pack"),
        importlib.import_module("prepare_p7_business_holdout"),
    )


def policy(kind, **extra):
    return {
        "metric_id": kind,
        "coverage": ["2031-01-01", "2032-01-01"],
        "currency": "CNY",
        "amount_storage": "minor",
        "history_complete": True,
        **extra,
    }


WINDOW = {"window": {"start": "2031-02-01", "end_exclusive": "2031-03-01"}}


def invoice(id_, amount, date="2031-02-05", status="paid", currency="CNY"):
    return {
        "invoice_id": id_,
        "customer_id": "toy-customer",
        "amount": amount,
        "invoice_date": date,
        "payment_status": status,
        "currency": currency,
    }


def test_independent_money_oracle_checks_units_filters_and_half_open(modules):
    o, _, _ = modules
    rows = [
        invoice("i1", 101),
        invoice("i2", 202),
        invoice("i3", 999, status="unpaid"),
        invoice("i4", 888, currency="USD"),
        invoice("i5", 777, date="2031-03-01"),
    ]
    assert o.oracle({"invoices": rows}, policy("paid_invoice_revenue"), WINDOW)["value"] == "3.03"
    major = [invoice("m1", "0.10"), invoice("m2", "0.20")]
    assert (
        o.oracle(
            {"invoices": major}, policy("paid_invoice_revenue", amount_storage="major"), WINDOW
        )["value"]
        == "0.30"
    )
    assert (
        o.oracle(
            {"invoices": [invoice("u", 10, status="unpaid")]},
            policy("paid_invoice_revenue"),
            WINDOW,
        )["value"]
        == "0"
    )


@pytest.mark.parametrize(
    "alter,reason",
    [
        ({"currency": "USD"}, "currency_not_supported"),
        ({"amount_storage": None}, "amount_unit_unconfirmed"),
        ({"metric_id": "mrr"}, "recurring_contract_definition_missing"),
    ],
)
def test_missing_policy_never_becomes_a_gold_number(modules, alter, reason):
    o, _, _ = modules
    result = o.oracle(
        {"invoices": [invoice("a", 1)]}, policy("paid_invoice_revenue", **alter), WINDOW
    )
    assert (
        result["disposition"] == "unavailable"
        and result["value"] is None
        and result["reason"] == reason
    )


def test_contract_customer_and_rejoined_contract_denominators_are_different(modules):
    o, _, _ = modules
    rows = [
        {
            "subscription_id": "s1",
            "customer_id": "a",
            "start_date": "2031-01-01",
            "end_date": "2031-02-09",
            "termination_kind": "churned",
        },
        {
            "subscription_id": "s2",
            "customer_id": "a",
            "start_date": "2031-02-15",
            "end_date": None,
            "termination_kind": "active",
        },
        {
            "subscription_id": "s3",
            "customer_id": "b",
            "start_date": "2031-01-05",
            "end_date": "2031-02-12",
            "termination_kind": "downgraded",
        },
        {
            "subscription_id": "s4",
            "customer_id": "c",
            "start_date": "2031-01-07",
            "end_date": "2031-03-01",
            "termination_kind": "churned",
        },
        {
            "subscription_id": "s5",
            "customer_id": "c",
            "start_date": "2031-01-09",
            "end_date": None,
            "termination_kind": "active",
        },
    ]
    records = {"subscriptions": rows}
    sub = o.oracle(records, policy("subscription_churn"), WINDOW)
    customer = o.oracle(records, policy("customer_churn"), WINDOW)
    assert (sub["numerator"], sub["denominator"]) == (1, 4)
    assert (customer["numerator"], customer["denominator"]) == (1, 3)
    assert sub["value"] == "0.250000000000"
    assert customer["value"] == "0.333333333333"
    for kind in ["subscription_churn", "customer_churn", "active_subscriptions"]:
        request = {"as_of": "2031-02-15"} if kind == "active_subscriptions" else WINDOW
        assert o.reference_sql(records, policy(kind), request)
    active = o.oracle(records, policy("active_subscriptions"), {"as_of": "2031-02-15"})
    assert active["value"] == "3"
    assert (
        o.oracle(records, policy("customer_churn", history_complete=False), WINDOW)["value"] is None
    )


def test_duplicates_zero_denominator_and_coverage_are_not_filled_in(modules):
    o, _, _ = modules
    records = {"invoices": [invoice("same", 1), invoice("same", 2)]}
    assert (
        o.oracle(records, policy("paid_invoice_revenue"), WINDOW)["reason"]
        == "duplicate_record_grain"
    )
    assert (
        o.oracle({"subscriptions": []}, policy("customer_churn"), WINDOW)["reason"]
        == "zero_denominator"
    )
    outside = {"window": {"start": "2030-01-01", "end_exclusive": "2030-02-01"}}
    assert (
        o.oracle({"invoices": [invoice("a", 1)]}, policy("paid_invoice_revenue"), outside)["reason"]
        == "outside_confirmed_coverage"
    )


def test_usage_feature_and_negative_count(modules):
    o, _, _ = modules
    rows = [
        {"event_id": "a", "event_date": "2031-02-01", "event_count": 3, "feature": "api"},
        {"event_id": "b", "event_date": "2031-02-28", "event_count": 7, "feature": "export"},
    ]
    assert o.oracle({"usage_events": rows}, policy("usage", feature="api"), WINDOW)["value"] == "3"
    rows[0]["event_count"] = -1
    assert o.oracle({"usage_events": rows}, policy("usage"), WINDOW)["value"] is None


def test_reference_sql_cannot_escape_literal_relations(modules):
    import sqlglot
    from sqlglot import exp

    o, _, _ = modules
    malicious = invoice("x'); DROP TABLE saas.customers; --", 101)
    query = o.reference_sql({"invoices": [malicious]}, policy("paid_invoice_revenue"), WINDOW)
    trees = sqlglot.parse(query, read="postgres")
    assert len(trees) == 1 and not list(trees[0].find_all(exp.Drop))
    assert all(t.name.startswith("oracle_") and not t.db for t in trees[0].find_all(exp.Table))


def test_old_question_extraction_does_not_parse_gold(modules):
    _, p, _ = modules
    # Invalid expected JSON would fail a full decoder; input extraction must not visit it.
    raw = b'{"case_id":"old","question":"quoted \\"word\\"", "expected":NOT_JSON_OR_GOLD}\n'
    assert p.old_question_inputs(raw) == [{"question": 'quoted "word"'}]


def test_input_dto_refuses_gold_and_fake_numeric_gold(modules):
    _, p, _ = modules
    with pytest.raises(ValidationError):
        p.CaseInput.model_validate_json(json.dumps({"gold": 123}))
    with pytest.raises(ValidationError):
        p.NumericGold(
            goal_id="metric_1", disposition="unavailable", value="9", unit="CNY", reason="missing"
        )


def toy_pack(p):
    tasks = []
    answers = []
    for i in range(60):
        lane = ["sql_only", "rag_only", "sql_rag"][i // 20]
        label = chr(65 + i // 26) + chr(65 + i % 26)
        question = "独立合同验证问题 " + label + "；不得计算或泄露生产数据。"
        metrics = (
            []
            if lane == "rag_only"
            else [
                {
                    "goal_id": "metric_1",
                    "dataset_id": "00000000-0000-4000-8000-000000000001",
                    "dataset_version": 1,
                    "semantic_version": 1,
                    "metric_id": "usage",
                    "metric_version": 1,
                    "window": {"start": "2031-02-01", "end_exclusive": "2031-03-01"},
                }
            ]
        )
        task = {
            "case_id": f"bh2-{i + 1:03}",
            "lane": lane,
            "objective": "独立契约目标" + label,
            "question": question,
            "owner": "toy",
            "datasets": {"bindings": []},
            "metrics": metrics,
        }
        if lane != "sql_only":
            task.update(
                document_goal={
                    "goal_id": "documents",
                    "question": question,
                    "metric_goals": [m["goal_id"] for m in metrics],
                },
                rag_scope={"owner": "toy", "corpora": []},
            )
        tasks.append(p.CaseInput.model_validate_json(json.dumps(task)))
        answers.append(
            p.Gold.model_validate_json(
                json.dumps(
                    {
                        "case_id": task["case_id"],
                        "business_completion": "unavailable",
                        "host_decision": "review_then_run",
                        "metrics": [
                            {
                                "goal_id": "metric_1",
                                "disposition": "unavailable",
                                "unit": "events",
                                "reason": "toy_missing",
                            }
                        ]
                        if metrics
                        else [],
                        "retrieval": {"disposition": "unavailable"} if lane != "sql_only" else None,
                        "refusal_conditions": ["toy_missing"],
                        "causal_claim_must_remain_unverified": False,
                    }
                )
            )
        )
    return tasks, answers


def test_seal_blocks_rewrite_gold_exposure_and_unregistered_files(modules, tmp_path):
    _, p, _ = modules
    tasks, gold = toy_pack(p)
    leakage = p.input_leakage(tasks, [], old_source_hashes=[], new_source_hashes=[])
    args = dict(
        inputs=tasks,
        gold=gold,
        assets={"note.md": b"synthetic only"},
        pins={},
        leakage=leakage,
        proof={"status": "passed", "database_writes": 0},
        freeze={},
        canary="secret-canary",
    )
    destination = tmp_path / "sealed"
    marker = p.seal(destination, **args)
    anchor = p.sha(p.canonical(marker))
    assert p.verify_seal(destination, expected_seal_sha256=anchor)["gold_decoded"] is False
    with pytest.raises(ValueError, match="overwrite"):
        p.seal(destination, **args)
    (destination / "extra.md").write_text("unexpected")
    with pytest.raises(ValueError, match="Unregistered"):
        p.verify_seal(destination, expected_seal_sha256=anchor)
    args["assets"] = {"bad.md": b"secret-canary"}
    with pytest.raises(ValueError, match="canary"):
        p.seal(tmp_path / "leaky", **args)


def test_seal_hash_rejects_gold_corruption_without_decoding(modules, tmp_path):
    _, p, _ = modules
    tasks, gold = toy_pack(p)
    leakage = p.input_leakage(tasks, [], old_source_hashes=[], new_source_hashes=[])
    marker = p.seal(
        tmp_path / "sealed",
        inputs=tasks,
        gold=gold,
        assets={},
        pins={},
        leakage=leakage,
        proof={"status": "passed", "database_writes": 0},
        freeze={},
        canary="hidden",
    )
    (tmp_path / "sealed/gold.jsonl").write_bytes(b"changed")
    with pytest.raises(ValueError, match="payload"):
        p.verify_seal(tmp_path / "sealed", expected_seal_sha256=p.sha(p.canonical(marker)))


def test_source_workbook_bytes_are_reproducible(modules, tmp_path):
    _, _, prep = modules
    records = {"invoices": [invoice("toy", 101)]}
    prep.write_source(tmp_path / "a.xlsx", records)
    prep.write_source(tmp_path / "b.xlsx", records)
    assert (tmp_path / "a.xlsx").read_bytes() == (tmp_path / "b.xlsx").read_bytes()


@pytest.mark.parametrize("source_format", ["csv", "xlsx"])
def test_null_date_roundtrip_uses_declared_file_format(modules, tmp_path, source_format):
    _, _, prep = modules
    records = {
        "subscriptions": [
            {
                "subscription_id": "toy",
                "customer_id": "c",
                "start_date": "2031-01-01",
                "end_date": None,
                "termination_kind": "active",
            }
        ]
    }
    spec = {
        "seed": 101,
        "datasets": {
            "toy": {"records": records, "format": source_format, "name": "toy", "version": 1}
        },
    }
    pins, confirmations = prep.prepare_datasets(spec, tmp_path)
    assert pins["toy"]["status"] == "planned_not_registered"
    assert confirmations["toy"]["reviewed"] is True


@pytest.mark.asyncio
async def test_relative_destination_is_resolved_and_existing_draft_preserved(
    modules, tmp_path, monkeypatch
):
    _, _, prep = modules
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prep, "ROOT", tmp_path)
    base = tmp_path / "artifacts/business"
    monkeypatch.setattr(prep, "BASE", base)
    stage = base / "sealed-draft-assets"
    stage.mkdir(parents=True)
    source = base / "spec.json"
    source.write_text("{}")
    with pytest.raises(ValueError, match="Preserve"):
        await prep.prepare(Path("artifacts/business/spec.json"), Path("artifacts/business/sealed"))
    assert stage.is_dir() and source.read_text() == "{}"
