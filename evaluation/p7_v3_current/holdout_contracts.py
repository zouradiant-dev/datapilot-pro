"""New Holdout contracts and host review drafts; no dispatch or implicit approval."""

import json
import sys
from pathlib import Path

from pydantic import Field, model_validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "p7_v3"))
from v3_common import Answer, Case  # noqa: E402

from datapilot.ingestion.common import digest  # noqa: E402
from datapilot.reporting.contracts import ReportScope  # noqa: E402

from .holdout_preparation import LANES, bind_drafts  # noqa: E402

CASE_PATTERN = r"^g2-bh-(sql|rag|xsrc)-(00[1-9]|01\d|020)$"
PROJECTION = {"owner", "question", "datasets", "metrics", "document_goal", "causal_requested"}


class HoldoutCase(Case):
    case_id: str = Field(pattern=CASE_PATTERN)
    report_scope: ReportScope

    @model_validator(mode="after")
    def exact_host_scope(self):
        if not self.case_id.startswith("g2-bh-" + LANES[self.lane] + "-"):
            raise ValueError("Holdout namespace and lane differ")
        if self.model_dump(mode="json", include=PROJECTION) != self.report_scope.model_dump(
            mode="json", include=PROJECTION
        ):
            raise ValueError("Case projection differs from the exact host ReportScope")
        if self.rag_scope and self.rag_scope.datasets != self.datasets:
            raise ValueError("RAG and report datasets differ")
        return self


class HoldoutAnswer(Answer):
    case_id: str = Field(pattern=CASE_PATTERN)


def compile_drafts(rows, bindings, task_bindings, revisions, candidate):
    """Compile authored inputs separately from private expectations and review decisions."""
    preparation = bind_drafts(rows, candidate)
    previous = {row["case_id"]: row for row in task_bindings}
    revised = {row["case_id"]: row for row in revisions}
    ids = {row["id"] for row in rows}
    if len(previous) != 60 or set(previous) != ids or not set(revised) <= ids:
        raise ValueError("Private binding identities differ from the 60 drafts")
    cases, reviews = [], []
    for row in rows:
        cid = row["id"]
        bound = revised.get(cid, previous[cid])
        request = bound.get("metric_request")
        corpora = [bindings["corpora"][name] for name in row.get("source_groups", [])]
        dataset_ids = {
            (item["dataset_id"], item["version"])
            for corpus in corpora
            for item in corpus["scope"]["datasets"]["bindings"]
        }
        if request:
            dataset_ids.add((request["dataset_id"], request["dataset_version"]))
        datasets = {"bindings": [{"dataset_id": d, "version": v} for d, v in sorted(dataset_ids)]}
        reasons = row.get("refusal_contract", {}).get("reason_codes", [])
        causal = "causal_unproven" in reasons or "causal" in row["tags"]
        doc = None
        if corpora:
            facts = [
                {"fact_id": f["fact_id"], "description": f["span_intent"]}
                for f in row.get("required_facts", [])
            ]
            authored = row["document_goal"]["purpose"]
            doc = {
                "goal_id": "documents",
                "question": row["question"],
                "metric_goals": [request["goal_id"]] if request else [],
                "purpose": "conclusion"
                if authored == "conclusion"
                else "facts"
                if facts
                else "locate",
                "required_facts": facts,
                "independent_facts": authored == "independent_facts",
            }
        scope = ReportScope.model_validate_json(
            json.dumps(
                {
                    "owner": "p7-g2-business-60-20261103",
                    "question": row["question"],
                    "datasets": datasets,
                    "metrics": [request] if request else [],
                    "document_goal": doc,
                    "causal_requested": causal,
                }
            )
        )
        rag = (
            {
                "owner": scope.owner,
                "datasets": datasets,
                "corpora": [c["scope"]["corpora"][0] for c in corpora],
            }
            if corpora
            else None
        )
        case = HoldoutCase.model_validate_json(
            json.dumps(
                {
                    "case_id": cid,
                    "lane": row["lane"],
                    "objective": "New business Holdout",
                    **scope.model_dump(mode="json", include=PROJECTION),
                    "rag_scope": rag,
                    "report_scope": scope.model_dump(mode="json"),
                }
            )
        )
        cases.append(case)
        reviews.append(
            {
                "case_id": cid,
                "authored_draft_sha256": digest(row),
                "case_sha256": digest(case),
                "report_scope_sha256": digest(scope),
                "revised": cid in revised,
                "gold_review": "REQUIRED" if cid in revised else "RECONFIRM_REQUIRED",
                "full_question_semantics_review": "REQUIRED",
                "goal_review": "REQUIRED" if doc else "NOT_APPLICABLE",
                "authored_document_purpose": row.get("document_goal", {}).get("purpose"),
                "partial_policy_review": "REQUIRED" if doc else "NOT_APPLICABLE",
                "proposed_scope_is_approved": False,
                "fact_proofs": previous[cid]["document_facts"],
                "expected_status": row["expected_status"],
                "authored_oracle": row.get("oracle"),
                "refusal_contract": row.get("refusal_contract"),
                "launch": "NOT_READY",
            }
        )
    return cases, reviews, preparation
