"""Bounded outbox dispatch; ALL Agent execution remains in original P5B run_durable."""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from contextlib import suppress

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.db.management import management_url
from datapilot.persistence.backend import Backend, execute
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import ReportScope
from datapilot.web.config import load_policy
from datapilot.web.service import ProductService
from datapilot.web.store import WebStore

log = logging.getLogger(__name__)


def safe_error(exc):
    code = exc.error.code if isinstance(exc, AgentFailure) else "WEB_EXECUTION_ERROR"
    return {
        "code": code,
        "message": "执行未完成；检查任务状态后再决定是否恢复",
        "retryable": code in {"MODEL_TIMEOUT", "MODEL_RATE_LIMIT", "RECOVERY_BUSY"},
        "manual_action_required": code
        in {
            "RECOVERY_UNCERTAIN",
            "BUDGET_INVALID",
            "RECOVERY_CORRUPT",
            "RECOVERY_IDENTITY",
            "RECOVERY_POLICY_UNBOUND",
            "RECOVERY_VERSION",
        },
    }


async def execute_one(settings, store, run_id, *, transport=None, fault=None, interrupt_after=None):
    # Independent dispatch lease survives API restart. Original P5B lease still guards graph.
    with store.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock:
        acquired = execute(
            lock, "SELECT pg_try_advisory_lock(hashtextextended(:r,6155))", r=run_id
        ).scalar_one()
        if not acquired:
            return False
        slot = next(
            (
                s
                for s in range(store.policy.max_workers)
                if execute(
                    lock,
                    "SELECT pg_try_advisory_lock(hashtextextended(:host,6156))",
                    host=store.policy.owner + ":" + str(s),
                ).scalar_one()
            ),
            None,
        )
        if slot is None:
            execute(lock, "SELECT pg_advisory_unlock(hashtextextended(:r,6155))", r=run_id)
            return False
        try:
            row = store.run(run_id)
            if row["command_seq"] == row["processed_seq"]:
                return False
            seq = row["command_seq"]
            try:
                # The caller and persisted Settings are comparison inputs, never authority.
                current = store.settings_provider() if store.settings_provider else Settings()
                if store.host_settings_hash(settings) != store.host_settings_hash(current):
                    raise AgentFailure("RECOVERY_VERSION", "Caller configuration is stale")
                settings = current
                store.check_host_settings(settings)
                service = ProductService(current, store)
                if row["action"] != "cancel" and service.admission.enabled:
                    service.admission.check_run(run_id)
                p = row["payload"]
                backend = Backend(
                    settings.runtime_database_url.get_secret_value(), run_id, store.policy.owner
                )
                try:
                    with backend.engine.connect() as conn:
                        exists = execute(
                            conn, "SELECT 1 FROM execution.runs WHERE run_id=:r", r=run_id
                        ).first()
                finally:
                    backend.close()
                if not row["cancel_requested"]:
                    await service.authorize_run(run_id)
                options = dict(
                    owner=store.policy.owner,
                    require_review=p["require_review"],
                    ttl_seconds=store.policy.ttl_seconds,
                    report_scope=ReportScope.model_validate_json(json.dumps(p["report_scope"])),
                    rag_scope=RagScope.model_validate_json(json.dumps(p["rag_scope"]))
                    if p["rag_scope"]
                    else None,
                    transport=transport,
                    fault=fault,
                )
                if not exists:
                    # Original Saver/interrupt initializes with zero model/metric work.
                    # Re-read the durable outbox after initialization, before any execution.
                    fresh = store.run(run_id)
                    if fresh["cancel_requested"]:
                        store.mark(run_id, fresh["command_seq"], "cancelled")
                        return True
                    if fresh["processed_seq"] >= seq or fresh["command_seq"] != seq:
                        return False
                    store.check_host_settings(settings)
                    if "host_policy_sha256" not in p:
                        raise AgentFailure(
                            "RECOVERY_POLICY_UNBOUND",
                            "Legacy pending task needs host reauthorization",
                        )
                    result = await run_durable(
                        settings,
                        run_id,
                        p["question"],
                        interrupt_before=["planner"],
                        **options,
                    )
                    if result["status"] == "awaiting_review":
                        store.mark(run_id, seq, result["status"])
                        return True
                fresh = store.run(run_id)
                if fresh["cancel_requested"]:
                    from datapilot.persistence.inspection import control_state

                    _, terminal = await control_state(
                        settings, run_id, store.policy.owner, p["question"]
                    )
                    if not terminal:
                        backend = Backend(
                            settings.runtime_database_url.get_secret_value(),
                            run_id,
                            store.policy.owner,
                        )
                        try:
                            backend.cancel()
                        finally:
                            backend.close()
                    store.mark(run_id, fresh["command_seq"], "cancelled")
                    return True
                if fresh["processed_seq"] >= seq or fresh["command_seq"] != seq:
                    return False
                store.check_host_settings(settings)
                result = await run_durable(
                    settings,
                    run_id,
                    resume=True,
                    approve=True if row["action"] == "approve" else None,
                    interrupt_after=interrupt_after,
                    **options,
                )
                store.mark(run_id, seq, result["status"])
            except Exception as exc:
                store.mark(run_id, seq, "blocked", safe_error(exc))
            return True
        finally:
            execute(
                lock,
                "SELECT pg_advisory_unlock(hashtextextended(:host,6156))",
                host=store.policy.owner + ":" + str(slot),
            )
            execute(lock, "SELECT pg_advisory_unlock(hashtextextended(:r,6155))", r=run_id)


