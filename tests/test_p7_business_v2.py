"""Public contracts for versioned benchmark preparation, never decode sealed Gold."""

import copy
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("p7_business_v2")


def toy():
    source = lambda c: {  # noqa: E731
        "source_id": c * 64,
        "document_id": c * 64,
        "version": "c" * 64,
        "name": c + ".md",
        "bytes": 3,
        "text_sha256": "c" * 64,
        "chunks": [],
    }
    corpus = "00000000-0000-4000-8000-000000000001"
    manifest = {
        "target": {
            "corpus_id": corpus,
            "owner": "toy",
            "dataset_id": None,
            "dataset_version": None,
        },
        "model": {
            "model": "synthetic-unit-fixture",
            "revision": "a" * 40,
            "dimensions": 512,
            "recipe": "fixture",
            "fixture": True,
            "files": {"toy": "a" * 64},
        },
        "chunker": {"version": "unicode-window-1", "chars": 192, "overlap": 32},
        "retriever": "pg-cosine-exact-1",
        "sources": [source("a"), source("b")],
    }
    question = "仅查找这次授权资料中的业务规则并保留出处。"
    task = {
        "case_id": "bh2-030",
        "lane": "rag_only",
        "objective": "公开契约测试目标",
        "question": question,
        "owner": "toy",
        "datasets": {"bindings": []},
        "metrics": [],
        "document_goal": {"goal_id": "documents", "question": question, "metric_goals": []},
        "rag_scope": {
            "owner": "toy",
            "allow_saas": True,
            "corpora": [
                {"corpus_id": corpus, "index_version": "e" * 64, "document_ids": ["a" * 64]}
            ],
        },
    }
    pins = {
        "corpora": {
            "old": {"manifest": manifest, "index_version": "e" * 64, "dataset_alias": "toy"}
        }
    }
    return task, pins


def test_subset_revision_preserves_authority_and_parent(v2, monkeypatch):
    monkeypatch.setattr(v2, "SUBSETS", {"bh2-030"})
    task, pins = toy()
    before = copy.deepcopy((task, pins))
    tasks, catalog, diffs = v2.revise([task], pins)
    assert (task, pins) == before
    assert tasks[0]["rag_scope"]["corpora"][0]["document_ids"] == ["a" * 64]
    item = next(p for alias, p in catalog["corpora"].items() if alias.startswith("subset-"))
    assert item["manifest"]["target"] == pins["corpora"]["old"]["manifest"]["target"]
    assert len(item["manifest"]["sources"]) == 1 and diffs[0]["case_id"] == task["case_id"]
    assert tasks[0]["question"] == task["question"]


@pytest.mark.parametrize("ids", [[], ["f" * 64]])
def test_subset_cannot_add_or_clear_document_grants(v2, monkeypatch, ids):
    monkeypatch.setattr(v2, "SUBSETS", {"bh2-030"})
    task, pins = toy()
    task["rag_scope"]["corpora"][0]["document_ids"] = ids
    with pytest.raises(ValueError, match="original grants"):
        v2.revise([task], pins)


def test_missing_exception_cannot_reduce_denominator(v2):
    with pytest.raises(ValueError, match="seven"):
        v2.revise([], {"corpora": {}})


def test_no_gold_or_execution_payload_added_to_inputs(v2, monkeypatch):
    monkeypatch.setattr(v2, "SUBSETS", {"bh2-030"})
    task, pins = toy()
    result, _, _ = v2.revise([task], pins)
    assert not ({"gold", "answer", "api_key", "approved"} & set(result[0]))
    assert json.loads(json.dumps(result))[0]["metrics"] == []
