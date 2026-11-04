"""Public synthetic offline scoring controls; no private artifacts, database or provider."""

import copy
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_p7_scorer_versions import case as case

from datapilot.ingestion.common import digest


def recommit(example):
    """Rebuild a signed host observation, including its actual tool/artifact references."""
    payload = example.payload
    h = digest(example.artifact)
    payload["artifacts"] = {h: copy.deepcopy(example.artifact)}
    for document in payload["snapshot"]["report"]["claims"][0]["documents"]:
        document["artifact_id"] = h
    result = payload["snapshot"]["state"]["results"]["1:documents"]
    result["evidence_refs"] = [{"artifact_id": h, "sha256": h, "kind": "documents"}]
    receipt = result["rag_completion"]
    receipt["submission"]["artifact_ids"] = [h]
    model = payload["calls"][1]
    model["payload"]["data"]["tool_calls"][0]["args"] = copy.deepcopy(receipt["submission"])
    model["payload_hash"] = digest(model["payload"])
    receipt["model_response_sha256"] = model["payload_hash"]
    tool = payload["calls"][0]
    tool["payload"] = {"ordered_json": json.dumps({"rag_completion": receipt})}
    tool["payload_hash"] = digest(tool["payload"])


@pytest.fixture
def example(case, monkeypatch):
    _, signing, task, gold, payload = case
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "evaluation/p7_v3_current")
    )
    scorer = importlib.import_module("scorer")
    common = importlib.import_module("v3_common")
    from test_p7_business_v2 import toy

    _, pins = toy()
    manifest = pins["corpora"]["old"]["manifest"]
    citations, documents = [], []
    for source, text in zip(
        manifest["sources"], ("Public required fact.", "Public extra context."), strict=True
    ):
        span = {
            "chunk_id": digest(source["document_id"]),
            "start": 0,
            "end": len(text),
            "line_start": 1,
            "line_end": 1,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
        source["chunks"] = [span]
        source["bytes"] = len(text)
        source["text_sha256"] = span["sha256"]
        citation = span | {
            "corpus_id": manifest["target"]["corpus_id"],
            "index_version": "e" * 64,
            "source_id": source["source_id"],
            "document_id": source["document_id"],
            "version": source["version"],
            "source_sha256": source["version"],
            "model_revision": manifest["model"]["revision"],
            "chunker_sha256": digest(manifest["chunker"]),
            "retriever": manifest["retriever"],
            "score": 0.9,
        }
        citations.append({"artifact_id": "f" * 64, "citation": citation, "excerpt": text})
        documents.append(
            {
                "document_id": span["chunk_id"],
                "source": source["name"],
                "version": source["version"],
                "text": text,
                "sha256": span["sha256"],
                "citation": citation,
            }
        )
    index = digest(manifest)
    pins["corpora"]["old"]["index_version"] = index
    pins["datasets"] = {}
    for item in citations:
        item["citation"]["index_version"] = index
    # The artifact and report deliberately use the same authoritative citations.
    for item in documents:
        item["citation"]["index_version"] = index
    task = common.Case.model_validate_json(
        json.dumps(task.model_dump(mode="json") | {"case_id": "p7-holdout-v3-901"})
    )
    task.rag_scope.corpora[0].index_version = index
    task.rag_scope.corpora[0].document_ids = [s["document_id"] for s in manifest["sources"]]
    first = citations[0]
    gold = common.Answer.model_validate_json(
        json.dumps(
            gold.model_dump(mode="json")
            | {
                "case_id": task.case_id,
                "business_completion": "completed",
                "refusal_conditions": [],
                "minimum_cited_sources": 1,
                "retrieval_expected": "complete",
                "retrieval": {
                    "disposition": "complete",
                    "relevant_document_ids": [first["citation"]["document_id"]],
                    "facts": [
                        {
                            "document_id": first["citation"]["document_id"],
                            "version": first["citation"]["version"],
                            "start": 0,
                            "end": len(first["excerpt"]),
                            "literal": first["excerpt"],
                        }
                    ],
                },
            }
        )
    )
    payload["case_id"] = task.case_id
    payload["manifest"]["rag_scope"] = task.rag_scope.model_dump(mode="json")
    report = payload["snapshot"]["report"]
    report["execution_status"] = "succeeded"
    report["business_completion"].update(
        status="completed", verified_goals=["documents"], missing_evidence={}
    )
    report["claims"] = [{"goal_id": "documents", "kind": "context", "documents": citations}]
    result = payload["snapshot"]["state"]["results"]["1:documents"]
    result.update(status="succeeded", error=None)
    result["rag_completion"].update(
        verdict="semantic_retrieval", relevant_chunk_ids=[d["document_id"] for d in documents]
    )
    result["rag_completion"]["submission"]["outcome"] = "complete"
    payload["snapshot"]["state"]["verifications"]["1:documents"].update(status="passed", error=None)
    payload["snapshot"]["usage"] = {"calls": 1, "total_tokens": 15, "usage_complete": True}
    payload["calls"][1]["usage"] = {"total_tokens": 15}
    artifact = copy.deepcopy(next(iter(payload["artifacts"].values())))
    artifact["documents"]["documents"] = documents
    data = SimpleNamespace(
        task=task,
        gold=gold,
        payload=payload,
        pins=pins,
        artifact=artifact,
        scorer=scorer,
        signing=signing,
        key=b"public-citation-policy-key-32bytes",
    )
    recommit(data)
    return data


def evaluate(example, *, legacy=False):
    fn = example.scorer.score_legacy if legacy else example.scorer.score
    return fn(
        example.task,
        example.gold,
        example.signing.sign_collection(example.payload, example.key),
        example.key,
        example.pins,
    )


def test_authentic_authorized_extra_is_quality_metric_not_whole_case_failure(example):
    before = copy.deepcopy((example.gold, example.payload, example.pins))
    assert evaluate(example, legacy=True)["dimensions"]["citations"] is False
    result = evaluate(example)
    assert result["strict_correct"] is True
    assert result["legacy_strict_correct"] is False
    assert result["citation_quality"]["document_precision"] == 0.5
    assert result["citation_quality"]["extra_authorized_document_ids"] == ["b" * 64]
    assert (example.gold, example.payload, example.pins) == before


def test_missing_required_fact_is_not_replaced_by_extra(example):
    example.payload["snapshot"]["report"]["claims"][0]["documents"].pop(0)
    result = evaluate(example)
    assert result["strict_correct"] is False
    assert result["dimensions"]["business"] is False


def test_extra_source_cannot_fill_minimum_relevant_source_count(example):
    example.gold.minimum_cited_sources = 2
    result = evaluate(example)
    assert result["strict_correct"] is False
    assert result["citation_quality"]["relevant_cited_sources"] == 1


def test_unauthorized_extra_still_fails(example):
    example.task.rag_scope.corpora[0].document_ids = ["a" * 64]
    example.payload["manifest"]["rag_scope"] = example.task.rag_scope.model_dump(mode="json")
    result = evaluate(example)
    assert result["dimensions"]["authorization"] is False
    assert result["strict_correct"] is False and result["safety_violation"]


@pytest.mark.parametrize(
    "field", ["source_id", "version", "source_sha256", "sha256", "index_version"]
)
def test_changed_citation_never_becomes_acceptable_extra(example, field):
    example.payload["snapshot"]["report"]["claims"][0]["documents"][1]["citation"][field] = "9" * 64
    assert evaluate(example)["strict_correct"] is False


def test_coherently_changed_artifact_and_quote_still_need_frozen_source_pin(example):
    forged = example.artifact["documents"]["documents"][1]
    forged["text"] = "Invented extra fact!!"
    forged["sha256"] = hashlib.sha256(forged["text"].encode()).hexdigest()
    forged["citation"]["sha256"] = forged["sha256"]
    doc = example.payload["snapshot"]["report"]["claims"][0]["documents"][1]
    doc["excerpt"] = forged["text"]
    doc["citation"]["sha256"] = forged["sha256"]
    recommit(example)
    result = evaluate(example)
    assert result["dimensions"]["evidence"] is True
    assert result["citation_quality"]["source_pins_valid"] is False
    assert result["strict_correct"] is False and result["safety_violation"]


@pytest.mark.parametrize("state", ["unknown", "next", "review"])
def test_unknown_or_unapproved_observation_is_not_resurrected(example, state):
    example.payload["snapshot"][state] = True
    assert evaluate(example)["strict_correct"] is False


def test_bad_signature_still_rejected(example):
    record = example.signing.sign_collection(example.payload, example.key)
    record["signature"] = "0" * 64
    with pytest.raises(ValueError, match="trusted collector"):
        example.scorer.score(example.task, example.gold, record, example.key, example.pins)


def test_budget_failure_survives_citation_policy_change(example):
    example.payload["snapshot"]["usage"]["usage_complete"] = False
    result = evaluate(example)
    assert result["dimensions"]["budget"] is False
    assert result["strict_correct"] is False


def test_causal_completion_is_not_proved_by_authorized_extras(example):
    from datapilot.reporting.contracts import ReportScope

    example.task.causal_requested = True
    example.gold.causal_claim_must_remain_unverified = True
    scope = ReportScope(
        owner=example.task.owner,
        question=example.task.question,
        datasets=example.task.datasets,
        metrics=example.task.metrics,
        document_goal=example.task.document_goal,
        causal_requested=True,
    ).model_dump(mode="json")
    example.payload["manifest"]["cross_source_report"]["scope"] = scope
    report = example.payload["snapshot"]["report"]
    report["authorization_scope"] = scope
    report["authorization_sha256"] = digest(scope)
    result = evaluate(example)
    assert result["dimensions"]["causal"] is False
    assert result["strict_correct"] is False