class Dispatcher:
    """Supervise only local process slots; DAG/budget/recovery are LangGraph's responsibility."""

    def __init__(self, store, policy_file):
        self.store, self.policy_file = store, str(policy_file)
        self.children = {}
        self.sequences = {}
        self.stopping = False
        self.poll_failures = 0
        self.last_error = None

    async def run(self):
        while not self.stopping:
            try:
                self.poll()
                self.poll_failures = 0
                self.last_error = None
            except Exception:
                self.poll_failures += 1
                self.last_error = "WEB_DISPATCH_UNAVAILABLE"
                log.error("Web dispatcher poll failed (%s/3); details redacted", self.poll_failures)
                if self.poll_failures >= 3:
                    # A circuit breaker, not an unbounded crash/restart loop. Host restart
                    # is required after repeated infrastructure failures.
                    while not self.stopping:
                        await asyncio.sleep(0.5)
                    return
            await asyncio.sleep(0.5 * max(1, self.poll_failures))

    def poll(self):
        for id_, child in list(self.children.items()):
            code = child.poll()
            if code is not None:
                seq = self.sequences[id_]
                if code == 75:
                    self.store.dispatch_busy(id_, seq)
                else:
                    # CAS leaves acknowledged commands alone; every unacknowledged exit,
                    # even exit 0, is uncertain and cannot be automatically relaunched.
                    self.store.dispatch_failed(id_, seq)
                self.children.pop(id_)
                self.sequences.pop(id_)
        for id_ in self.store.pending():
            if len(self.children) >= self.store.policy.max_workers:
                break
            if id_ in self.children:
                continue
            # Advisory probe avoids launch storms while an orphan worker is still active.
            with self.store.transaction() as conn:
                free = execute(
                    conn, "SELECT pg_try_advisory_xact_lock(hashtextextended(:r,6155))", r=id_
                ).scalar_one()
                capacity = free and any(
                    execute(
                        conn,
                        "SELECT pg_try_advisory_xact_lock(hashtextextended(:host,6156))",
                        host=self.store.policy.owner + ":" + str(slot),
                    ).scalar_one()
                    for slot in range(self.store.policy.max_workers)
                )
            if not capacity:
                continue
            seq = self.store.dispatch_start(id_)
            if seq is None:
                continue
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            try:
                self.children[id_] = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "datapilot.web.worker",
                        id_,
                        "--host-file",
                        self.policy_file,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags,
                    env={**os.environ, "PYTHONUTF8": "1"},
                )
                self.sequences[id_] = seq
            except Exception:
                self.store.dispatch_failed(id_, seq)
                log.error("Web worker launch failed; task quarantined, details redacted")

    async def close(self):
        self.stopping = True
        # Ordinary shutdown does not cancel the business run; children may safely finish.
        for child in self.children.values():
            if child.poll() is None:
                with suppress(subprocess.TimeoutExpired):
                    await asyncio.to_thread(child.wait, timeout=1)
        # Do not kill orphan workers on API shutdown. PG leases bound subsequent dispatch.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--host-file", required=True)
    args = parser.parse_args()
    policy = load_policy(args.host_file)
    store = WebStore(management_url("web"), policy)
    try:
        completed = run_async(execute_one(Settings(), store, args.run_id))
        if not completed:
            raise SystemExit(75)
    finally:
        store.close()


if __name__ == "__main__":
    main()
