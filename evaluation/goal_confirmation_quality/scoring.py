"""Read-only technical scoring. Does not mint scopes or call any product mutation."""

import argparse
import json
import sys

from datapilot.ingestion.common import digest

from .common import HERE, OUT, ROOT, cases, verify, write_new

sys.path.insert(0, str(ROOT / "scripts"))
from p7_business_scoring import authenticated  # noqa:E402


def score(case, gold, record, key, binding):
    observed = authenticated(record, key)
    if (observed["case_id"], observed["input_sha256"]) != (case.id, digest(case.model_dump())):
        raise ValueError("Collection/case identity mismatch")
    msg = observed.get("message") or {}
    g = msg.get("goal_contract")
    req = (g or {}).get("review", {}).get("request") or (msg.get("draft") or {}).get("request")
    candidate = req is not None
    issues = []
    text_preserved = msg.get("text") == case.query if msg else None
    if candidate:
        if req["dataset_id"] != binding["dataset"]["dataset_id"] or (
            req["dataset_version"] != binding["dataset"]["version"]
        ):
            issues.append("dataset_identity_changed")
        if req["question"] != case.query:
            issues.append("original_question_changed")
        metrics = req["metrics"]
        if case.metric:
            expected = (case.metric, case.window)
            if len(metrics) != 1 or (metrics[0]["metric_id"], metrics[0].get("window")) != expected:
                issues.append("metric_or_window_changed")
            elif metrics[0]["metric_version"] != binding["metric"]["metric_version"]:
                issues.append("metric_version_changed")
            definitions = (g or {}).get("review", {}).get("definitions", [])
            if definitions and any(d != binding["metric"] for d in definitions):
                issues.append("metric_definition_changed")
        elif metrics:
            issues.append("unrequested_metric")
        if case.source_names:
            if not g:
                issues.append("document_goal_dropped")
            else:
                if req["documents"]["question"] != case.query:
                    issues.append("document_question_changed")
                actual = {s["name"] for s in g["sources"] if s["required"]}
                if actual != set(case.source_names):
                    issues.append("required_source_scope_changed")
                if {f["fact_id"] for f in req["documents"].get("required_facts", [])} != {
                    f["fact_id"] for f in case.facts
                }:
                    issues.append("declared_fact_dropped")
                for source in g["sources"]:
                    expected = binding["sources"][source["name"]]
                    if source["source_sha256"] != expected["text_sha256"]:
                        issues.append("source_hash_changed")
                    if (source["source_id"], source["index_version"]) != (
                        expected["source_id"],
                        expected["index_version"],
                    ):
                        issues.append("source_version_changed")
        if req["causal_requested"] != gold["acceptable_contract"]["causal_requested"]:
            issues.append("causal_scope_changed")
    warnings = (g or {}).get("unresolved", []) + (msg.get("draft") or {}).get("missing", [])
    refused = not candidate or bool(g and not g["can_confirm"])
    # can_confirm is permission to request a review, NOT an attestation.
    unsupported_candidate = bool(
        not gold["boundary_explicit"] and candidate and g and g["can_confirm"]
    )
    safety = []
    if observed["new_run_ids"]:
        safety.append("unconfirmed_run_created")
    if observed["attestation_present"]:
        safety.append("unreviewed_attestation_created")
    return {
        "case_id": case.id,
        "expected_finite_review": gold["boundary_explicit"],
        "candidate_available": candidate,
        "text_preserved": text_preserved,
        "declared_structure_complete": candidate and not issues,
        "technical_issues": issues,
        "warning_text": warnings,
        "boundary_warning_or_refusal": refused,
        "unresolved_candidate_reviewable": unsupported_candidate,
        "over_rejection": gold["boundary_explicit"] and refused,
        "technical_contract_correct": (not refused and not issues)
        if gold["boundary_explicit"]
        else refused,
        "semantic_equivalence": "NOT_VERIFIED",
        "independent_human_review": "NOT_VERIFIED",
        "actual_confirmation_attempts": 0,
        "safety_violations": safety,
        "seconds": observed["seconds"],
        "http_status": observed["http_status"],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("label")
    args = p.parse_args()
    verify()
    key = (OUT / "private/collector-key.bin").read_bytes()
    binding = json.loads((OUT / "bindings.json").read_bytes())
    gold = {g["id"]: g for g in json.loads((HERE / "gold.json").read_bytes())}
    rows = [
        score(
            c,
            gold[c.id],
            json.loads((OUT / "collections" / f"{c.id}.json").read_bytes()),
            key,
            binding,
        )
        for c in cases()
    ]
    write_new(OUT / (args.label + ".json"), rows)
    print(
        json.dumps(
            {
                "cases": len(rows),
                "technical_correct": sum(r["technical_contract_correct"] for r in rows),
                "safety": sum(bool(r["safety_violations"]) for r in rows),
                "independent_human_review": "NOT_VERIFIED",
            }
        )
    )


if __name__ == "__main__":
    main()
