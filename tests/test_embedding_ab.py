"""Experiment metrics/protocol guards, never claims local model quality from mocks."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def lab():
    path = Path(__file__).parents[1] / "evaluation/embedding_ab/experiment.py"
    spec = importlib.util.spec_from_file_location("embedding_lab", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_predeclared_dev_has_disjoint_positive_topics_and_native_models(lab):
    p = lab.load_plan()
    topics = [
        {c["topic"] for c in p["cases"] if c["split"] == split and c["kind"] == "language_pair"}
        for split in ["calibration", "validation"]
    ]
    assert not topics[0] & topics[1]
    assert len(p["cases"]) == 56
    assert {m["dimensions"] for m in p["models"].values()} == {512, 1024}
    assert all("API key" not in c["query"] for c in p["cases"])
    assert len([c for c in p["cases"] if c.get("expected_error")]) == 4


@pytest.mark.parametrize("n", [512, 1024])
def test_native_unit_vectors_are_preserved(lab, n):
    a = np.zeros(n, dtype=np.float32)
    a[0] = 1
    assert np.array_equal(lab.vector(a, n), a)


@pytest.mark.parametrize("bad", ["shape", "nan", "norm", "dimension"])
def test_reject_bad_vectors_without_truncation(lab, bad):
    a = np.zeros(1024, dtype=np.float32)
    a[0] = 1
    n = 1024
    if bad == "shape":
        a = a[:512]
    elif bad == "nan":
        a[0] = np.nan
    elif bad == "norm":
        a[0] = 2
    else:
        n = 384
    with pytest.raises(ValueError):
        lab.vector(a, n)


def test_source_requirement_is_not_satisfied_by_related_supplement(lab):
    c = {"relevant_sources": ["required", "background"], "required_sources": ["required"]}
    r = lab.measure(c, [{"source": "background", "query_score": 0.9, "goal_score": 0.9}], 0.55)
    assert r["source_precision_returned"] == 1
    assert r["source_recall"] == 0.5 and r["required_coverage"] == 0
    assert not r["business_verified"]


def test_goal_gate_cannot_be_bypassed_by_rewrite_score(lab):
    c = {"relevant_sources": ["a"], "required_sources": ["a"]}
    rows = [{"source": "a", "query_score": 0.8, "goal_score": 0.4}]
    assert lab.measure(c, rows, 0.55)["required_coverage"] == 1
    assert lab.measure(c, rows, 0.55, True)["required_coverage"] == 0


def test_empty_negative_has_no_fabricated_perfect_recall(lab):
    r = lab.measure({"relevant_sources": [], "required_sources": []}, [])
    assert r["source_recall"] is None and r["source_precision_at_3"] is None
    assert r["empty_negative_false_hit"] is False


def test_calibration_is_closed_to_validation_and_constrained_by_false_hits(lab):
    plan = {
        "cases": [
            {
                "id": "c",
                "split": "calibration",
                "relevant_sources": ["a"],
                "required_sources": ["a"],
            },
            {"id": "n", "split": "calibration", "relevant_sources": [], "required_sources": []},
        ],
        "protocol": {"threshold_grid": [0.3, 0.55, 0.75, 0.85]},
    }
    results = {
        "c": [{"source": "a", "query_score": 0.8, "goal_score": 0.8}],
        "n": [{"source": "x", "query_score": 0.7, "goal_score": 0.7}],
    }
    fitted = lab.calibrate(plan, results)
    assert fitted["selected_threshold"] == 0.75 and not fitted["validation_used"]
    with pytest.raises(ValueError):
        lab.calibrate(plan, results | {"validation-row": []})


@pytest.mark.parametrize("kind", ["unauthorized_source", "wrong_owner"])
def test_unauthorized_scope_is_rejected_before_database_or_vectors(lab, kind):
    p = lab.load_plan()
    c = next(c for c in p["cases"] if c["kind"] == kind)
    store = object.__new__(lab.Store)
    with pytest.raises(ValueError, match=c["expected_error"]):
        store.rank(p, c, {}, {})


def test_untrusted_document_instructions_do_not_expand_scope(lab):
    p = lab.load_plan()
    c = next(c for c in p["cases"] if c["kind"] == "injection_as_data")
    granted = lab.authorize(p, c, lab.OWNER)
    assert "injection-zh.md" in granted and "restricted-en.md" not in granted
    with pytest.raises(ValueError, match="SOURCE_NOT_AUTHORIZED"):
        lab.authorize(p, c, lab.OWNER, ["restricted-en.md"])


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://datapilot_rag_reader:x@localhost/datapilot",
        "postgresql+psycopg://postgres:x@localhost/datapilot_test_embedding_ab_v1_20261029",
    ],
)
def test_diagnostic_store_rejects_production_database_and_admin(lab, url):
    with pytest.raises(ValueError):
        lab.Store(url)
