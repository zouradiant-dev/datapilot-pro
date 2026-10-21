"""Explicit operator review and bounded deterministic metric runs; never MCP write tools."""

import asyncio
import json
from pathlib import Path

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding, DatasetScope
from datapilot.db.management import management_url
from datapilot.ingestion.common import read_file
from datapilot.runtime.mcp_client import metric_session
from datapilot.semantics.contracts import MetricDraft, MetricRequest, SemanticDraft
from datapilot.semantics.registry import RegistryStore
from datapilot.semantics.service import analyze


def add_commands(sub):
    semantic = sub.add_parser(
        "semantics", help="Confirm versioned SaaS mappings/metrics or run deterministic metrics"
    )
    commands = semantic.add_subparsers(dest="semantic_command", required=True)
    for name in ("confirm-mapping", "confirm-metric"):
        cmd = commands.add_parser(name)
        cmd.add_argument("file", type=Path)
        cmd.add_argument("--reviewed", action="store_true")
    cmd = commands.add_parser("run")
    cmd.add_argument(
        "file", type=Path, help="JSON list of one to ten version-pinned MetricRequest objects"
    )
    cmd = commands.add_parser(
        "evidence", help="Read source-scoped evidence through MCP, without writer credentials"
    )
    cmd.add_argument("evidence_id")
    cmd.add_argument("--dataset", required=True)
    cmd.add_argument("--version", type=int, required=True)


async def read_evidence(args):
    scope = DatasetScope(bindings=[DatasetBinding(dataset_id=args.dataset, version=args.version)])
    async with metric_session(Settings(llm_mode="fake"), scope) as tools:
        return await tools.evidence(args.dataset, args.evidence_id)


def run(args):
    if args.semantic_command == "evidence":
        try:
            print(asyncio.run(read_evidence(args)).model_dump_json(indent=2))
            return 0
        except AgentFailure as exc:
            print(json.dumps({"error": exc.error.model_dump()}, ensure_ascii=False))
            return 2
    raw = read_file(args.file, 256 * 1024).decode("utf-8-sig")
    store = RegistryStore(management_url("registry"))
    try:
        if args.semantic_command == "confirm-mapping":
            result = store.confirm_semantics(
                SemanticDraft.model_validate_json(raw), reviewed=args.reviewed
            )
        elif args.semantic_command == "confirm-metric":
            result = store.confirm_metric(
                MetricDraft.model_validate_json(raw), reviewed=args.reviewed
            )
        else:
            payload = json.loads(raw)
            if not isinstance(payload, list) or not 1 <= len(payload) <= 10:
                raise ValueError("Use a list of at most ten metric requests")
            requests = [MetricRequest.model_validate_json(json.dumps(v)) for v in payload]
            result = asyncio.run(analyze(Settings(llm_mode="fake"), store, requests))
        print(result.model_dump_json(indent=2))
        if args.semantic_command == "run" and any(
            o.verification.verdict == "rejected" for o in result.outcomes
        ):
            return 2
        return 0
    except AgentFailure as exc:
        print(json.dumps({"error": exc.error.model_dump()}, ensure_ascii=False))
        return 2
    finally:
        store.close()
