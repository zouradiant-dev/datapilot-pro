"""Publish native-dimension Dev indexes, fit calibration only, then evaluate validation."""

import argparse
import hashlib
import json
from pathlib import Path

import sqlalchemy as sa
from experiment import DB, OWNER, ROOT, Store, aggregate, calibrate, load_plan, measure, vector
from sqlalchemy.engine import make_url

from datapilot.ingestion.common import digest


def write_new(path, value):
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)


def evaluate(base, model_id):
    plan = load_plan()
    plan_sha = hashlib.sha256(
        (ROOT / "tests/fixtures/rag/embedding-ab-dev.json").read_bytes()
    ).hexdigest()
    registered = json.loads((base / "preregistration.json").read_bytes())
    if plan_sha != registered["plan_sha256"]:
        raise ValueError("Dev Gold/protocol changed after preregistration")
    result = json.loads((base / (model_id + "-vectors.json")).read_bytes())
    parsed = json.loads((base / "parsed.json").read_bytes())
    env = json.loads((base / "database-private.json").read_bytes())
    writer = make_url(env["rag_ingest"])
    if writer.database != DB or writer.username != "datapilot_rag_ingest":
        raise ValueError("Only the dedicated restricted Dev ingestor may publish")
    model = result["model"]
    if any(model[k] != plan["models"][model_id][k] for k in ["repo", "revision", "dimensions"]):
        raise ValueError("Predeclared model identity changed")
    out = base / model_id
    out.mkdir(exist_ok=False)
    engine = sa.create_engine(writer, hide_parameters=True)
    indexes = {}
    try:
        for split in ["calibration", "validation"]:
            data = parsed[split]
            manifest = {
                "schema_version": "embedding-ab-index-1",
                "owner": OWNER,
                "split": split,
                "corpus_id": data["corpus_id"],
                "model": model,
                "chunker": plan["protocol"]["chunker"],
                "sources": data["sources"],
                "plan_sha256": plan_sha,
            }
            version = digest(manifest)
            indexes[split] = manifest
            with engine.begin() as conn:
                conn.execute(
                    sa.text("INSERT INTO embedding_ab.indexes VALUES(:v,CAST(:m AS jsonb))"),
                    {"v": version, "m": json.dumps(manifest)},
                )
                for source in manifest["sources"]:
                    raw = (base / "sources" / split / source["name"]).read_bytes()
                    if hashlib.sha256(raw).hexdigest() != source["version"]:
                        raise ValueError("Raw source differs from the registered snapshot")
                    text = raw.decode("utf-8")
                    for span in source["chunks"]:
                        value = vector(
                            result["vectors"]["documents"][span["chunk_id"]], model["dimensions"]
                        )
                        conn.execute(
                            sa.text(
                                "INSERT INTO embedding_ab.chunks VALUES "
                                "(:v,:c,:d,:n,:t,CAST(:s AS jsonb),:dimensions,"
                                "CAST(:e AS public.vector),:h)"
                            ),
                            {
                                "v": version,
                                "c": span["chunk_id"],
                                "d": source["document_id"],
                                "n": source["name"],
                                "t": text[span["start"] : span["end"]],
                                "s": json.dumps(span),
                                "dimensions": model["dimensions"],
                                "e": json.dumps(value.tolist()),
                                "h": hashlib.sha256(value.astype("<f4").tobytes()).hexdigest(),
                            },
                        )
            write_new(
                out / (split + "-index.json"), {"index_version": version, "manifest": manifest}
            )
    finally:
        engine.dispose()
    store = Store(env["rag_reader"])
    rows = {}
    try:
        for split in ["calibration", "validation"]:
            current = []
            for case in [c for c in plan["cases"] if c["split"] == split]:
                try:
                    ranking = store.rank(plan, case, indexes[split], result["vectors"]["queries"])
                except ValueError as exc:
                    if str(exc) != case.get("expected_error"):
                        raise
                    current.append(
                        {
                            "case_id": case["id"],
                            "expected_scope_refusal": str(exc),
                            "source_access": False,
                        }
                    )
                    continue
                if case.get("expected_error"):
                    raise AssertionError("Unauthorized request was not refused")
                current.append(
                    {
                        "case_id": case["id"],
                        "ranking": ranking,
                        "raw": measure(case, ranking),
                        "default_055": measure(case, ranking, 0.55),
                        "default_055_goal_gate": measure(case, ranking, 0.55, True),
                    }
                )
            rows[split] = current
            write_new(out / (split + "-raw.json"), current)
            if split == "calibration":
                fitted = calibrate(
                    plan, {r["case_id"]: r["ranking"] for r in current if "ranking" in r}
                )
                threshold = fitted["selected_threshold"]
                write_new(
                    out / "calibration-lock.json",
                    {
                        **fitted,
                        "plan_sha256": plan_sha,
                        "model_manifest_sha256": digest(model),
                        "calibration_raw_sha256": hashlib.sha256(
                            (out / "calibration-raw.json").read_bytes()
                        ).hexdigest(),
                        "before_validation_retrieval": True,
                    },
                )
        groups = {}
        validation = {c["id"]: c for c in plan["cases"] if c["split"] == "validation"}
        for row in rows["validation"]:
            if "ranking" not in row:
                continue
            case = validation[row["case_id"]]
            row["calibrated"] = (
                measure(case, row["ranking"], threshold) if threshold is not None else None
            )
            row["calibrated_goal_gate"] = (
                measure(case, row["ranking"], threshold, True) if threshold is not None else None
            )
            groups.setdefault(case["language_pair"], []).append(row)
        summary = {
            "id": model_id,
            "model_manifest_sha256": digest(model),
            "selected_threshold": threshold,
            "resources": result["resources"],
            "validation": {},
            "language_groups": {},
            "paid_calls": 0,
            "scope_refusals": sum(
                "expected_scope_refusal" in r for rows_ in rows.values() for r in rows_
            ),
            "source_hash_and_cosine_checks_passed": True,
            "one_chunk_per_source": True,
            "business_report_verification": "not_run",
        }
        for key in [
            "raw",
            "default_055",
            "default_055_goal_gate",
            "calibrated",
            "calibrated_goal_gate",
        ]:
            summary["validation"][key] = aggregate(
                [r[key] for r in rows["validation"] if r.get(key) is not None]
            )
            for name, values in groups.items():
                summary["language_groups"].setdefault(name, {})[key] = aggregate(
                    [r[key] for r in values if r.get(key) is not None]
                )
        write_new(out / "validation-scored.json", rows["validation"])
        write_new(out / "summary.json", summary)
        return summary
    finally:
        store.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--model", choices=["bge-small", "bge-m3", "qwen3"], required=True)
    a = p.parse_args()
    r = evaluate(a.base, a.model)
    print(
        json.dumps(
            {
                "model": r["id"],
                "threshold": r["selected_threshold"],
                "validation": r["validation"],
                "scope_refusals": r["scope_refusals"],
            }
        )
    )
