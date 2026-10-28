# ruff: noqa: E402
"""Bounded cross-process Fake probe using the unchanged original Durable Runtime."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_phase4_postgres import BudgetDecisions, budget_settings

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import ReportScope

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["start", "resume"])
parser.add_argument("run_id")
parser.add_argument("input")
parser.add_argument("--pause", action="store_true")
parser.add_argument("--no-model", action="store_true")
parser.add_argument("--cut", choices=["tool_committed", "model_response"])
args = parser.parse_args()
path = Path(args.input).resolve()
assert path.is_file() and path.stat().st_size <= 1048576
data = json.loads(path.read_bytes())
rag = RagScope.model_validate_json(json.dumps(data["rag_scope"]))
scope = ReportScope.model_validate_json(json.dumps(data["report_scope"]))
count = 0


def fault(point):
    global count
    if point == args.cut:
        count += 1
        if count == (5 if args.cut == "model_response" else 4):
            os._exit(91)


class NoModel:
    async def respond(self, *_):
        raise AssertionError("Completed resume cannot call a model")


try:
    result = run_async(
        run_durable(
            budget_settings(Settings(_env_file=None, llm_mode="fake", api_key=None)),
            args.run_id,
            scope.question if args.action == "start" else None,
            owner=scope.owner,
            resume=args.action == "resume",
            rag_scope=rag,
            report_scope=scope,
            transport=NoModel() if args.no_model else BudgetDecisions(),
            interrupt_after=["worker"] if args.pause else None,
            fault=fault,
        )
    )
except AgentFailure as exc:
    print(json.dumps({"error": exc.error.code}))
    raise SystemExit(2) from None
print(
    json.dumps(
        {
            "status": result["status"],
            "usage": result["usage"],
            "business_completion": result["business_completion"].status
            if result.get("business_completion")
            else None,
            "report_sha256": digest(result["cross_source_report"])
            if result.get("cross_source_report")
            else None,
        }
    )
)
