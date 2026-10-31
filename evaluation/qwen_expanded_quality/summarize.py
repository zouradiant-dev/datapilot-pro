"""Independent offline scoring, paired inference, and immutable batch seals."""

import argparse
import json
import math
import random
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime

from .common import ARMS, OUT, cases, sha, verify, write_new
from .scoring import score


def average(rows, name):
    x = [r[name] for r in rows if r.get(name) is not None]
    return sum(x) / len(x) if x else None


def paired(pairs, complete):
    obs = [p for p in pairs if all(p.get(a, {}).get("observed") for a in ARMS)]
    table = Counter(
        (bool(p["bge"]["strict_correct"]), bool(p["qwen"]["strict_correct"])) for p in obs
    )
    deltas = [int(p["qwen"]["strict_correct"]) - int(p["bge"]["strict_correct"]) for p in obs]
    n = len(deltas)
    discordant = table[False, True] + table[True, False]
    exact = (
        min(
            1,
            2
            * sum(
                math.comb(discordant, k)
                for k in range(min(table[False, True], table[True, False]) + 1)
            )
            / (2**discordant),
        )
        if discordant
        else None
    )
    interval = None
    if n and complete:
        rng = random.Random(20261030)
        groups = {}
        for p, delta in zip(obs, deltas, strict=True):
            groups.setdefault(p.get("category", "single"), []).append(delta)
        samples = sorted(
            sum(rng.choice(group) for group in groups.values() for _ in group) / n
            for _ in range(10000)
        )
        interval = [samples[249], samples[9749]]
    return {
        "planned_pairs": len(pairs),
        "observed_complete_pairs": n,
        "bge_wrong_qwen_right": table[False, True],
        "bge_right_qwen_wrong": table[True, False],
        "both_right": table[True, True],
        "both_wrong": table[False, False],
        "observed_paired_difference": sum(deltas) / n if n else None,
        "primary_95_paired_bootstrap_interval": interval,
        "exact_mcnemar_two_sided": exact if complete else None,
        "inference": "complete frozen cohort"
        if complete
        else "partial observed pairs descriptive; primary cohort inference not_run",
    }


def aggregate(pairs):
    result = {}
    for arm in ARMS:
        rows = [p[arm] for p in pairs if p.get(arm, {}).get("observed")]
        returned = sum(len(r.get("returned_sources", [])) for r in rows)
        unrelated = sum(len(r.get("unrelated_sources", [])) for r in rows)
        result[arm] = {
            "planned": len(pairs),
            "observed": len(rows),
            "not_run": len(pairs) - len(rows),
            "strict_correct": sum(r["strict_correct"] for r in rows),
            "strict_over_planned_lower_bound": sum(r["strict_correct"] for r in rows) / len(pairs),
            "strict_over_observed": average(rows, "strict_correct"),
            "status_counts": dict(Counter(r["actual_status"] for r in rows)),
            "authorized_retrieval_observed": sum(
                r.get("source_recall_at_3") is not None for r in rows
            ),
            "preflight_refusals": sum(r.get("expected_safe_refusal", False) for r in rows),
            "source_recall_at_3": average(rows, "source_recall_at_3"),
            "required_coverage": average(rows, "required_coverage"),
            "fact_coverage": average(rows, "fact_coverage"),
            "all_required": sum(r.get("all_required") is True for r in rows),
            "precision_nonempty_macro": average(rows, "source_precision"),
            "precision_micro": (returned - unrelated) / returned if returned else None,
            "returned_unique_sources": returned,
            "unrelated_returns": unrelated,
            "wrong_snapshot_returns": sum(len(r.get("wrong_version_sources", [])) for r in rows),
            "worker_complete": sum(r.get("worker_complete") is True for r in rows),
            "fact_citation_valid": sum(r.get("correct_citation_count", 0) for r in rows),
            "fact_citation_total": sum(r.get("citation_count", 0) for r in rows),
            "goal_parse_observed": sum(r.get("goal_parse_correct") is not None for r in rows),
            "goal_parse_accuracy": average(rows, "goal_parse_correct"),
            "unsupported_false_positive": sum(
                r.get("unsupported_false_positive", False) for r in rows
            ),
            "unsupported_false_negative": sum(
                r.get("unsupported_false_negative", False) for r in rows
            ),
            "false_completion": sum(r["false_completion"] for r in rows),
            "unsupported_claims": sum(r["unsupported_claims"] for r in rows),
            "safety_violations": sum(len(r["safety_violations"]) for r in rows),
            "infrastructure_failures": sum(r["infrastructure_failure"] for r in rows),
        }
    return result


