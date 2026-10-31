"""Pilot registration/scoring adversaries and unchanged SQL-only control."""

import copy
import sys
from decimal import Decimal

import pytest
from pydantic import ValidationError

from evaluation.qwen_business_pilot.common import ROOT, load
from evaluation.qwen_business_pilot.contracts import Case, invoice_gold
from evaluation.qwen_business_pilot.scoring import score

sys.path.insert(0, str(ROOT / "scripts"))
from p7_business_scoring import authenticated, rank_metrics, sign_collection  # noqa: E402


def test_pilot_is_independent_fixed_16_and_separate_statuses():
    p = load()
    assert len(p.cases) == 16 and len({c.category for c in p.cases}) == 8
    assert {c.expected_status for c in p.cases} == {
        "completed",
        "partial",
        "unavailable",
        "blocked",
    }
    assert all(c.id.startswith("qc") for c in p.cases)
    assert sum(c.metric for c in p.cases) == 2


def test_independent_paid_currency_right_open_gold():
    p = load()
    assert invoice_gold(p) == Decimal("200.00")
    other = p.model_copy(update={"csv": p.csv.replace("2026-09-01", "2026-08-31")})
    assert invoice_gold(other) == Decimal("533.00")
    other = p.model_copy(
        update={"csv": p.csv.replace("qa-03,9000,2026-08-19,unpaid", "qa-03,9000,2026-08-19,paid")}
    )
    assert invoice_gold(other) == Decimal("290.00")


@pytest.mark.parametrize("field", ["quote", "source", "expected", "duplicate"])
def test_bad_gold_cannot_silently_confirm_facts(field):
    data = copy.deepcopy(load().cases[0].model_dump())
    if field == "quote":
        data["facts"][0][2] = "An invented fact absent from the source"
    if field == "source":
        data["required"] = ["unknown.md"]
    if field == "expected":
        data["expected_facts"] = ["invented"]
    if field == "duplicate":
        data["facts"].append(data["facts"][0])
    with pytest.raises(ValidationError):
        Case.model_validate(data)


def test_unique_source_metrics_do_not_count_duplicate_chunks_twice():
    assert rank_metrics(["one", "one", "two"], ["one", "two"])["recall"] == 1
    assert rank_metrics(["one", "one"], ["one", "two"])["recall"] == 0.5
    assert rank_metrics([], [])["recall"] is None


@pytest.mark.parametrize("field", ["run_id", "arm", "status", "facts"])
def test_collected_fake_success_or_identity_edits_are_not_authenticated(field):
    key = b"synthetic unit collector key only" * 2
    original = sign_collection(
        {"run_id": "one", "arm": "bge", "status": "partial", "facts": []}, key
    )
    original["payload"][field] = "forged-succeeded"
    with pytest.raises(ValueError):
        authenticated(original, key)


@pytest.mark.parametrize("field", ["case_id", "arm", "case_sha256", "run_id"])
def test_authenticated_wrong_case_binding_is_rejected(field):
    from datapilot.ingestion.common import digest
    from evaluation.qwen_business_pilot.common import run_id

    case, key = load().cases[0], b"public test key" * 4
    payload = {
        "case_id": case.id,
        "arm": "bge",
        "case_sha256": digest(case),
        "run_id": run_id(case, "bge"),
    }
    payload[field] = "incorrect-binding"
    with pytest.raises(ValueError, match="identity"):
        score(case, "bge", sign_collection(payload, key), key, {})


@pytest.mark.integration
async def test_existing_sql_only_control_without_changing_old_artifacts(
    pg_settings, tmp_path, monkeypatch
):
    import test_semantic_integration as original

    # Reuse the existing six-metric Gold assertions; keep all output in this new test root.
    folder = tmp_path / "control"
    (folder / "artifacts/p3").mkdir(parents=True)
    monkeypatch.setattr(original, "ROOT", folder)
    generator = original.metric_data.__wrapped__(pg_settings)
    data = next(generator)
    try:
        await original.test_real_xlsx_pg_mcp_five_metrics_evidence_and_unanswerable(
            data, pg_settings
        )
    finally:
        with pytest.raises(StopIteration):
            next(generator)
