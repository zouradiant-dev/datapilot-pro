"""Offline business Holdout authoring contracts; no model or database write entry point."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from datapilot.datasets.contracts import DatasetScope
from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import DocumentGoal
from datapilot.semantics.contracts import MetricRequest


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: str = Field(pattern=r"^bh2-\d{3}$")
    lane: Literal["sql_only", "rag_only", "sql_rag"]
    objective: str = Field(min_length=4, max_length=120)
    question: str = Field(min_length=16, max_length=8000)
    owner: str = Field(min_length=1, max_length=64)
    datasets: DatasetScope
    metrics: list[MetricRequest] = Field(max_length=6)
    document_goal: DocumentGoal | None = None
    rag_scope: RagScope | None = None
    causal_requested: bool = False
    review_required: Literal[True] = True

    @model_validator(mode="after")
    def lane_matches_payload(self):
        if bool(self.metrics) != (self.lane != "rag_only"):
            raise ValueError("Lane and actual metric goals differ")
        if (self.document_goal is not None) != (self.lane != "sql_only"):
            raise ValueError("Lane and actual document goal differ")
        if self.document_goal is not None and self.rag_scope is None:
            raise ValueError("Document goals need an explicit host scope")
        if self.rag_scope and self.rag_scope.owner != self.owner:
            raise ValueError("A source cannot confer another owner's authority")
        if not self.metrics and self.document_goal.question != self.question:
            raise ValueError("RAG-only must preserve the full original question")
        goals = [m.goal_id for m in self.metrics]
        if len(goals) != len(set(goals)):
            raise ValueError("Duplicate metric goal")
        if self.document_goal and set(self.document_goal.metric_goals) != set(goals):
            raise ValueError("Document/metric associations must be explicit")
        return self


class NumericGold(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    goal_id: str
    disposition: Literal["verified", "unavailable"]
    value: str | None = None
    unit: str
    reason: str | None = None
    numerator: int | None = None
    denominator: int | None = None
    window_days: int | None = None

    @model_validator(mode="after")
    def not_a_self_verified_business_result(self):
        if self.disposition == "verified" and (self.value is None or self.reason):
            raise ValueError("Numeric Gold needs an exact value, not a refusal")
        if self.disposition == "unavailable" and (self.value is not None or not self.reason):
            raise ValueError("Unavailable Gold cannot publish a number")
        if self.value is not None and re.fullmatch(r"-?\d+(?:\.\d+)?", self.value) is None:
            raise ValueError("Use finite exact Decimal text, never float or exponent")
        return self


class Gold(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: str = Field(pattern=r"^bh2-\d{3}$")
    business_completion: Literal["completed", "partial", "unavailable", "blocked"]
    host_decision: Literal["review_then_run", "permission_denied", "confirmation_required"]
    metrics: list[NumericGold] = Field(max_length=6)
    retrieval: dict | None = None
    refusal_conditions: list[str] = Field(max_length=12)
    causal_claim_must_remain_unverified: bool


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def normalized_question(text):
    return " ".join(re.sub(r"\d+", "#", text.casefold()).split())


def old_question_inputs(raw):
    """Extract only encoded question strings; do not decode an old expected/Gold value."""
    result = []
    for line in raw.decode("utf-8").splitlines():
        match = re.search(r'"question"\s*:\s*("(?:[^"\\]|\\.)*")', line)
        if not match:
            raise ValueError("Old task has no bounded question input")
        result.append({"question": json.loads(match.group(1))})
    return result


def shingles(text):
    text = normalized_question(text)
    return {text[i : i + 3] for i in range(max(0, len(text) - 2))}


def input_leakage(inputs, old_inputs, *, old_source_hashes, new_source_hashes):
    """Uses old question inputs only. No old Gold or candidate outputs are inspected."""
    texts = {r["question"] for r in old_inputs}
    normal = {normalized_question(s) for s in texts}
    old_shingles = [shingles(s) for s in texts]
    exact, numeric, near = [], [], []
    for case in inputs:
        if case.question in texts:
            exact.append(case.case_id)
        if normalized_question(case.question) in normal:
            numeric.append(case.case_id)
        parts = shingles(case.question)
        overlap = max(
            (
                len(parts & other) / len(parts | other) if parts | other else 0
                for other in old_shingles
            ),
            default=0,
        )
        if overlap >= 0.8:
            near.append({"case_id": case.case_id, "jaccard_3gram": overlap})
    return {
        "old_input_records": len(old_inputs),
        "new_input_records": len(inputs),
        "exact_question_overlap": exact,
        "numeric_normalized_question_overlap": numeric,
        "near_duplicate_warnings": near,
        "source_byte_overlap": sorted(set(old_source_hashes) & set(new_source_hashes)),
        "old_gold_used_for_candidate_tuning": False,
        "independent_human_authorship": False,
    }


def validate_inputs(inputs):
    if len(inputs) < 50 or len({r.case_id for r in inputs}) != len(inputs):
        raise ValueError("At least 50 unique business task identities required")
    if len({r.objective for r in inputs}) != len(inputs):
        raise ValueError("A date substitution is not a new declared business objective")
    if len({normalized_question(r.question) for r in inputs}) != len(inputs):
        raise ValueError("Do not inflate tasks through date/number-only rewrites")
    if Counter(r.lane for r in inputs) != {"sql_only": 20, "rag_only": 20, "sql_rag": 20}:
        raise ValueError("Use the pre-registered 20/20/20 lane denominators")


def seal(destination, *, inputs, gold, assets, pins, leakage, proof, freeze, canary):
    """One-time author operation. An evaluation consumer receives inputs/assets, never Gold."""
    validate_inputs(inputs)
    if [r.case_id for r in inputs] != [r.case_id for r in gold]:
        raise ValueError("Gold order/coverage differs from task identity")
    for task, answer in zip(inputs, gold, strict=True):
        requested = {m.goal_id for m in task.metrics}
        expected = {m.goal_id for m in answer.metrics}
        if not expected <= requested or (
            answer.host_decision == "review_then_run" and requested != expected
        ):
            raise ValueError("Gold does not cover the original metric goals")
        if answer.business_completion == "completed" and (
            any(m.disposition != "verified" for m in answer.metrics)
            or (answer.retrieval and answer.retrieval["disposition"] != "complete")
            or answer.causal_claim_must_remain_unverified
        ):
            raise ValueError("Completed Gold cannot hide missing or causal evidence")
    if any(
        leakage[k]
        for k in (
            "exact_question_overlap",
            "numeric_normalized_question_overlap",
            "source_byte_overlap",
            "near_duplicate_warnings",
        )
    ):
        raise ValueError("Leakage audit failed before sealing")
    if proof.get("status") != "passed" or proof.get("database_writes") != 0:
        raise ValueError("Numerical Gold requires the real read-only PG/MCP cross-check")
    if destination.exists():
        raise ValueError("Refuse to overwrite or reseal an existing Holdout")
    inputs_raw = b"".join(canonical(r.model_dump(mode="json")) + b"\n" for r in inputs)
    gold_raw = b"".join(canonical(r.model_dump(mode="json")) + b"\n" for r in gold)
    if canary.encode() in inputs_raw or any(canary.encode() in raw for raw in assets.values()):
        raise ValueError("Evaluation-only canary leaked into an executable input/source")
    destination.mkdir(parents=True)
    (destination / "inputs.jsonl").write_bytes(inputs_raw)
    (destination / "gold.jsonl").write_bytes(gold_raw)
    (destination / "evaluator-only.json").write_bytes(canonical({"canary": canary}))
    (destination / "pins.json").write_bytes(canonical(pins))
    (destination / "oracle-proof.json").write_bytes(canonical(proof))
    (destination / "candidate-freeze.json").write_bytes(canonical(freeze))
    source_dir = destination / "assets"
    source_dir.mkdir()
    for name, raw in assets.items():
        target = (source_dir / name).resolve()
        if not target.is_relative_to(source_dir.resolve()) or Path(name).suffix not in {
            ".csv",
            ".xlsx",
            ".md",
            ".txt",
        }:
            raise ValueError("Only reviewed source assets may enter the materialization closure")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    files = {
        str(p.relative_to(destination)).replace("\\", "/"): sha(p.read_bytes())
        for p in sorted(destination.rglob("*"))
        if p.is_file()
    }
    marker = {"version": "business-holdout-seal-1", "files": files, "live_allowed": False}
    (destination / "SEALED.json").write_bytes(canonical(marker))
    return marker


def verify_seal(destination, *, expected_seal_sha256):
    """Hash-only integrity check; does not decode Gold, score a candidate or enable Live."""
    raw = (destination / "SEALED.json").read_bytes()
    if sha(raw) != expected_seal_sha256:
        raise ValueError("Seal anchor changed")
    marker = json.loads(raw)
    actual_files = {
        str(p.relative_to(destination)).replace("\\", "/")
        for p in destination.rglob("*")
        if p.is_file()
    }
    if actual_files != set(marker["files"]) | {"SEALED.json"}:
        raise ValueError("Unregistered file added to sealed pack")
    for name, expected in marker["files"].items():
        path = (destination / name).resolve()
        if (
            (destination / name).is_symlink()
            or not path.is_relative_to(destination.resolve())
            or sha(path.read_bytes()) != expected
        ):
            raise ValueError("Sealed payload changed")
    return {"files_checked": len(marker["files"]), "gold_decoded": False, "live_allowed": False}