def offline(index):
    reg = verify()
    b = json.loads((OUT / "bindings.json").read_bytes())
    assert (
        sha(OUT / "bindings.json")
        == json.loads((OUT / "bindings-seal.json").read_bytes())["sha256"]
    )
    key = (OUT / "collector-key-private.bin").read_bytes()
    pairs = []
    differences = []
    failures = []
    for c in cases():
        p = {
            "case_id": c.id,
            "split": c.split,
            "category": c.category,
            "gold": c.model_dump(mode="json"),
        }
        for a in ARMS:
            path = OUT / "collections" / f"{c.id}-{a}.json"
            if not path.exists():
                p[a] = {"observed": False, "actual_status": "not_run", "strict_correct": False}
                continue
            rated = score(c, a, json.loads(path.read_bytes()), key, b)
            original = json.loads((OUT / "scores" / path.name).read_bytes())
            if rated != original:
                differences.append({"case": c.id, "arm": a})
            p[a] = {**rated, "observed": True}
            if (
                not rated["strict_correct"]
                or rated.get("unrelated_sources")
                or rated.get("wrong_version_sources")
            ):
                failures.append(
                    {
                        "case": c.id,
                        "arm": a,
                        "strict": rated["strict_correct"],
                        "errors": rated["error_categories"],
                        "safety": rated["safety_violations"],
                        "unrelated": rated.get("unrelated_sources", []),
                        "wrong_snapshot": rated.get("wrong_version_sources", []),
                    }
                )
        pairs.append(p)
    if differences and not (OUT / "stopped.json").exists():
        write_new(
            OUT / "stopped.json",
            {"reason": "Offline scoring integrity disagreement", "differences": differences},
        )
    batch = [p for p in pairs if p["case_id"] in reg["batches"][index]]
    junit = ET.Element("testsuite", name=f"expanded-business-quality-batch-{index}", tests="40")
    failed = skipped = 0
    for p in batch:
        for a in ARMS:
            node = ET.SubElement(
                junit,
                "testcase",
                name=p["case_id"] + "-" + a,
                classname=p["split"] + "." + p["category"],
            )
            if not p[a]["observed"]:
                ET.SubElement(node, "skipped", message="not_run")
                skipped += 1
            elif not p[a]["strict_correct"]:
                ET.SubElement(node, "failure", message=",".join(p[a]["error_categories"]))
                failed += 1
    junit.set("failures", str(failed))
    junit.set("skipped", str(skipped))
    junit.set("errors", "0")
    xmlpath = OUT / f"batch-{index}-business-quality.xml"
    with xmlpath.open("xb") as f:
        f.write(ET.tostring(junit, encoding="utf8", xml_declaration=True))
    write_new(OUT / f"batch-{index}-results.json", batch)
    write_new(
        OUT / f"batch-{index}-seal.json",
        {
            "created_at": datetime.now(UTC).isoformat(),
            "complete": skipped == 0,
            "offline_equal": not differences,
            "stopped": (OUT / "stopped.json").exists(),
            "observed": 40 - skipped,
            "quality_failed": failed,
            "results_sha256": sha(OUT / f"batch-{index}-results.json"),
            "junit_sha256": sha(xmlpath),
            "registration_sha256": sha(OUT / "registration.json"),
            "implementation_sha256": sha(OUT / "registration-r2.json"),
        },
    )
    cohorts = {}
    for split in ["all", "dev", "validation"]:
        selected = [p for p in pairs if split == "all" or p["split"] == split]
        complete = all(p[a]["observed"] for p in selected for a in ARMS)
        cohorts[split] = {
            "arms": aggregate(selected),
            "paired": paired(selected, complete),
            "complete": complete,
            "categories": {
                cat: aggregate([p for p in selected if p["category"] == cat])
                for cat in sorted({p["category"] for p in selected})
            },
        }
    val = cohorts["validation"]
    v = val["arms"]
    bg, q = v["bge"], v["qwen"]
    safe = not any(
        p[a].get("safety_violations") or p[a].get("infrastructure_failure")
        for p in pairs
        for a in ARMS
    )
    gates = {
        "A": (
            "failed"
            if not safe
            else "passed"
            if cohorts["all"]["complete"]
            else "not_established_partial"
        ),
        "B": "not_run_incomplete_validation",
        "C": "not_run_incomplete_validation",
    }
    if val["complete"]:
        gates["B"] = (
            "passed"
            if q["required_coverage"] > bg["required_coverage"]
            and q["fact_coverage"] > bg["fact_coverage"]
            and q["precision_micro"] >= bg["precision_micro"]
            and q["unrelated_returns"] <= bg["unrelated_returns"]
            and q["wrong_snapshot_returns"] <= bg["wrong_snapshot_returns"]
            else "not_established"
        )
        gates["C"] = (
            "positive_paired_difference"
            if val["paired"]["observed_paired_difference"] > 0
            else "not_established"
        )
    result = {
        "schema_version": "expanded-quality-results-1",
        "at": datetime.now(UTC).isoformat(),
        "status": "BLOCKED"
        if (OUT / "stopped.json").exists() or differences
        else "PASS"
        if cohorts["all"]["complete"]
        else "IN_PROGRESS",
        "cohorts": cohorts,
        "gates": gates,
        "differences": differences,
        "failures_including_false_retrieval": failures,
        "pairs": pairs,
        "paid_calls": 0,
        "live_quality": "not_run",
        "next_live_ready": cohorts["all"]["complete"]
        and safe
        and val["paired"]["observed_paired_difference"] >= 0,
        "registration_sha256": sha(OUT / "registration.json"),
        "implementation_sha256": sha(OUT / "registration-r2.json"),
    }
    write_new(OUT / f"summary-batch-{index}.json", result)
    print(
        json.dumps(
            {
                "batch": index,
                "observed": sum(p[a]["observed"] for p in pairs for a in ARMS),
                "quality_failures_in_batch": failed,
                "status": result["status"],
                "gates": gates,
            }
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--index", type=int, required=True, choices=range(5))
    offline(p.parse_args().index)
