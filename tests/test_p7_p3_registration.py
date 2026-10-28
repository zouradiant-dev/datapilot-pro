"""Public synthetic confirmation contracts; never reads sealed Gold or writes a database."""

import importlib
import json
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from datapilot.semantics.contracts import MetricDraft, SemanticDraft


@pytest.fixture
def registration(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("p7_confirm_p3")


@pytest.fixture
def approved(registration, monkeypatch):
    entries = []
    for n in range(34):
        kind = "semantic" if n < 12 or n == 32 else "metric"
        dataset = str(UUID(int=n + 1))
        draft = (
            SemanticDraft(
                dataset_id=dataset,
                dataset_version=1,
                entities=[
                    {
                        "entity": "invoices",
                        "table_id": "table_1",
                        "fields": {"record_id": "id"},
                        "grain": ["id"],
                    }
                ],
            )
            if kind == "semantic"
            else MetricDraft(
                dataset_id=dataset,
                dataset_version=1,
                semantic_version=1,
                metric_id="paid_invoice_revenue",
            )
        )
        identity = {
            "kind": kind,
            "dataset_id": dataset,
            "dataset_version": 1,
            "semantic_version": 1,
            "definition_sha256": registration.digest(draft),
        }
        if kind == "metric":
            identity.update(metric_id="paid_invoice_revenue", metric_version=1)
        entries.append(
            {
                "category": ("A_" if n < 26 else "B_" if n < 32 else "C_") + "public_test",
                "identity": identity,
                "entry_id": registration.sha(registration.canonical(identity)),
                "definition": draft.model_dump(mode="json"),
            }
        )
    raw = json.dumps({"entries": entries}).encode()
    digest = registration.sha(raw)
    monkeypatch.setattr(registration, "REQUEST_SHA", digest)
    approval = {
        "authority": "direct_user_message",
        "approved_by_role": "project_owner",
        "request_sha256": digest,
        "approved_groups": ["A", "B"],
        "excluded_groups": ["C"],
        "paid_live_authorized": False,
        "source_user_decision_ref": "public-test-only",
    }
    return raw, approval


@pytest.mark.parametrize("mutation", ["bytes", "role", "scope", "paid"])
def test_explicit_approval_is_exact_and_cannot_expand(registration, approved, mutation):
    raw, approval = approved
    if mutation == "bytes":
        raw += b" "
    elif mutation == "role":
        approval["approved_by_role"] = "model"
    elif mutation == "scope":
        approval["approved_groups"].append("C")
    else:
        approval["paid_live_authorized"] = True
    with pytest.raises(ValueError, match="owner approval"):
        registration.approved_entries(raw, approval)


def test_only_approved_entries_and_semantics_before_metrics(registration, approved):
    raw, approval = approved
    entries = registration.approved_entries(raw, approval)
    assert len(entries) == 32
    assert all(e["category"][0] in {"A", "B"} for e in entries)
    assert [e["identity"]["kind"] for e in entries] == ["semantic"] * 12 + ["metric"] * 20
    assert raw == approved[0]


def test_row_comparison_preserves_numeric_precision_and_duplicates(registration):
    a = [["中文", "9007199254740993.1200"], ["另一个", None]]
    b = [["另一个", None], ["中文", "9007199254740993.12"]]
    assert registration.rows_hash(a, ["TEXT", "NUMERIC"]) == registration.rows_hash(
        b, ["TEXT", "NUMERIC"]
    )
    assert registration.rows_hash(a, ["TEXT", "NUMERIC"]) != registration.rows_hash(
        a + a, ["TEXT", "NUMERIC"]
    )


@pytest.mark.parametrize("conflict", ["none", "paid", "coverage", "unit"])
def test_explicit_zero_coverage_does_not_guess_or_count_april(registration, conflict):
    window = SimpleNamespace(
        start=date(2023, 3, 1),
        end_exclusive=date(2023, 4, 1),
        model_dump=lambda **k: {"start": "2023-03-01", "end_exclusive": "2023-04-01"},
    )
    task = SimpleNamespace(case_id="public-zero", metrics=[SimpleNamespace(window=window)])
    entity = {
        "entity": "invoices",
        "coverage_start": "2023-01-01",
        "coverage_end_exclusive": "2024-01-01",
        "timezone": "UTC",
        "amount_storage": "minor",
    }
    metric = {"paid_values": ["paid"], "currency": "CNY"}
    rows = [
        {
            "payment_status": "unpaid",
            "invoice_date": "2023-03-05",
            "currency": "CNY",
            "amount": "151",
        },
        {
            "payment_status": "paid",
            "invoice_date": "2023-04-01",
            "currency": "CNY",
            "amount": "4271",
        },
    ]
    if conflict == "paid":
        rows[0]["payment_status"] = "paid"
    elif conflict == "coverage":
        entity["coverage_start"] = "2023-03-02"
    elif conflict == "unit":
        entity["amount_storage"] = None
    if conflict != "none":
        with pytest.raises(ValueError):
            registration.zero_coverage_check(task, {"entities": [entity]}, metric, rows)
    else:
        value = registration.zero_coverage_check(task, {"entities": [entity]}, metric, rows)
        assert value["independent_decimal_value"] == "0" and not value["p3_verified_claim"]


def test_append_uses_original_confirmation_api_only(registration, approved, monkeypatch, tmp_path):
    entries = registration.approved_entries(*approved)
    calls = []

    def confirm(draft, *, reviewed):
        assert reviewed is True
        calls.append(draft)
        return SimpleNamespace(
            semantic_version=1,
            metric_version=1,
            definition_sha256=registration.digest(draft),
            model_dump=lambda **k: {"test_record": True},
        )

    store = SimpleNamespace(confirm_semantics=confirm, confirm_metric=confirm, close=lambda: None)
    monkeypatch.setattr(registration, "RegistryStore", lambda url: store)
    monkeypatch.setattr(
        registration,
        "environment",
        lambda: {"DATAPILOT_REGISTRY_DATABASE_URL": "public-test-not-a-dsn"},
    )
    monkeypatch.setattr(registration, "validate_registry", lambda *a: None)
    monkeypatch.setattr(
        registration, "check_exclusions", lambda *a: {"excluded_c_definitions_absent": 2}
    )
    monkeypatch.setattr(registration, "OUTPUT", tmp_path)
    receipt = {"registry_writes": 0, "targeted_checks": [{"definition_conflict": False}]}
    registration.apply(entries, approved[1], receipt)
    assert len(calls) == 32
    assert sum(isinstance(d, SemanticDraft) for d in calls) == 12
    assert len(list(tmp_path.glob("*.json"))) == 33


def test_source_conflict_prevents_every_append(registration, approved, monkeypatch):
    entries = registration.approved_entries(*approved)
    monkeypatch.setattr(
        registration, "RegistryStore", lambda url: pytest.fail("Must not open writer")
    )
    with pytest.raises(ValueError, match="Source checks"):
        registration.apply(
            entries,
            approved[1],
            {"registry_writes": 0, "targeted_checks": [{"definition_conflict": True}]},
        )


def test_missing_dataset_uses_requested_version_not_authorized_binding(
    registration, monkeypatch, tmp_path
):
    private = tmp_path / "private"
    private.mkdir()
    (private / "p3-confirmation-request.json").write_text('{"entries":[]}', encoding="utf-8")
    metric = SimpleNamespace(
        dataset_id="public-test",
        dataset_version=1,
        metric_id="paid_invoice_revenue",
        metric_version=999999,
    )
    requested = SimpleNamespace(dataset_id="public-test", dataset_version=999999)
    tasks = [
        SimpleNamespace(case_id="bh2-019", metrics=[metric]),
        SimpleNamespace(
            case_id="bh2-048",
            metrics=[requested],
            datasets=SimpleNamespace(bindings=[SimpleNamespace(version=2)]),
        ),
    ]
    seen = []

    def scalar(query):
        params = query.compile().params
        seen.append(params)
        # Authorized v2 exists; the deliberately requested v999999 does not.
        return int(params.get("version_1", 999999) != 999999)

    connection = SimpleNamespace(scalar=scalar)
    store = SimpleNamespace(
        engine=SimpleNamespace(begin=lambda: nullcontext(connection)), _configure=lambda c: None
    )
    monkeypatch.setattr(registration, "BASE", tmp_path)
    monkeypatch.setattr(registration, "load_v2", lambda: (tasks, {}, {}))
    result = registration.check_exclusions(store)
    assert result["dataset_999999_absent"] and seen[-1]["version_1"] == 999999
