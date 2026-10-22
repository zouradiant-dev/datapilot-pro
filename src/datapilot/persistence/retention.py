"""Explicit whole-thread purge under a separate maintenance role. Default is dry-run."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy.engine import make_url

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.coordinator import Coordinator
from datapilot.persistence.backend import execute, json_value
from datapilot.persistence.inspection import NoModel
from datapilot.persistence.session import serializer

EXECUTION = ("calls", "events", "artifacts", "ledger", "web_runs", "runs")
CHECKPOINTS = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")


def blocked(reason):
    raise AgentFailure("RETENTION_BLOCKED", reason)


class Retainer:
    def __init__(self, url):
        if make_url(url).username != "datapilot_maintenance":
            blocked("Only the isolated maintenance identity can plan or execute retention")
        self.engine = sa.create_engine(url, hide_parameters=True, isolation_level="SERIALIZABLE")
        with self.engine.connect() as conn:
            unsafe = conn.exec_driver_sql(
                "SELECT rolsuper OR rolcreatedb OR rolcreaterole "
                "OR rolinherit OR rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).scalar_one()
            if (
                unsafe
                or conn.exec_driver_sql(
                    "SELECT count(*) FROM pg_auth_members WHERE "
                    "member=(SELECT oid FROM pg_roles WHERE rolname=current_user)"
                ).scalar_one()
            ):
                blocked("Maintenance must have no inherited or privileged role")

    def close(self):
        self.engine.dispose()

    def _check(self, conn, run_id):
        conn.exec_driver_sql("SET LOCAL search_path=checkpoints,pg_catalog")
        if str(UUID(run_id)) != run_id:
            blocked("Use a canonical run UUID")
        for seed in (9182, 6155, 6157):
            if not execute(
                conn,
                "SELECT pg_try_advisory_xact_lock(hashtextextended(:r,:seed))",
                r=run_id,
                seed=seed,
            ).scalar_one():
                blocked("A runtime or dispatch lease is active")
        row = (
            execute(conn, "SELECT * FROM execution.runs WHERE run_id=:r", r=run_id)
            .mappings()
            .one_or_none()
        )
        if row is None or row["expires_at"] > datetime.now(UTC):
            blocked("Run is missing or has not expired")
        if digest(row["manifest"]) != row["manifest_hash"]:
            blocked("Run manifest is inconsistent")
        web = (
            execute(conn, "SELECT * FROM execution.web_runs WHERE run_id=:r", r=run_id)
            .mappings()
            .one_or_none()
        )
        if web and (
            web["expires_at"] > datetime.now(UTC) or web["command_seq"] != web["processed_seq"]
        ):
            blocked("Web retention is unexpired or a host command is pending")
        if execute(
            conn, "SELECT 1 FROM execution.retention_holds WHERE run_id=:r AND active", r=run_id
        ).first():
            blocked("An explicit retention hold exists")
        if execute(
            conn,
            "SELECT 1 FROM execution.calls WHERE run_id=:r AND status IN ('issued','uncertain')",
            r=run_id,
        ).first():
            blocked("An external outcome needs reconciliation")
        payload = execute(
            conn, "SELECT payload FROM execution.ledger WHERE run_id=:r", r=run_id
        ).scalar_one()
        if digest(payload["state"]) != payload["sha256"] or payload["state"].get("pending"):
            blocked("Budget is corrupt or reservations are outstanding")
        version = conn.exec_driver_sql(
            "SELECT max(v) FROM checkpoints.checkpoint_migrations"
        ).scalar_one()
        if version != len(PostgresSaver.MIGRATIONS) - 1 or version != 9:
            blocked("Official Saver schema differs from the audited version")
        saver = PostgresSaver(conn.connection.driver_connection, serde=serializer())
        engine = Coordinator(
            Settings(llm_mode="fake", _env_file=None), NoModel(), checkpointer=saver
        )
        snapshot = engine.graph.get_state({"configurable": {"thread_id": run_id}})
        state = snapshot.values
        if not state or state.get("run_id") != run_id or snapshot.next or snapshot.interrupts:
            blocked("Missing, active, paused or awaiting-review checkpoint")
        if state.get("status") not in {"succeeded", "unavailable", "failed", "cancelled"}:
            blocked("Only a verified terminal graph state can be purged")
        # Never delete an artifact referenced by another run, even if such a reference
        # would already fail the normal same-run ArtifactStore contract.
        if execute(
            conn,
            "SELECT 1 FROM execution.artifacts other,execution.artifacts target "
            "WHERE target.run_id=:r AND other.run_id<>:r AND "
            "EXISTS (SELECT 1 FROM jsonb_array_elements("
            "coalesce(other.payload->'parents','[]'::jsonb)) p "
            "WHERE p->>'artifact_id'=target.artifact_id) LIMIT 1",
            r=run_id,
        ).first():
            blocked("Another run still references an artifact")
        artifacts = execute(
            conn,
            "SELECT artifact_id,payload FROM execution.artifacts "
            "WHERE run_id=:r ORDER BY artifact_id",
            r=run_id,
        ).all()
        if any(digest(p) != id_ for id_, p in artifacts):
            blocked("Artifact integrity is inconsistent")
        counts = {}
        for table in EXECUTION:
            counts["execution." + table] = execute(
                conn, f"SELECT count(*) FROM execution.{table} WHERE run_id=:r", r=run_id
            ).scalar_one()
        for table in CHECKPOINTS:
            counts["checkpoints." + table] = execute(
                conn, f"SELECT count(*) FROM checkpoints.{table} WHERE thread_id=:r", r=run_id
            ).scalar_one()
        pin = {
            "run_id": run_id,
            "manifest_sha256": row["manifest_hash"],
            "counts": counts,
            "checkpoint_id": snapshot.config["configurable"]["checkpoint_id"],
            "artifact_ids": [a[0] for a in artifacts],
            "ledger_sha256": payload["sha256"],
            "expires_at": row["expires_at"].isoformat(),
            "saver_version": version,
        }
        return {"run_id": run_id, "eligible": True, "counts": counts, "plan_hash": digest(pin)}

    def plan(self, run_id):
        with self.engine.begin() as conn:
            return self._check(conn, run_id)

    def purge(self, run_id, *, reviewed=False, confirm_hash=None, fault=None):
        if reviewed is not True or not confirm_hash:
            blocked("Explicit reviewed confirmation of a current dry-run plan is required")
        with self.engine.begin() as conn:
            plan = self._check(conn, run_id)
            if plan["plan_hash"] != confirm_hash:
                blocked("Plan changed; dry-run and review again")
            # Second check under the same locks/serializable transaction, immediately before writes.
            if self._check(conn, run_id) != plan:
                blocked("State changed during retention verification")
            for table in CHECKPOINTS:
                execute(conn, f"DELETE FROM checkpoints.{table} WHERE thread_id=:r", r=run_id)
            if fault:
                fault("after_checkpoints")
            for table in EXECUTION:
                execute(conn, f"DELETE FROM execution.{table} WHERE run_id=:r", r=run_id)
            execute(
                conn,
                "UPDATE execution.web_requests SET retired=true,"
                "response='{}'::jsonb WHERE object_id=:r",
                r=run_id,
            )
            execute(
                conn,
                "INSERT INTO execution.retention_audit "
                "(audit_id,run_id_hash,plan_hash,counts) "
                "VALUES (:a,:r,:p,CAST(:c AS jsonb))",
                a=str(uuid4()),
                r=digest({"run_id": run_id}),
                p=confirm_hash,
                c=json_value(plan["counts"]),
            )
        return {**plan, "status": "purged"}

    def hold(self, run_id, *, active, reason):
        if not 1 <= len(reason) <= 128:
            blocked("Use a bounded non-sensitive hold reason")
        with self.engine.begin() as conn:
            if not execute(
                conn, "SELECT pg_try_advisory_xact_lock(hashtextextended(:r,6157))", r=run_id
            ).scalar_one():
                blocked("A retention transaction is active")
            execute(
                conn,
                "INSERT INTO execution.retention_holds(run_id,active,reason) "
                "VALUES (:r,:a,:reason) ON CONFLICT(run_id) DO UPDATE "
                "SET active=EXCLUDED.active,reason=EXCLUDED.reason",
                r=run_id,
                a=active,
                reason=reason,
            )
