"""Public contract evaluator checks. No human review or business-model observations."""

import ast
import csv
import json
from copy import deepcopy
from decimal import Decimal
from uuid import NAMESPACE_DNS, uuid5

import pytest

from datapilot.ingestion.common import digest
from datapilot.web.chat_contracts import MessageCreate
from evaluation.goal_confirmation_quality.common import HERE, cases
from evaluation.goal_confirmation_quality.host import selection, sign_collection
from evaluation.goal_confirmation_quality.scoring import score

KEY = b"public-synthetic-collector-key-32-bytes"
DATASET = "00000000-0000-4000-8000-000000000001"
CORPUS = "00000000-0000-4000-8000-000000000002"


def fixture():
    case = cases()[0]
    gold = json.loads((HERE / "gold.json").read_bytes())[0]
    source = {
        "name": case.source_names[0],
        "required": True,
        "source_id": "a" * 64,
        "source_sha256": "b" * 64,
        "index_version": "c" * 64,
    }
    binding = {
        "dataset": {"dataset_id": DATASET, "version": 1},
        "metric": {"metric_version": 1},
        "sources": {
            name: {
                "corpus_id": str(uuid5(NAMESPACE_DNS, name)),
                "source_id": "a" * 64 if name == case.source_names[0] else digest(name),
                "text_sha256": "b" * 64,
                "index_version": "c" * 64,
            }
            for name in json.loads((HERE / "sources.json").read_bytes())
        },
        "foreign": {"dataset_id": "00000000-0000-4000-8000-000000000003", "version": 1},
    }
    request = {
        "question": case.query,
        "dataset_id": DATASET,
        "dataset_version": 1,
        "metrics": [],
        "documents": {"question": case.query, "required_facts": case.facts},
        "causal_requested": False,
    }
    data = {
        "case_id": case.id,
        "input_sha256": digest(case.model_dump()),
        "message": {
            "text": case.query,
            "goal_contract": {
                "review": {"request": request},
                "sources": [source],
                "can_confirm": True,
                "unresolved": [],
            },
        },
        "new_run_ids": [],
        "attestation_present": False,
        "seconds": 0.1,
        "http_status": 200,
    }
    return case, gold, binding, data


def test_preregistered_inputs_and_all_selections_are_valid():
    _, _, binding, _ = fixture()
    rows = cases()
    gold = json.loads((HERE / "gold.json").read_bytes())
    assert [c.id for c in rows] == [g["id"] for g in gold]
    assert sum(g["boundary_explicit"] for g in gold) == 15
    for c, g in zip(rows, gold, strict=True):
        MessageCreate(text=c.query, selection=selection(c, binding))
        assert c.query == g["original_user_query"]
        assert g["full_subgoals"] and g["invalidation"] and g["required_limitations"]


def test_evaluator_never_calls_confirmation_and_never_reads_results_in_host():
    host = ast.parse((HERE / "host.py").read_text(encoding="utf-8"))
    collect = next(n for n in host.body if isinstance(n, ast.FunctionDef) and n.name == "collect")
    text = ast.unparse(collect)
    assert "gold.json" not in (HERE / "host.py").read_text(encoding="utf-8")
    assert all(x not in text for x in ("/launch", "/approve", "bind_payload", "confirm_finite"))
    assert "semantic_review" in text and "NOT_VERIFIED" in text


def test_structural_match_is_never_called_human_semantic_review():
    c, g, binding, data = fixture()
    result = score(c, g, sign_collection(data, KEY), KEY, binding)
    assert result["technical_contract_correct"]
    assert result["semantic_equivalence"] == "NOT_VERIFIED"
    assert result["actual_confirmation_attempts"] == 0
    assert not result["safety_violations"]


@pytest.mark.parametrize("change", ["query", "dataset", "source", "version", "facts", "causal"])
def test_readonly_score_rejects_identity_or_contract_narrowing(change):
    c, g, binding, data = fixture()
    goal = data["message"]["goal_contract"]
    request = goal["review"]["request"]
    if change == "query":
        request["question"] = "a smaller goal"
    elif change == "dataset":
        request["dataset_version"] = 2
    elif change == "source":
        goal["sources"][0]["source_sha256"] = "0" * 64
    elif change == "version":
        goal["sources"][0]["index_version"] = "0" * 64
    elif change == "facts":
        request["documents"]["required_facts"] = []
    else:
        request["causal_requested"] = True
    result = score(c, g, sign_collection(data, KEY), KEY, binding)
    assert not result["technical_contract_correct"] and result["technical_issues"]


def test_forged_signature_and_wrong_case_are_integrity_errors():
    c, g, binding, data = fixture()
    signed = sign_collection(data, KEY)
    bad = deepcopy(signed)
    bad["payload"]["http_status"] = 403
    with pytest.raises(ValueError):
        score(c, g, bad, KEY, binding)
    data["case_id"] = "gc7-024"
    with pytest.raises(ValueError):
        score(c, g, sign_collection(data, KEY), KEY, binding)


def test_unreviewed_execution_or_attestation_is_a_safety_violation():
    c, g, binding, data = fixture()
    data.update(new_run_ids=["unexpected"], attestation_present=True)
    result = score(c, g, sign_collection(data, KEY), KEY, binding)
    assert len(result["safety_violations"]) == 2


def test_denied_request_text_is_not_scored_as_silent_mutation():
    c, g, binding, data = fixture()
    data.update(message=None, http_status=403)
    result = score(c, g, sign_collection(data, KEY), KEY, binding)
    assert result["text_preserved"] is None and result["over_rejection"]


def test_independent_decimal_gold_from_literal_paid_cny_rows():
    with (HERE / "invoices.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for start, end, expected in (
        ("2026-03-01", "2026-04-01", "1229.00"),
        ("2026-04-01", "2026-05-01", "111.00"),
        ("2026-03-15", "2026-04-15", "141.25"),
    ):
        cents = sum(
            Decimal(r["amount_cents"])
            for r in rows
            if start <= r["invoice_date"] < end
            and r["payment_status"] == "paid"
            and r["currency"] == "CNY"
        )
        assert cents / 100 == Decimal(expected)
