"""Independent offline re-score and paired aggregates, with fixed planned denominators."""

import json
from collections import Counter
from statistics import mean

from .common import ARMS, OUT, load, sha, write_new
from .prepare import verify_registration
from .scoring import score


def average(rows, name):
    values = [row[name] for row in rows if row.get(name) is not None]
    return mean(values) if values else None


def main():
    verify_registration()
    binding = json.loads((OUT / "bindings.json").read_bytes())
    seal = json.loads((OUT / "bindings-seal.json").read_bytes())
    assert sha(OUT / "bindings.json") == seal["sha256"]
    key = (OUT / "collector-key-private.bin").read_bytes()
    pairs, rows, differences = [], [], []
    for case in load().cases:
        pair = {"case_id": case.id, "category": case.category, "gold": case.model_dump()}
        for arm in ARMS:
            path = OUT / "collections" / f"{case.id}-{arm}.json"
            if not path.exists():
                pair[arm] = {"actual_status": "not_run", "strict_correct": False}
                continue
            rated = score(case, arm, json.loads(path.read_bytes()), key, binding)
            old = json.loads((OUT / "scores" / path.name).read_bytes())
            if rated != old:
                differences.append({"case_id": case.id, "arm": arm})
            pair[arm] = rated
            rows.append(rated)
        pairs.append(pair)
    arms = {}
    for arm in ARMS:
        observed = [r for r in rows if r["arm"] == arm]
        arms[arm] = {
            "planned": 16,
            "observed": len(observed),
            "not_run": 16 - len(observed),
            "strict_correct": sum(r["strict_correct"] for r in observed),
            "strict_correct_over_planned": sum(r["strict_correct"] for r in observed) / 16,
            "status_counts": dict(Counter(r["actual_status"] for r in observed)),
            "source_recall_at_3": average(observed, "source_recall_at_3"),
            "source_precision_nonempty": average(observed, "source_precision"),
            "required_coverage": average(observed, "required_coverage"),
            "all_required": sum(r["all_required"] is True for r in observed),
            "retrieval_applicable_observed": sum(
                r["source_recall_at_3"] is not None for r in observed
            ),
            "fact_coverage": average(observed, "fact_coverage"),
            "irrelevant_sources": sum(len(r.get("unrelated_sources", [])) for r in observed),
            "citation_count": sum(r.get("citation_count", 0) for r in observed),
            "correct_citation_count": sum(r.get("correct_citation_count", 0) for r in observed),
            "worker_complete": sum(r["worker_complete"] is True for r in observed),
            "false_completion": sum(r["false_completion"] for r in observed),
            "unsupported_claims": sum(r["unsupported_claims"] for r in observed),
            "safety_violations": sum(len(r["safety_violations"]) for r in observed),
            "infrastructure_failures": sum(r["infrastructure_failure"] for r in observed),
            "provider_calls": 0,
            "categories": {},
        }
        for category in sorted({c.category for c in load().cases}):
            selected = [p[arm] for p in pairs if p["category"] == category]
            arms[arm]["categories"][category] = {
                "planned": 2,
                "strict_correct": sum(r["strict_correct"] for r in selected),
                "required_coverage": average(selected, "required_coverage"),
                "fact_coverage": average(selected, "fact_coverage"),
            }
    complete = len(rows) == 32 and not differences
    b, q = arms["bge"], arms["qwen"]
    gates = {
        "A_safety": complete and not sum(a["safety_violations"] for a in arms.values()),
        "B_evidence": complete
        and q["required_coverage"] > b["required_coverage"]
        and q["fact_coverage"] > b["fact_coverage"]
        and q["irrelevant_sources"] <= b["irrelevant_sources"],
        "C_report": complete and q["strict_correct"] > b["strict_correct"],
    }
    write_new(OUT / "paired-results.json", pairs)
    write_new(
        OUT / "summary.json",
        {
            "arms": arms,
            "gates": gates,
            "offline_differences": differences,
            "registration_sha256": sha(OUT / "registration.json"),
            "bindings_sha256": seal["sha256"],
            "paid_api_calls": 0,
            "live_quality": "not_run",
            "safety_or_infrastructure_stop": (OUT / "stopped.json").exists(),
        },
    )
    print(json.dumps({"observed_pairs": len(rows), "gates": gates, "differences": differences}))


if __name__ == "__main__":
    main()
