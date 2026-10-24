"""Actual labelled P7 PG instance restart and cross-process Durable observations.

No live model calls, original database operations, volume removal or user Run IDs.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from p7_isolated_pg import environment, inspect
from p7_isolated_pg import main as pg_main

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.harness.budget import RunBudget
from datapilot.ingestion.common import digest
from datapilot.llm.fake import FakeModelClient
from datapilot.orchestration.model import FakeTransport
from datapilot.persistence.backend import Backend, execute
from datapilot.persistence.session import encode, run_async, run_durable

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/p7/restart-v2"


class BlockedDecision:
    """A deterministic blocked model double; only the PG restart is real."""

    def __init__(self, settings, marker):
        self.inner = FakeTransport(FakeModelClient(settings, RunBudget(8, 18000)))
        self.marker = marker

    async def respond(self, messages, tools):
        self.marker.write_text("Original Journal has issued this decision", encoding="utf-8")
        for _ in range(300):
            if self.marker.with_suffix(".release").exists():
                return await self.inner.respond(messages, tools)
            await asyncio.sleep(0.05)
        raise RuntimeError("Bounded P7 fixture release deadline")


def snapshot(settings, id_):
    backend = Backend(settings.runtime_database_url.get_secret_value(), id_, "local-user")
    try:
        with backend.transaction() as conn:
            run = backend.authorize(conn)
            calls = (
                execute(
                    conn,
                    (
                        "SELECT kind,status,payload_hash,ticket,usage FROM execution.calls "
                        "WHERE run_id=:r ORDER BY call_key"
                    ),
                    r=id_,
                )
                .mappings()
                .all()
            )
            ledger = execute(
                conn, "SELECT payload FROM execution.ledger WHERE run_id=:r", r=id_
            ).scalar_one()
            refs = (
                execute(
                    conn,
                    (
                        "SELECT artifact_id,kind FROM execution.artifacts "
                        "WHERE run_id=:r ORDER BY artifact_id"
                    ),
                    r=id_,
                )
                .mappings()
                .all()
            )
        return {
            "run_id": id_,
            "manifest_sha256": run["manifest_hash"],
            "cancelled": run["cancelled"],
            "calls": [dict(r) for r in calls],
            "ledger": ledger,
            "artifacts": [dict(r) for r in refs],
        }
    finally:
        backend.close()


def child(args):
    os.environ.update(environment())
    settings = Settings(llm_mode="fake")
    try:
        result = run_async(
            run_durable(
                settings,
                args.run_id,
                "查询客户总数" if args.action == "start" else None,
                resume=args.action == "resume",
                approve=True if args.approve else None,
                require_review=args.review,
                interrupt_after=["worker"] if args.pause else None,
                transport=BlockedDecision(settings, Path(args.marker)) if args.marker else None,
            )
        )
        safe = {
            "status": result["status"],
            "usage": result["usage"],
            "results_sha256": digest(encode(result.get("results", {}))),
            "result": encode(result.get("result")),
            "error_code": None,
        }
    except AgentFailure as exc:
        safe = {"status": "blocked", "error_code": exc.error.code}
    except Exception as exc:
        safe = {"status": "failed", "error_code": type(exc).__name__}
    Path(args.output).write_text(
        json.dumps(safe, default=str, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def command(id_, label, *, action="start", options=()):
    path = BASE / (label + ".json")
    args = [
        sys.executable,
        str(Path(__file__).resolve()),
        "child",
        action,
        id_,
        "--output",
        str(path),
        *options,
    ]
    return args, path


def invoke(id_, label, **kw):
    args, path = command(id_, label, **kw)
    result = subprocess.run(args, env=environment(), cwd=ROOT, capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError("Restart child failed; no automatic execution retry")
    return json.loads(path.read_text(encoding="utf-8"))


def parent():
    inspect()
    os.environ.update(environment())
    settings = Settings(llm_mode="fake")
    BASE.mkdir(exist_ok=False, parents=True)
    ids = {k: str(uuid4()) for k in ["completed", "paused", "review", "cancelled", "issued"]}
    before = {}
    before["completed"] = invoke(ids["completed"], "completed-before")
    before["paused"] = invoke(ids["paused"], "paused-before", options=["--pause"])
    before["review"] = invoke(ids["review"], "review-before", options=["--review"])
    before["cancelled"] = invoke(ids["cancelled"], "cancel-before", options=["--pause"])
    assert before["completed"]["status"] == "succeeded", "Validate observer before restarting"
    assert before["paused"]["status"] == "paused"
    assert before["review"]["status"] == "awaiting_review"
    backend = Backend(
        settings.runtime_database_url.get_secret_value(), ids["cancelled"], "local-user"
    )
    try:
        backend.cancel()
    finally:
        backend.close()
    marker = BASE / "issued.marker"
    args, issued_path = command(
        ids["issued"], "issued-after-loss", options=["--marker", str(marker)]
    )
    process = subprocess.Popen(
        args,
        env=environment(),
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for _ in range(300):
        if marker.exists():
            break
        if process.poll() is not None:
            raise RuntimeError("Issued fixture stopped before the marker")
        time.sleep(0.05)
    if not marker.exists():
        raise RuntimeError("Issued fixture marker deadline")
    snapshots = {k: snapshot(settings, id_) for k, id_ in ids.items()}
    assert any(c["status"] == "issued" for c in snapshots["issued"]["calls"])
    record = {
        "ids": ids,
        "before": before,
        "snapshots_before": snapshots,
        "actual_instance_restart": False,
        "paid_model_calls": 0,
    }
    (BASE / "before.json").write_text(json.dumps(record, default=str, indent=2), encoding="utf-8")
    # Name, label and pinned image are revalidated by the only restart helper.
    old_argv = sys.argv
    try:
        sys.argv = ["p7_isolated_pg.py", "restart"]
        pg_main()
    finally:
        sys.argv = old_argv
    marker.with_suffix(".release").write_text("Restart completed; no reissue", encoding="utf-8")
    process.wait(timeout=30)
    after = {k: invoke(ids[k], k + "-after", action="resume") for k in ids}
    repeated = invoke(ids["completed"], "completed-repeat", action="resume")
    final = {k: snapshot(settings, id_) for k, id_ in ids.items()}
    assert (
        before["completed"]["status"]
        == after["completed"]["status"]
        == repeated["status"]
        == "succeeded"
    )
    assert snapshots["completed"] == final["completed"]
    assert (
        after["paused"]["status"] == "succeeded"
        and before["paused"]["usage"] == after["paused"]["usage"]
    )
    assert after["review"]["status"] == "awaiting_review" and after["review"]["usage"]["calls"] == 0
    assert after["cancelled"]["error_code"] == "CANCELLED" and final["cancelled"]["cancelled"]
    assert after["issued"]["error_code"] == "RECOVERY_UNCERTAIN"
    assert len(snapshots["issued"]["calls"]) == len(final["issued"]["calls"])
    assert sum(c["kind"] == "model" for c in final["issued"]["calls"]) == 1
    assert final["issued"]["ledger"]["state"]["accounts"]["root"]["usage"]["calls"] == 1
    record.update(
        actual_instance_restart=True,
        after=after,
        repeated=repeated,
        snapshots_after=final,
        issued_child=json.loads(issued_path.read_text()),
        all_assertions_passed=True,
        uncertain_auto_reissues=0,
        fixture_model_not_real_provider=True,
    )
    (BASE / "verification.json").write_text(
        json.dumps(record, default=str, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {"actual_pg_restart": True, "checks": 5, "uncertain_reissued": 0, "paid_model_calls": 0}
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    c = sub.add_parser("child")
    c.add_argument("action", choices=["start", "resume"])
    c.add_argument("run_id")
    c.add_argument("--output", required=True)
    c.add_argument("--pause", action="store_true")
    c.add_argument("--review", action="store_true")
    c.add_argument("--approve", action="store_true")
    c.add_argument("--marker")
    args = parser.parse_args()
    parent() if args.command == "run" else child(args)
