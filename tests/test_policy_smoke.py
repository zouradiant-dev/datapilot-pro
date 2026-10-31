"""New Dev authority and evaluator contracts, with public inputs and no model key."""

import copy
import importlib
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetScope
from datapilot.ingestion.common import digest
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import DocumentGoal, ReportScope


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    return tuple(
        importlib.import_module(n)
        for n in [
            "p7_policy_smoke",
            "p7_policy_smoke_run",
            "p7_policy_smoke_worker",
            "p7_policy_smoke_prepare",
        ]
    )


def authorized(worker):
    binding = {"manifest_sha256": "a" * 64, "scope_hashes": {"tps-01": "b" * 64}}
    permit = {
        "kind": "p7-three-policy-live-1",
        "authorized": True,
        "approved_by_role": "project_owner",
        "source_user_authorization_ref": "synthetic-unit-only",
        "approve_bound_runs": True,
        "binding": binding,
        "budget": dict(worker.POLICY),
        "provider": "deepseek",
        "model": "deepseek-flash",
        "thinking": "disabled",
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    return permit, binding


@pytest.mark.parametrize(
    "field,value",
    [
        ("authorized", False),
        ("kind", "p7-dev-smoke-live-authorization-1"),
        ("approve_bound_runs", False),
        ("model", "another-model"),
        ("source_user_authorization_ref", ""),
        ("binding", {}),
    ],
)
def test_old_pending_or_changed_authority_is_rejected(modules, field, value):
    _, _, w, _ = modules
    p, binding = authorized(w)
    p[field] = value
    with pytest.raises(ValueError):
        w.permit_valid(p, binding, admission=True)


def test_expiry_requires_full_campaign_headroom_and_explicit_timezone(modules):
    _, _, w, _ = modules
    p, binding = authorized(w)
    w.permit_valid(p, binding, admission=True)
    for expiry in [
        datetime.now(UTC) + timedelta(minutes=20),
        datetime.now(UTC) - timedelta(seconds=1),
    ]:
        p["expires_at"] = expiry.isoformat()
        with pytest.raises(ValueError):
            w.permit_valid(p, binding, admission=True)
    p["expires_at"] = "2031-01-01T00:00:00"
    with pytest.raises(ValueError):
        w.permit_valid(p, binding)


@pytest.mark.parametrize("value", [True, 1.0])
def test_boolean_and_float_are_not_integer_budget_authority(modules, value):
    _, _, w, _ = modules
    p, binding = authorized(w)
    p["budget"]["concurrency"] = value
    with pytest.raises(ValueError):
        w.permit_valid(p, binding)


async def test_pending_live_fails_before_settings_or_provider_construction(modules, monkeypatch):
    _, _, w, _ = modules

    def forbidden(*args, **kwargs):
        raise AssertionError("Settings/credentials/provider must not be touched")

    monkeypatch.setattr(w, "Settings", forbidden)
    config = dict.fromkeys(
        [
            "schema_version",
            "case_id",
            "run_id",
            "question_sha256",
            "report_scope",
            "rag_scope",
            "scope_sha256",
            "profile",
            "binding",
        ]
    )
    config.update(schema_version="three-policy-launch-1", profile=w.PROFILE)
    with pytest.raises(ValueError, match="authority"):
        await w.main(config, "live", "approve", {})


def test_seven_original_admissions_bound_tokens_even_after_refunds(modules):
    _, runner, _, _ = modules
    ledger = BudgetLedger(BudgetLimits(calls=7, tokens=90000))
    tickets = [runner.reserve_case(ledger) for _ in range(5)]
    assert ledger.snapshot().total_tokens == 90000 and len(ledger.pending) == 5
    with pytest.raises(AgentFailure):
        runner.reserve_case(ledger)
    for ticket in tickets[:-1]:
        ledger.settle(ticket, 15)
    runner.reserve_case(ledger)
    runner.reserve_case(ledger)
    assert len(ledger.pending) == 3
    with pytest.raises(AgentFailure):
        runner.reserve_case(ledger)
    assert ledger.snapshot().total_tokens == 54060  # Four known settlements, three full reserves.


def test_independent_decimal_oracle_filters_payment_currency_and_right_boundary(modules, tmp_path):
    *_, prepare = modules
    p = tmp_path / "invoices.csv"
    p.write_text(
        "invoice_id,amount_cents,invoice_date,payment_status,currency\n"
        "i1,1001,2025-10-01,paid,CNY\n"
        "i2,900,2025-11-01,paid,CNY\n"
        "i3,800,2025-10-02,unpaid,CNY\n"
        "i4,700,2025-10-02,paid,USD\n",
        encoding="utf-8",
    )
    assert prepare.oracle(p) == "10.01"


def test_full_untracked_closure_and_frozen_snapshot_are_checked(modules, tmp_path):
    core, *_ = modules
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("pass\n")
    files = core.runtime_files(tmp_path)
    shutil.copytree(tmp_path / "src", tmp_path / "frozen/src")
    m = {"files": files, "snapshot": "frozen"}
    core.check_freeze(tmp_path, m)
    (tmp_path / "src/new_untracked.py").write_text("pass\n")
    with pytest.raises(ValueError):
        core.check_freeze(tmp_path, m)
    with pytest.raises(ValueError):
        core.check_freeze(tmp_path, {"files": files, "snapshot": "../escape"})


def test_signed_denial_cannot_be_a_different_case_or_model_execution(modules):
    core, *_ = modules
    from p7_business_scoring import sign_collection

    scope = ReportScope(
        owner="public-toy",
        question="A public document question",
        datasets=DatasetScope(),
        metrics=[],
        document_goal=DocumentGoal(
            goal_id="documents", question="A public document question", metric_goals=[]
        ),
    )
    case = core.Case(
        case_id="tps-08",
        lane="rag_only",
        scope=scope,
        rag_scope=RagScope(owner="public-toy", allow_saas=True),
        preflight_denial="DOCUMENT_NOT_AUTHORIZED",
    )
    gold = core.Gold(case_id="tps-08", completion="blocked")
    payload = {
        "case_id": case.case_id,
        "question_sha256": digest(scope.question),
        "stage": "preflight",
        "code": "DOCUMENT_NOT_AUTHORIZED",
        "case_sha256": digest(case),
        "model_mode": "not_invoked",
    }
    key = b"unit-only-public-synthetic-key-32-bytes"
    signed = sign_collection(payload, key)
    assert core.score(case, gold, signed, key)["strict_correct"]
    bad = copy.deepcopy(signed)
    bad["payload"]["code"] = "succeeded"
    with pytest.raises(ValueError):
        core.score(case, gold, bad, key)
    payload["model_mode"] = "live"
    assert not core.score(case, gold, sign_collection(payload, key), key)["strict_correct"]
    payload["case_id"] = "tps-07"
    with pytest.raises(ValueError):
        core.score(case, gold, sign_collection(payload, key), key)


@pytest.mark.parametrize("mode", ["fake", "live"])
def test_json_launch_has_the_same_full_scope_hash_in_host_and_candidate(modules, mode):
    import json

    core, runner, worker, _ = modules
    scope = ReportScope(
        owner="public-toy",
        question="A public document question",
        datasets=DatasetScope(),
        metrics=[],
        document_goal=DocumentGoal(
            goal_id="documents", question="A public document question", metric_goals=[]
        ),
    )
    case = core.Case(
        case_id="tps-07",
        lane="rag_only",
        scope=scope,
        rag_scope=RagScope(owner=scope.owner, allow_saas=True),
    )
    config = runner.base_config(case, mode, "a" * 64)
    decoded = json.loads(json.dumps(config))
    assert decoded["scope_sha256"] == worker.scope_hash(case.scope, case.rag_scope)
    assert digest(decoded) == digest(config)
