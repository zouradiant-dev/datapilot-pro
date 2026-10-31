"""Non-paid, public Dev measurement. Not an Agent tool or retrieval replacement."""

import hashlib
import json
import re
from statistics import mean

import numpy as np

from datapilot.rag.models import validate_vectors
from datapilot.rag.storage import Repository, sql

PARAMETERS = {
    "top_k": 5,
    "min_score": 0.55,
    "maximum_searches": 2,
    "searches_per_case": 1,
    "raw_rank_limit": 64,
    "threshold_tuning": False,
}


def load_plan(path):
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan["parameters"] != PARAMETERS or plan["schema_version"] != "p7-language-boundary-dev-1":
        raise ValueError("Measurement parameters/version changed")
    cases = plan["cases"]
    if len(cases) != 12 or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Expected twelve unique predeclared queries")
    for language, sources in plan["sources"].items():
        if language not in {"zh", "en"}:
            raise ValueError("Unexpected corpus language")
        for name, text in sources.items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]*\.md", name) or not 1 <= len(text) <= 512:
                raise ValueError("Use bounded public Markdown sources")
    for case in cases:
        if (
            case["query_language"] not in {"zh", "en"}
            or not 1 <= len(case["query"]) <= 512
            or not set(case["relevant_sources"]) <= set(plan["sources"][case["document_language"]])
            or bool(case["relevant_sources"]) != case["answerable"]
        ):
            raise ValueError("Invalid query or independently labeled sources")
    return plan


def measure(citations, sources, required_names):
    """Independent source labels, not a score or model self-reported completion."""
    required = set(required_names)
    if not required <= {s["name"] for s in sources}:
        raise ValueError("Required source not present in the approved corpus")
    chunks = {c["chunk_id"]: s for s in sources for c in s["chunks"]}
    ids = [c["chunk_id"] for c in citations]
    if len(ids) != len(set(ids)):
        raise ValueError("Repeated chunk references cannot inflate coverage")
    for citation in citations:
        source = chunks.get(citation["chunk_id"])
        if source is None or (citation["source_id"], citation["document_id"]) != (
            source["source_id"],
            source["document_id"],
        ):
            raise ValueError("Citation identity not bound to the actual source")
    gold_chunks = {c for c, s in chunks.items() if s["name"] in required}
    gold_sources = {s["source_id"] for s in sources if s["name"] in required}
    returned = set(ids)
    returned_sources = {c["source_id"] for c in citations}
    hits = len(returned & gold_chunks)
    source_hits = len(returned_sources & gold_sources)
    relevant_ranks = [i for i, chunk in enumerate(ids, 1) if chunk in gold_chunks]
    return {
        "returned_chunks": len(ids),
        "returned_sources": len(returned_sources),
        "required_chunks": len(gold_chunks),
        "required_sources": len(gold_sources),
        "relevant_chunks": hits,
        "relevant_sources": source_hits,
        "irrelevant_chunks": len(ids) - hits,
        "recall_at_k": hits / len(gold_chunks) if gold_chunks else None,
        "precision_at_k": hits / len(ids) if ids else None,
        "source_coverage": source_hits / len(gold_sources) if gold_sources else None,
        "reciprocal_rank": (1 / relevant_ranks[0] if relevant_ranks else 0.0)
        if gold_chunks
        else None,
        "full_source_coverage": source_hits == len(gold_sources) if gold_sources else None,
        "wrong_empty": bool(gold_sources) and not ids,
        "negative_correct": not ids if not gold_sources else None,
    }


