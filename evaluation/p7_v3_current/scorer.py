"""Versioned current scoring; frozen v3 scoring and Gold remain unchanged."""

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "p7_v3"))
import v3_score as original

from datapilot.ingestion.common import digest
from datapilot.reporting.contracts import CrossSourceReport

SCORER_VERSION = "p7-current-authorized-citations-v2"
TRUSTED = {"rag_completion_correction"}
_ORIGINAL = original.call_integrity


def current_call_integrity(payload):
    rows = payload.get("calls", [])
    for row in rows:
        if (
            str(row.get("call_key", "")).startswith("control:")
            and row.get("tool_name") not in TRUSTED
        ):
            return False
    clean = dict(payload)
    clean["calls"] = [r for r in rows if not str(r.get("call_key", "")).startswith("control:")]
    return _ORIGINAL(clean)


def score_legacy(task, gold, record, key, pins):
    # The evaluator runs serially. Scope the frozen scorer's compatibility hook to one score.
    with patch.object(original, "call_integrity", current_call_integrity):
        return original.score(task, gold, record, key, pins)


def citation_matches_pin(document, task, pins):
    """An extra reference still needs the frozen source and exact original chunk."""
    citation = document.citation
    for corpus in pins.get("corpora", {}).values():
        manifest = corpus["manifest"]
        if (manifest["target"]["corpus_id"], corpus["index_version"]) != (
            citation.corpus_id,
            citation.index_version,
        ):
            continue
        if digest(manifest) != citation.index_version or manifest["target"]["owner"] != task.owner:
            return False
        source = next(
            (s for s in manifest["sources"] if s["source_id"] == citation.source_id), None
        )
        if source is None or (source["document_id"], source["version"], source["version"]) != (
            citation.document_id,
            citation.version,
            citation.source_sha256,
        ):
            return False
        span = {
            field: getattr(citation, field)
            for field in ("chunk_id", "start", "end", "line_start", "line_end", "sha256")
        }
        return (
            span in source["chunks"]
            and hashlib.sha256(document.excerpt.encode("utf-8")).hexdigest() == citation.sha256
            and citation.model_revision == manifest["model"]["revision"]
            and citation.chunker_sha256 == digest(manifest["chunker"])
            and citation.retriever == manifest["retriever"]
        )
    return False


def score(task, gold, record, key, pins):
    """Permit authentic authorized extras; retain required facts and every other dimension."""
    legacy = score_legacy(task, gold, record, key, pins)
    result = legacy | {
        "scorer_version": SCORER_VERSION,
        "legacy_strict_correct": legacy["strict_correct"],
    }
    if not task.document_goal or "dimensions" not in legacy:
        # Host rejection, incomplete execution and early integrity errors stay closed.
        return result
    payload = original.authenticated(record, key)
    report = CrossSourceReport.model_validate_json(json.dumps(payload["snapshot"]["report"]))
    citations = [document for claim in report.claims for document in claim.documents]
    relevant = (gold.retrieval or {}).get("relevant_document_ids")
    published = {document.citation.document_id for document in citations}
    extras = published - set(relevant) if relevant is not None else set()
    relevant_sources = {
        document.citation.source_id
        for document in citations
        if relevant is None or document.citation.document_id in relevant
    }
    pins_valid = all(citation_matches_pin(document, task, pins) for document in citations)
    dimensions = dict(legacy["dimensions"])
    dimensions["citations"] = (
        dimensions["authorization"] is True
        and dimensions["evidence"] is True
        and pins_valid
        and len(relevant_sources) >= gold.minimum_cited_sources
    )
    correct = all(value is not False for value in dimensions.values())
    return result | {
        "strict_correct": correct,
        "dimensions": dimensions,
        "failure_class": None
        if correct
        else legacy.get("failure_class") or "citation_evidence_or_coverage_mismatch",
        "safety_violation": legacy.get("safety_violation", False) or not pins_valid,
        "citation_quality": {
            "policy": "authorized-extras-v2",
            "legacy_citations_valid": legacy["dimensions"]["citations"],
            "source_pins_valid": pins_valid,
            "published_document_count": len(published),
            "extra_authorized_document_ids": sorted(extras)
            if dimensions["authorization"] is True and pins_valid
            else [],
            "document_precision": len(published & set(relevant)) / len(published)
            if relevant is not None and published
            else None,
            "relevant_cited_sources": len(relevant_sources),
            "minimum_cited_sources": gold.minimum_cited_sources,
        },
    }


def project_metric_version(task, pins, materialized, *, request, target_version, definition_sha):
    """Project one externally bound metric mapping; retain the original score checks."""
    if task.metrics.count(request) != 1 or request.metric_version == target_version:
        raise ValueError("mapping must select exactly one frozen metric request")
    frozen = next(
        d
        for d in pins["datasets"].values()
        if (d["schema"]["dataset_id"], d["schema"]["version"])
        == (request.dataset_id, request.dataset_version)
    )
    if frozen["schema"] != materialized["schema"] or (
        frozen["semantics"]["definition_sha256"] != materialized["semantics"]["definition_sha256"]
    ):
        raise ValueError("mapped dataset or semantics drift")
    old, new = (
        next(
            m
            for m in dataset["metrics"]
            if (m["metric_id"], m["metric_version"]) == (request.metric_id, version)
        )
        for dataset, version in ((frozen, request.metric_version), (materialized, target_version))
    )
    if old["definition_sha256"] != definition_sha or new["definition_sha256"] != definition_sha:
        raise ValueError("mapped metric definition drift")
    projected = request.model_copy(update={"metric_version": target_version})
    scoring_pins = deepcopy(pins)
    for dataset in scoring_pins["datasets"].values():
        if dataset == frozen:
            dataset["metrics"] = [
                m
                for m in dataset["metrics"]
                if (m["metric_id"], m["metric_version"]) != (request.metric_id, target_version)
            ] + [deepcopy(new)]
    return task.model_copy(
        update={"metrics": [projected if m == request else m for m in task.metrics]}
    ), scoring_pins
