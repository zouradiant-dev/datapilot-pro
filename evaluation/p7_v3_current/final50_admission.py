"""Read-only admission for the three Final 50 follow-up drafts."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from formal_runner import Answer, Case, load, score
from pydantic import Field

from datapilot.datasets.repository import DatasetRepository
from datapilot.ingestion.common import digest
from datapilot.rag.storage import Repository as RagRepository
from datapilot.reporting.contracts import ReportScope
from datapilot.semantics.recipes import request_missing
from datapilot.semantics.repository import MetricRepository

CASE_PATTERN = r"^p7-final50-admit-(017|064|077)$"
CASE_IDS = {f"p7-final50-admit-{suffix}" for suffix in ("017", "064", "077")}


class AdmissionCase(Case):
    case_id: str = Field(pattern=CASE_PATTERN)


class AdmissionAnswer(Answer):
    case_id: str = Field(pattern=CASE_PATTERN)


def load_drafts(pack):
    drafts = load(pack / "draft-contracts.json")
    if len(drafts) != len(CASE_IDS) or {row["case_id"] for row in drafts} != CASE_IDS:
        raise ValueError("Expected the three distinct admission cases")
    evidence = load(pack / "oracle-evidence.json")
    expected = {(row["case_id"], row["goal_id"]): row for row in evidence}
    if len(expected) != len(evidence):
        raise ValueError("Duplicate oracle evidence")
    consumed = set()
    for draft in drafts:
        scope = ReportScope.model_validate_json(json.dumps(draft["report_scope"]))
        cid = draft["case_id"]
        case = AdmissionCase.model_validate_json(
            json.dumps(
                {
                    "case_id": cid,
                    "lane": "sql_rag" if scope.document_goal else "sql_only",
                    "objective": "Final 50 metric definition follow-up",
                    **scope.model_dump(
                        mode="json",
                        include={
                            "question",
                            "owner",
                            "datasets",
                            "metrics",
                            "document_goal",
                            "causal_requested",
                        },
                    ),
                    "rag_scope": draft["rag_scope"],
                }
            )
        )
        if case.rag_scope and case.rag_scope.datasets != scope.datasets:
            raise ValueError("RAG and report dataset scopes differ")
        metric_rows = [expected[cid, req.goal_id] for req in scope.metrics]
        consumed.update((cid, req.goal_id) for req in scope.metrics)
        metrics = [{"goal_id": row["goal_id"], **row["decimal_oracle"]} for row in metric_rows]
        answer = AdmissionAnswer.model_validate(
            {
                "case_id": cid,
                "business_completion": "partial" if cid.endswith("017") else "completed",
                "host_decision": "review_then_run",
                "metrics": metrics,
                "expected_codes": {
                    row["goal_id"]: [row["reason"]] for row in metrics if row.get("reason")
                },
                "expected_verdicts": {row["goal_id"]: row["disposition"] for row in metrics},
                "minimum_cited_sources": int(case.document_goal is not None),
                "refusal_conditions": [],
                "causal_claim_must_remain_unverified": scope.causal_requested,
            }
        )
        yield draft, scope, case, answer, metric_rows
    if consumed != set(expected):
        raise ValueError("Unbound oracle evidence")


def score_admission(case, answer, signed_collection, key, pins):
    if not isinstance(case, AdmissionCase) or not isinstance(answer, AdmissionAnswer):
        raise ValueError("Admission scorer requires the new case and Gold contracts")
    if case.case_id != answer.case_id:
        raise ValueError("Admission case and Gold identities differ")
    return score(case, answer, signed_collection, key, pins)


def isolated_reader(env, role):
    url = env[f"DATAPILOT_{role}_DATABASE_URL"]
    target = urlsplit(url)
    if (target.hostname, target.port, target.path) != ("127.0.0.1", 55450, "/datapilot_p7"):
        raise ValueError("Unexpected isolated database identity")
    return url


def preflight(pack, env, *, case_id=None):
    sql = isolated_reader(env, "UPLOAD_READER")
    rag_url = isolated_reader(env, "RAG_READER")
    rows = []
    for draft, scope, case, answer, evidence in load_drafts(pack):
        if case_id and case.case_id != case_id:
            continue
        repo = DatasetRepository(sql, scope.datasets)
        try:
            for req, row in zip(scope.metrics, evidence, strict=True):
                ctx = MetricRepository(repo).context(req)
                if request_missing(ctx, req) or (
                    ctx.source_sha256,
                    ctx.semantic_sha256,
                    ctx.metric_sha256,
                ) != (row["source_sha256"], row["semantic_sha256"], row["metric_sha256"]):
                    raise ValueError(f"Metric identity or readiness drift: {case.case_id}")
        finally:
            repo.close()
        if case.rag_scope:
            proof = draft["document_pin_evidence"]
            reader = RagRepository(rag_url, case.rag_scope)
            try:
                manifest = reader.manifests()[proof["corpus_id"]]
                (pin,) = (p for p in case.rag_scope.corpora if p.corpus_id == proof["corpus_id"])
                if pin.index_version != proof["index_version"]:
                    raise ValueError("Document index binding changed")
                (source,) = (s for s in manifest.sources if s.document_id == proof["document_id"])
                if (
                    source.source_id != proof["source_id"]
                    or source.version != proof["source_sha256"]
                    or proof["chunk"] not in [s.model_dump(mode="json") for s in source.chunks]
                ):
                    raise ValueError("Document source or chunk binding changed")
            finally:
                reader.close()
        rows.append(
            {
                "case_id": case.case_id,
                "case_sha256": digest(case),
                "draft_gold_sha256": digest(answer),
                "report_scope_sha256": digest(scope),
                "status": "READ_ONLY_PREFLIGHT_PASS",
                "gold_review": "PENDING",
                "trusted_goal_confirmation": "PENDING" if case.rag_scope else "NOT_APPLICABLE",
            }
        )
    return {"cases": rows, "worker_dispatch": "NOT_RUN", "paid_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = preflight(args.pack, load(args.environment))
    with args.out.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(f"{len(result['cases'])} admission cases passed read-only preflight")


if __name__ == "__main__":
    main()