def summarize(records):
    if not records or len({r["id"] for r in records}) != len(records):
        raise ValueError("Require nonempty unique observations, never a zero-data success")

    def group(rows):
        positive = [r for r in rows if r["answerable"]]
        negative = [r for r in rows if not r["answerable"]]
        required = sum(r["metrics"]["required_sources"] for r in rows)
        return {
            "cases": len(rows),
            "answerable": len(positive),
            "negative": len(negative),
            "full_source_coverage": sum(r["metrics"]["full_source_coverage"] for r in positive),
            "recall_at_k_macro": mean(r["metrics"]["recall_at_k"] for r in positive)
            if positive
            else None,
            "mrr": mean(r["metrics"]["reciprocal_rank"] for r in positive) if positive else None,
            "source_hits": sum(r["metrics"]["relevant_sources"] for r in rows),
            "source_required": required,
            "wrong_empty": sum(r["metrics"]["wrong_empty"] for r in positive),
            "negative_correct": sum(r["metrics"]["negative_correct"] for r in negative),
            "irrelevant_chunks": sum(r["metrics"]["irrelevant_chunks"] for r in rows),
            "returned_chunks": sum(r["metrics"]["returned_chunks"] for r in rows),
        }

    all_rows = group(records)
    all_rows["quality_gate_passed"] = (
        all_rows["full_source_coverage"] == all_rows["answerable"]
        and all_rows["negative_correct"] == all_rows["negative"]
        and all_rows["irrelevant_chunks"] == 0
    )
    return {
        "overall": all_rows,
        "language_pairs": {
            pair: group([r for r in records if r["language_pair"] == pair])
            for pair in sorted({r["language_pair"] for r in records})
        },
        "paired_matrix": group([r for r in records if r["kind"] == "paired_language_matrix"]),
        "worker_completion": "not_run",
        "business_completion": "not_run",
        "paid_model_calls": 0,
    }


def prefilter(reader_url, scope, query, embedding):
    """Trusted read-only diagnostic, never registered with MCP or shown to a model."""
    pin = scope.corpora[0]
    vectors, _ = embedding.encode([query], query=True)
    vector = validate_vectors(vectors, 1)[0]
    repository = Repository(reader_url, scope, goal=query)
    try:
        manifest = repository.manifests()[pin.corpus_id]
        expected = sum(len(s.chunks) for s in manifest.sources)
        if not 0 < expected <= PARAMETERS["raw_rank_limit"]:
            raise ValueError("Diagnostic corpus exceeds bounded candidate limit")
        with repository.read() as conn:
            assert conn.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
            assert (
                conn.exec_driver_sql("SELECT current_user").scalar_one() == "datapilot_rag_reader"
            )
            rows = (
                sql(
                    conn,
                    "SELECT chunk_id,document_id,span,text,embedding::text AS vector,"
                    "embedding_sha256,1-(embedding OPERATOR(public.<=>) "
                    "CAST(:vector AS public.vector)) AS score FROM rag.chunks "
                    "WHERE corpus_id=:c AND index_version=:v "
                    "AND document_id=ANY(CAST(:docs AS text[])) "
                    "ORDER BY embedding OPERATOR(public.<=>) "
                    "CAST(:vector AS public.vector),chunk_id "
                    "LIMIT 64",
                    c=pin.corpus_id,
                    v=pin.index_version,
                    docs=pin.document_ids,
                    vector=json.dumps(vector.tolist()),
                )
                .mappings()
                .all()
            )
        assert len(rows) == expected
        ranked = []
        for rank, row in enumerate(rows, 1):
            stored = validate_vectors([json.loads(row["vector"])], 1)[0]
            assert (
                hashlib.sha256(stored.astype("<f4").tobytes()).hexdigest()
                == row["embedding_sha256"]
            )
            assert hashlib.sha256(row["text"].encode()).hexdigest() == row["span"]["sha256"]
            independent = float(
                np.dot(stored.astype(np.float64), vector.astype(np.float64))
                / (
                    np.linalg.norm(stored.astype(np.float64))
                    * np.linalg.norm(vector.astype(np.float64))
                )
            )
            assert abs(independent - float(row["score"])) < 0.00001
            source = next(s for s in manifest.sources if s.document_id == row["document_id"])
            ranked.append(
                {
                    "rank": rank,
                    "chunk_id": row["chunk_id"],
                    "document_id": row["document_id"],
                    "source_id": source.source_id,
                    "source": source.name,
                    "score": float(row["score"]),
                    "independent_cosine": independent,
                    "span": row["span"],
                }
            )
        return manifest, ranked
    finally:
        repository.close()
