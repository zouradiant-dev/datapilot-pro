"""Isolated runner/collector adapters. No Gold imports, alternate runtime or verifier."""

import argparse
import json
import os
from pathlib import Path

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.persistence.backend import Backend, DurableArtifacts, execute
from datapilot.persistence.inspection import inspect_run
from datapilot.persistence.session import encode, run_async, run_durable
from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import ReportScope


def configuration(raw):
    value = json.loads(raw)
    # Gate 2B CLI cannot execute an actual sealed case, including with Fake decisions.
    if value["phase"] != "gate2b_toy" or not value["case_id"].startswith("toy-"):
        raise ValueError("Gate 2B permits only unrelated Toy execution")
    settings = Settings(_env_file=None, **value["settings"])
    if settings.llm_mode != "fake" or settings.api_key:
        raise ValueError("No paid model or key in Gate 2B runner")
    infrastructure = value.get("infrastructure_environment", {})
    if set(infrastructure) - {"DATAPILOT_REGISTRY_DATABASE_URL"}:
        raise ValueError("Only the original restricted P3 writer may enter the trusted host")
    os.environ.update(infrastructure)
    scope = ReportScope.model_validate_json(json.dumps(value["report_scope"]))
    rag = (
        RagScope.model_validate_json(json.dumps(value["rag_scope"]))
        if value.get("rag_scope")
        else None
    )
    if digest(scope.question) != value["question_sha256"] or scope.owner != value["owner"]:
        raise ValueError("Runner goal/owner differs from trusted launch record")
    return value, settings, scope, rag


async def collect(value, settings, scope, rag):
    """Original inspect_run revalidates P3, RAG, report, tasks, Manifest and ledger."""
    backend = Backend(
        settings.runtime_database_url.get_secret_value(), value["run_id"], scope.owner
    )
    try:
        # Same original run lease prevents a worker publishing against our collection snapshot.
        with backend.lease():
            snapshot = await inspect_run(
                settings,
                value["run_id"],
                scope.owner,
                scope.question,
                report_scope=scope,
                rag_scope=rag,
            )
            artifacts = DurableArtifacts(backend).export()
            with backend.transaction() as conn:
                manifest = backend.authorize(conn)
                calls = (
                    execute(
                        conn, "SELECT * FROM execution.calls WHERE run_id=:r", r=value["run_id"]
                    )
                    .mappings()
                    .all()
                )
                events = (
                    execute(
                        conn,
                        "SELECT payload FROM execution.events WHERE run_id=:r ORDER BY event_id",
                        r=value["run_id"],
                    )
                    .scalars()
                    .all()
                )
            # Private collection preserves full original call payload hashes and artifact closure.
            clean_calls = [
                {
                    k: c[k]
                    for k in [
                        "call_key",
                        "kind",
                        "account",
                        "tool_name",
                        "status",
                        "payload",
                        "payload_hash",
                        "usage",
                        "elapsed_ms",
                    ]
                }
                for c in calls
            ]
            payload = {
                "schema_version": "p7-collected-run-1",
                "case_id": value["case_id"],
                "run_id": value["run_id"],
                "question_sha256": value["question_sha256"],
                "manifest_sha256": manifest["manifest_hash"],
                "manifest": manifest["manifest"],
                "cancelled": manifest["cancelled"],
                "snapshot": encode(snapshot),
                "calls": clean_calls,
                "events": events,
                "artifacts": {k: a.model_dump(mode="json") for k, a in artifacts.items()},
                "collector": "original_inspect_run_under_original_run_lease",
                "model_mode": settings.llm_mode,
                "actual_provider_cost": None,
                "actual_provider_cost_status": "not_applicable_fake",
            }
            return payload
    finally:
        backend.close()


async def main(args):
    value, settings, scope, rag = configuration(args.config.read_bytes())
    if args.action == "collect":
        return await collect(value, settings, scope, rag)
    return encode(
        await run_durable(
            settings,
            value["run_id"],
            scope.question,
            owner=scope.owner,
            resume=args.action != "start",
            approve=True if args.action == "approve" else None,
            require_review=True,
            report_scope=scope,
            rag_scope=rag,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "resume", "approve", "collect"])
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run_async(main(args)), ensure_ascii=False))
    except AgentFailure as error:
        print(json.dumps({"error": error.error.model_dump()}))
        raise SystemExit(2) from None
