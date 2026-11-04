"""Bind the new 60-case private draft to repaired code and scoring, without dispatch."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from datapilot.ingestion.common import digest

from .candidate_binding import digest as binding_digest
from .candidate_binding import verify

LANES = {"sql_only": "sql", "rag_only": "rag", "sql_rag": "xsrc"}


def bind_drafts(rows, manifest):
    counts = Counter(row["lane"] for row in rows)
    ids = [row["id"] for row in rows]
    if counts != Counter({name: 20 for name in LANES}) or len(set(ids)) != 60:
        raise ValueError("Expected 60 distinct business drafts in three 20-case lanes")
    scorer = manifest["scoring_profiles"]["partial-facts-v1"]
    if scorer["version"] != "p7-current-partial-evidence-v3":
        raise ValueError("New Holdout requires the repaired partial-evidence v3 scorer")
    cases = []
    for row in rows:
        if not re.fullmatch(r"g2-bh-" + LANES[row["lane"]] + r"-\d{3}", row["id"]):
            raise ValueError("New Holdout cannot reuse a legacy case namespace")
        cases.append(
            {
                "case_id": row["id"],
                "lane": row["lane"],
                "draft_contract_sha256": digest(row),
                "scorer_version": scorer["version"],
                "partial_evidence_policy": "HOST_REVIEW_REQUIRED"
                if row["lane"] != "sql_only"
                else "legacy",
                "trusted_launch_contract": "PENDING",
                "dispatch": "NOT_RUN",
            }
        )
    return {
        "schema": "p7-new-holdout-candidate-preparation-1",
        "planned": 60,
        "lane_counts": dict(counts),
        "candidate_manifest_sha256": binding_digest(manifest),
        "candidate_tree_sha256": manifest["tree_sha256"],
        "batch_scorer": scorer,
        "cases": cases,
        "formal_launch_ready": False,
        "live_allowed": False,
        "paid_calls": 0,
    }


def prepare(root, pack, bundle, expected_sha256):
    candidate = verify(root, bundle, expected_sha256)
    revision = pack / "revision-01"
    review = json.loads((revision / "manifest-v2.json").read_bytes())
    for name, expected in review["sha256"].items():
        path = revision / name.replace("\\", "/")
        if not path.resolve().is_relative_to(revision.resolve()):
            raise ValueError("Draft revision path escaped its pack")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Reviewed draft revision drift: " + name)
    rows = [
        json.loads(line)
        for lane in LANES
        for line in (revision / "tasks" / (lane + ".jsonl")).read_bytes().splitlines()
        if line.strip()
    ]
    result = bind_drafts(rows, candidate)
    result["draft_review"] = {
        "revision": review["revision"],
        "changed": review["changed"],
        "retained": review["retained"],
        "gold_review": review["new_gold_review"],
        "revision_manifest_sha256": hashlib.sha256(
            (revision / "manifest-v2.json").read_bytes()
        ).hexdigest(),
    }
    probes = (pack / "fault_probes.jsonl").read_bytes()
    result["fault_probes"] = {
        "count": sum(bool(line.strip()) for line in probes.splitlines()),
        "sha256": hashlib.sha256(probes).hexdigest(),
        "separate_denominator": True,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(
        Path(__file__).resolve().parents[2], args.pack, args.candidate, args.manifest_sha256
    )
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {
                "planned": result["planned"],
                "scorer": result["batch_scorer"]["version"],
                "live_allowed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
