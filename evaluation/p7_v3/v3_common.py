"""Versioned P7 evaluation adapters; product Runtime and historical freezes are unchanged."""

import json
import sys
from pathlib import Path

from pydantic import Field, model_validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from p7_holdout_pack import CaseInput, Gold, canonical, sha, verify_seal  # noqa: E402
from p7_smoke_pack import PROFILE, infrastructure, settings_for, write_new  # noqa: E402
from p7_smoke_run import scope_for  # noqa: E402
from p7_smoke_run import verify_freeze as parent_freeze  # noqa: E402

__all__ = ["PROFILE", "canonical", "infrastructure", "sha", "write_new"]

BASE = ROOT / "artifacts/p7/independent-holdout-v3"
PACK = BASE / "sealed"
OWNER = "p7-chengyue-independent-v3"
CAMPAIGN = "p7-business-independent-v3-first-live"
BUDGET = {
    "version": "p7-business-v3-budget-1",
    "planned_cases": 60,
    "runtime_runs": 54,
    "root_calls": 8,
    "root_tokens": 18000,
    "child_calls": 4,
    "child_tokens": 18000,
    "output_tokens": 1200,
    "provider_attempts": 432,
    "campaign_token_units": 972000,
    "partition_runtime_counts": [5] * 10 + [4],
    "partition_tokens": [90000] * 10 + [72000],
    "concurrency": 1,
    "sdk_retries": 0,
    "outer_retries": 0,
    "provider_timeout_seconds": 30,
    "task_timeout_seconds": 180,
    "campaign_timeout_seconds": 10800,
    "max_estimated_peak_usd": "1.1664",
    "paid_authorized": False,
}


class Case(CaseInput):
    case_id: str = Field(pattern=r"^p7-holdout-v3-\d{3}$")

    @model_validator(mode="after")
    def lane_matches_payload(self):
        if bool(self.metrics) != (self.lane != "rag_only"):
            raise ValueError("Lane/metric mismatch")
        if (self.document_goal is not None) != (self.lane != "sql_only"):
            raise ValueError("Lane/document mismatch")
        if self.document_goal and (not self.rag_scope or self.rag_scope.owner != self.owner):
            raise ValueError("Missing delegated document identity")
        if not self.metrics and self.document_goal.question != self.question:
            raise ValueError("Pure document task must preserve original question")
        # Production ReportScope allows a document to support a subset of metric goals.
        goals = [m.goal_id for m in self.metrics]
        if len(goals) != len(set(goals)):
            raise ValueError("Duplicate metric goal")
        if self.document_goal and not set(self.document_goal.metric_goals) <= set(goals):
            raise ValueError("Unknown document/metric association")
        return self


class Answer(Gold):
    case_id: str = Field(pattern=r"^p7-holdout-v3-\d{3}$")
    expected_codes: dict[str, list[str]] = Field(default_factory=dict)
    expected_verdicts: dict[str, str] = Field(default_factory=dict)
    missing_fact_ids: list[str] = Field(default_factory=list)
    minimum_cited_sources: int = 0
    host_code: str | None = None
    tags: list[str] = Field(default_factory=list)
    retrieval_expected: str | None = None
    document_missing_codes: list[str] = Field(default_factory=list)


def scope(task):
    return scope_for(task)


def load():
    anchor = json.loads((BASE / "anchor.json").read_bytes())
    verify_seal(PACK, expected_seal_sha256=anchor["case_gold_seal_sha256"])
    tasks = [
        Case.model_validate_json(row) for row in (PACK / "inputs.jsonl").read_bytes().splitlines()
    ]
    return tasks, json.loads((PACK / "pins.json").read_bytes()), anchor


def verify():
    parent, product = parent_freeze()
    anchor = json.loads((BASE / "anchor.json").read_bytes())
    raw = (BASE / "implementation-freeze.json").read_bytes()
    if sha(raw) != anchor["implementation_manifest_sha256"]:
        raise ValueError("FREEZE_INVALIDATED: v3 implementation anchor")
    manifest = json.loads(raw)
    if manifest["parent_manifest_sha256"] != parent["manifest_sha256"]:
        raise ValueError("FREEZE_INVALIDATED: product parent")
    current = {
        "evaluation/p7_v3/" + name: value
        for name, value in file_map(ROOT / "evaluation/p7_v3").items()
        if name.endswith(".py")
    }
    if current != manifest["evaluation_files"]:
        raise ValueError("FREEZE_INVALIDATED: evaluation executable closure differs")
    for name, expected in manifest["evaluation_files"].items():
        path = ROOT / name
        if path.is_symlink() or sha(path.read_bytes()) != expected:
            raise ValueError("FREEZE_INVALIDATED: evaluation adapter")
    load()
    for name, expected in manifest["protocol_files"].items():
        if sha((BASE / name).read_bytes()) != expected:
            raise ValueError("FREEZE_INVALIDATED: protocol/budget/scorer")
    return anchor, manifest, product


def clean_settings(values, mode="fake", key=None):
    return settings_for(values, mode=mode, key=key)


def read_answers():
    return {
        g.case_id: g
        for g in [
            Answer.model_validate_json(row)
            for row in (PACK / "gold.jsonl").read_bytes().splitlines()
        ]
    }


def file_map(directory):
    return {
        f.relative_to(directory).as_posix(): sha(f.read_bytes())
        for f in sorted(directory.rglob("*"))
        if f.is_file() and "__pycache__" not in f.parts
    }


def expected_order():
    # Interleave lanes so ordinary failures do not systematically censor combined tasks.
    return [f"p7-holdout-v3-{n:03}" for i in range(20) for n in (i + 1, i + 21, i + 41)]
