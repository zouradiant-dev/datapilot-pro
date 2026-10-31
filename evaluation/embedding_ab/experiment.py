"""Trusted, non-Agent native-dimension PG experiment; not a production RAG adapter."""

import hashlib
import json
from pathlib import Path

import numpy as np
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from datapilot.ingestion.common import digest

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "tests/fixtures/rag/embedding-ab-dev.json"
DB = "datapilot_test_embedding_ab_v1_20261029"
OWNER = "p7-embedding-ab-20261029"


def load_plan(path=PLAN):
    plan = json.loads(path.read_bytes())
    if plan["schema_version"] != "embedding-ab-dev-1" or len(plan["cases"]) != 56:
        raise ValueError("Use the preregistered bounded Dev")
    ids = [c["id"] for c in plan["cases"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate cases")
    for c in plan["cases"]:
        names = set(plan["sources"][c["split"]])
        if not set(c["required_sources"]) <= set(c["relevant_sources"]) <= names:
            raise ValueError("Unknown or incoherent Gold")
        if any(not 1 <= len(c[k]) <= 512 for k in ("query", "goal")):
            raise ValueError("Bounded query and immutable goal required")
    return plan


def vector(values, dimensions):
    v = np.asarray(values, dtype=np.float32)
    if dimensions not in {512, 1024} or v.shape != (dimensions,) or not np.isfinite(v).all():
        raise ValueError("Native dimension or finite-vector mismatch")
    if abs(float(np.linalg.norm(v)) - 1) > 0.001:
        raise ValueError("Unit-normalized vector required")
    return v


def allowed_sources(plan, case):
    return [
        n
        for n, s in plan["sources"][case["split"]].items()
        if not s.get("restricted") and (case["pool"] == "both" or s["language"] == case["pool"])
    ]


def authorize(plan, case, owner, requested_sources=()):
    if owner != OWNER:
        raise ValueError("OWNER_NOT_AUTHORIZED")
    allowed = allowed_sources(plan, case)
    if not set(requested_sources) <= set(allowed):
        raise ValueError("SOURCE_NOT_AUTHORIZED")
    return allowed


def measure(case, ranked, threshold=None, goal_gate=False):
    selected = [
        r
        for r in ranked
        if threshold is None
        or (r["query_score"] >= threshold and (not goal_gate or r["goal_score"] >= threshold))
    ]
    relevant, required = set(case["relevant_sources"]), set(case["required_sources"])
    names = list(dict.fromkeys(r["source"] for r in selected))
    hits = [i for i, name in enumerate(names, 1) if name in relevant]
    hit_names = set(names) & relevant
    return {
        "source_recall": len(hit_names) / len(relevant) if relevant else None,
        "source_precision_at_3": len(hit_names) / 3 if relevant else None,
        "source_precision_returned": len(hit_names) / len(names) if names else None,
        "mrr": 1 / hits[0] if hits else 0 if relevant else None,
        "required_coverage": len(set(names) & required) / len(required) if required else None,
        "required_all": required <= set(names) if required else None,
        "irrelevant_hits": len(set(names) - relevant),
        "empty_negative_false_hit": bool(names) if not relevant else None,
        "returned": len(names),
        "wrong_empty": not names if relevant else None,
        "business_verified": False,
    }


def aggregate(rows):
    def avg(key):
        values = [r[key] for r in rows if r[key] is not None]
        return sum(values) / len(values) if values else None

    return {
        "n": len(rows),
        "source_recall": avg("source_recall"),
        "source_precision_at_3": avg("source_precision_at_3"),
        "source_precision_returned": avg("source_precision_returned"),
        "mrr": avg("mrr"),
        "required_coverage": avg("required_coverage"),
        "required_all": avg("required_all"),
        "irrelevant_hits": sum(r["irrelevant_hits"] for r in rows),
        "empty_negative_n": sum(r["empty_negative_false_hit"] is not None for r in rows),
        "empty_negative_false_hits": sum(r["empty_negative_false_hit"] is True for r in rows),
        "wrong_empty": sum(r["wrong_empty"] is True for r in rows),
    }


def calibrate(plan, results):
    rows = {
        c["id"]: c
        for c in plan["cases"]
        if c["split"] == "calibration" and not c.get("expected_error")
    }
    if set(results) != set(rows):
        raise ValueError("Calibration inputs must be exactly the independent calibration split")
    trials = []
    for threshold in plan["protocol"]["threshold_grid"]:
        metrics = aggregate([measure(rows[k], v, threshold) for k, v in results.items()])
        trials.append({"threshold": threshold, "metrics": metrics})
    safe = [r for r in trials if r["metrics"]["empty_negative_false_hits"] == 0]
    chosen = (
        max(
            safe,
            key=lambda r: (
                r["metrics"]["source_recall"] or 0,
                r["metrics"]["required_coverage"] or 0,
                r["metrics"]["source_precision_returned"] or 0,
                r["threshold"],
            ),
        )
        if safe
        else None
    )
    return {
        "selected_threshold": chosen["threshold"] if chosen else None,
        "trials": trials,
        "validation_used": False,
    }


class Store:
    """Fixed read-only templates in the dedicated Dev DB; no model-supplied SQL/scope."""

    def __init__(self, url):
        u = make_url(url)
        if (
            u.drivername != "postgresql+psycopg"
            or u.database != DB
            or u.username != "datapilot_rag_reader"
            or u.query
        ):
            raise ValueError("Dedicated experimental DB and reader required")
        self.engine = sa.create_engine(
            url, hide_parameters=True, connect_args={"connect_timeout": 5}
        )

    def close(self):
        self.engine.dispose()

    def rank(self, plan, case, index_manifest, vectors, *, owner=OWNER):
        requested = case.get("requested_sources", [])
        if case.get("expected_error") == "OWNER_NOT_AUTHORIZED":
            owner = "unrelated-owner"
        names = authorize(plan, case, owner, requested)
        version = digest(index_manifest)
        q, g = [
            vector(vectors[t], index_manifest["model"]["dimensions"])
            for t in (case["query"], case["goal"])
        ]
        with self.engine.connect() as conn, conn.begin():
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql("SET LOCAL statement_timeout='2s'")
            conn.exec_driver_sql("SET LOCAL lock_timeout='500ms'")
            actual = conn.execute(
                sa.text("SELECT manifest FROM embedding_ab.indexes WHERE index_version=:v"),
                {"v": version},
            ).scalar_one_or_none()
            if (
                actual != index_manifest
                or actual["owner"] != OWNER
                or actual["split"] != case["split"]
            ):
                raise ValueError("INDEX_NOT_AUTHORIZED")
            rows = (
                conn.execute(
                    sa.text(
                        "SELECT c.chunk_id,c.document_id,c.source_name,c.text,c.span,"
                        "c.vector_sha256,c.embedding::text AS vector,"
                        "1-(c.embedding OPERATOR(public.<=>) CAST(:q AS public.vector)) "
                        "AS query_score,"
                        "1-(c.embedding OPERATOR(public.<=>) CAST(:g AS public.vector)) "
                        "AS goal_score FROM embedding_ab.chunks c "
                        "WHERE c.index_version=:v AND c.source_name=ANY(:names) "
                        "ORDER BY c.embedding OPERATOR(public.<=>) "
                        "CAST(:q AS public.vector),c.chunk_id LIMIT 3"
                    ),
                    {
                        "v": version,
                        "q": json.dumps(q.tolist()),
                        "g": json.dumps(g.tolist()),
                        "names": names,
                    },
                )
                .mappings()
                .all()
            )
        output = []
        for row in rows:
            stored = vector(json.loads(row["vector"]), index_manifest["model"]["dimensions"])
            if hashlib.sha256(stored.astype("<f4").tobytes()).hexdigest() != row["vector_sha256"]:
                raise ValueError("VECTOR_HASH_CHANGED")
            source = next(s for s in index_manifest["sources"] if s["name"] == row["source_name"])
            span = next(s for s in source["chunks"] if s["chunk_id"] == row["chunk_id"])
            if (
                row["document_id"] != source["document_id"]
                or row["span"] != span
                or hashlib.sha256(row["text"].encode()).hexdigest() != span["sha256"]
            ):
                raise ValueError("SOURCE_HASH_CHANGED")
            for target, score in [(q, row["query_score"]), (g, row["goal_score"])]:
                independent = float(
                    stored.astype(np.float64)
                    @ target.astype(np.float64)
                    / (
                        np.linalg.norm(stored.astype(np.float64))
                        * np.linalg.norm(target.astype(np.float64))
                    )
                )
                if abs(independent - score) > 0.00001:
                    raise ValueError("PG_COSINE_MISMATCH")
            output.append(
                {
                    "source": row["source_name"],
                    "document_id": row["document_id"],
                    "chunk_id": row["chunk_id"],
                    "span": span,
                    "source_sha256": source["version"],
                    "index_version": version,
                    "query_score": float(row["query_score"]),
                    "goal_score": float(row["goal_score"]),
                    "model_manifest_sha256": digest(index_manifest["model"]),
                }
            )
        return output
