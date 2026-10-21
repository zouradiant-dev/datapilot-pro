"""Restricted PG metadata transactions and the existing budget algorithm's durable adapter."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.contracts import Artifact
from datapilot.orchestration.runtime import ArtifactStore


def execute(conn, statement, **params):
    return conn.execute(sa.text(statement), params)


def json_value(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class Backend:
    def __init__(self, url, run_id, owner, *, fault=None):
        parsed = make_url(url)
        if parsed.drivername != "postgresql+psycopg" or parsed.username != "datapilot_runtime":
            raise AgentFailure("ROLE_UNSAFE", "Use the isolated runtime identity")
        self.engine = sa.create_engine(
            url, hide_parameters=True, connect_args={"connect_timeout": 5}
        )
        self.run_id, self.owner, self.fault = run_id, owner, fault
        self.lease_connection = None

        with self.engine.connect() as conn:
            unsafe = conn.exec_driver_sql(
                "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls "
                "OR rolinherit FROM pg_roles WHERE rolname=current_user"
            ).scalar_one()
            members = conn.exec_driver_sql(
                "SELECT count(*) FROM pg_auth_members "
                "WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)"
            ).scalar_one()
            ddl = conn.exec_driver_sql(
                "SELECT has_schema_privilege(current_user,'checkpoints','CREATE') "
                "OR has_schema_privilege(current_user,'execution','CREATE')"
            ).scalar_one()
            if unsafe or members or ddl:
                self.engine.dispose()
                raise AgentFailure(
                    "ROLE_UNSAFE", "Runtime identity must have no DDL or inherited roles"
                )

    def hit(self, point):
        if self.fault:
            self.fault(point)

    def close(self):
        self.engine.dispose()

    def register(self, manifest, limits, ttl_seconds=86400):
        if not 60 <= ttl_seconds <= 7 * 86400:
            raise ValueError("Runtime retention must be between one minute and seven days")
        with self.engine.begin() as conn:
            execute(
                conn,
                """INSERT INTO execution.runs
                (run_id,owner,manifest,manifest_hash,expires_at)
                VALUES (:run,:owner,CAST(:manifest AS jsonb),:hash,:expiry)
                ON CONFLICT (run_id) DO NOTHING""",
                run=self.run_id,
                owner=self.owner,
                manifest=json_value(manifest),
                hash=digest(manifest),
                expiry=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            )
            self.authorize(conn, manifest)
            state = BudgetLedger(limits).dump_state()
            execute(
                conn,
                """INSERT INTO execution.ledger(run_id,payload)
                VALUES (:run,CAST(:payload AS jsonb)) ON CONFLICT DO NOTHING""",
                run=self.run_id,
                payload=json_value({"state": state, "sha256": digest(state)}),
            )

    def authorize(self, conn, manifest=None):
        row = (
            execute(
                conn, "SELECT * FROM execution.runs WHERE run_id=:run FOR UPDATE", run=self.run_id
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["owner"] != self.owner:
            raise AgentFailure("RECOVERY_FORBIDDEN", "Run was not delegated to this owner")
        if row["expires_at"] <= datetime.now(UTC):
            raise AgentFailure("RECOVERY_EXPIRED", "Run retention has expired")
        if digest(row["manifest"]) != row["manifest_hash"] or (
            manifest is not None and digest(manifest) != row["manifest_hash"]
        ):
            raise AgentFailure("RECOVERY_IDENTITY", "Task, scope, versions or policy changed")
        return row

    @contextmanager
    def transaction(self):
        with self.engine.begin() as conn:
            self.authorize(conn)
            yield conn

    @contextmanager
    def lease(self):
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            locked = execute(
                conn, "SELECT pg_try_advisory_lock(hashtextextended(:run, 9182))", run=self.run_id
            ).scalar_one()
            if not locked:
                raise AgentFailure("RECOVERY_BUSY", "Another process owns this run")
            try:
                self.lease_connection = conn
                yield
            finally:
                self.lease_connection = None
                execute(
                    conn, "SELECT pg_advisory_unlock(hashtextextended(:run, 9182))", run=self.run_id
                )

    def assert_lease(self):
        if self.lease_connection is None:
            raise AgentFailure("RECOVERY_BUSY", "External execution requires the run lease")
        self.lease_connection.exec_driver_sql("SELECT 1")

    def cancelled(self):
        with self.transaction() as conn:
            return self.authorize(conn)["cancelled"]

    def cancel(self):
        with self.transaction() as conn:
            execute(
                conn, "UPDATE execution.runs SET cancelled=true WHERE run_id=:run", run=self.run_id
            )

    def event(self, payload):
        # Only host-defined redacted summaries; never prompts, SQL, credentials or rows.
        with self.transaction() as conn:
            count = execute(
                conn, "SELECT count(*) FROM execution.events WHERE run_id=:run", run=self.run_id
            ).scalar_one()
            if count >= 2048:
                raise AgentFailure("EVIDENCE_LIMIT", "Durable audit event quota reached")
            execute(
                conn,
                "INSERT INTO execution.events(run_id,payload) VALUES (:run,CAST(:p AS jsonb))",
                run=self.run_id,
                p=json_value(payload),
            )


class DurableLedger(BudgetLedger):
    """Apply the ORIGINAL BudgetLedger operations under a PostgreSQL row transaction."""

    def __init__(self, backend, limits):
        super().__init__(limits)
        self.backend = backend
        self.expected_limits = limits
        self.refresh()

    def mutate(self, operation, conn=None):
        if conn is None:
            with self.backend.transaction() as connection:
                result, error = self._apply(operation, connection)
        else:
            result, error = self._apply(operation, conn)
        if error:
            raise error
        return result

    def _apply(self, operation, conn):
        with self._lock:
            payload = execute(
                conn,
                "SELECT payload FROM execution.ledger WHERE run_id=:run FOR UPDATE",
                run=self.backend.run_id,
            ).scalar_one()
            if digest(payload["state"]) != payload["sha256"]:
                raise AgentFailure("BUDGET_INVALID", "Durable ledger hash differs")
            self.load_state(payload["state"])
            if self.accounts["root"].limits != self.expected_limits:
                raise AgentFailure(
                    "BUDGET_INVALID", "Durable root policy differs from trusted limits"
                )
            self.receipts = dict(payload["state"].get("receipts", {}))
            result, error = None, None
            try:
                result = operation()
            except AgentFailure as exc:
                error = exc
            state = self.dump_state()
            state["receipts"] = self.receipts
            execute(
                conn,
                "UPDATE execution.ledger SET payload=CAST(:payload AS jsonb) WHERE run_id=:run",
                run=self.backend.run_id,
                payload=json_value({"state": state, "sha256": digest(state)}),
            )
            return result, error

    def refresh(self):
        self.mutate(lambda: None)

    def fork(self, name, limits, parent="root"):
        def apply():
            if name in self.accounts:
                a = self.accounts[name]
                if a.limits != limits or a.parent != parent:
                    raise AgentFailure("BUDGET_INVALID", "Existing child budget differs")
                return name
            return super(DurableLedger, self).fork(name, limits, parent)

        return self.mutate(apply)

    def reserve_batch(self, account, requests):
        return self.mutate(lambda: super(DurableLedger, self).reserve_batch(account, requests))

    def check_ticket(self, ticket, account, amount):
        return self.mutate(lambda: super(DurableLedger, self).check_ticket(ticket, account, amount))

    def release_unissued(self, ticket):
        with self.backend.transaction() as conn:
            if execute(
                conn,
                "SELECT 1 FROM execution.calls WHERE run_id=:run AND ticket=:ticket",
                run=self.backend.run_id,
                ticket=ticket,
            ).first():
                raise AgentFailure(
                    "BUDGET_INVALID", "An issued call reservation cannot be released"
                )
            result, error = self._apply(
                lambda: self.record_settlement(ticket, None, released=True), conn
            )
        if error:
            raise error
        return result

    def settle(self, ticket, actual):
        return self.mutate(lambda: self.record_settlement(ticket, actual))

    def record_settlement(self, ticket, actual, *, released=False):
        if type(actual) is not int or actual < 0:
            actual = None
        receipt = ["released" if released else "settled", actual]
        if ticket in self.receipts:
            if self.receipts[ticket][:2] != receipt:
                raise AgentFailure("BUDGET_INVALID", "Conflicting durable settlement")
            return
        if ticket not in self.pending:
            raise AgentFailure("BUDGET_INVALID", "Unknown durable reservation")
        amount = self.pending[ticket][1]
        try:
            if released:
                super().release_unissued(ticket)
            else:
                super().settle(ticket, actual)
        finally:
            if ticket not in self.pending:
                self.receipts[ticket] = [*receipt, amount]

    def snapshot(self, account="root"):
        return self.mutate(lambda: super(DurableLedger, self).snapshot(account))


class DurableArtifacts(ArtifactStore):
    def __init__(self, backend):
        super().__init__(backend.run_id)
        self.backend = backend

    def put(self, artifact):
        checked = Artifact.model_validate_json(artifact.model_dump_json())
        if checked.run_id != self.run_id:
            raise AgentFailure("EVIDENCE_INVALID", "Artifact belongs to another run")
        sha, size = digest(checked), len(checked.model_dump_json().encode())
        with self.backend.transaction() as conn:
            existing = execute(
                conn,
                "SELECT payload FROM execution.artifacts WHERE run_id=:run AND artifact_id=:id",
                run=self.run_id,
                id=sha,
            ).scalar_one_or_none()
            if existing is not None and digest(existing) != sha:
                raise AgentFailure("EVIDENCE_INVALID", "Stored artifact hash differs")
            if existing is None:
                count, total = execute(
                    conn,
                    "SELECT count(*),coalesce(sum(bytes),0) "
                    "FROM execution.artifacts WHERE run_id=:run",
                    run=self.run_id,
                ).one()
                if count >= 96 or total + size > 16 * 1024**2:
                    raise AgentFailure("EVIDENCE_LIMIT", "Durable artifact quota reached")
                execute(
                    conn,
                    """INSERT INTO execution.artifacts
                    (run_id,artifact_id,task_id,plan_version,kind,payload,bytes)
                    VALUES (:run,:id,:task,:version,:kind,CAST(:payload AS jsonb),:size)""",
                    run=self.run_id,
                    id=sha,
                    task=checked.task_id,
                    version=checked.plan_version,
                    kind=checked.kind,
                    payload=checked.model_dump_json(),
                    size=size,
                )
        return super().put(checked)

    def get(self, ref):
        with self.backend.transaction() as conn:
            row = (
                execute(
                    conn,
                    "SELECT * FROM execution.artifacts WHERE run_id=:run AND artifact_id=:id",
                    run=self.run_id,
                    id=ref.artifact_id,
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise AgentFailure("EVIDENCE_INVALID", "Durable artifact is missing")
        item = Artifact.model_validate_json(json_value(row["payload"]))
        if (
            (digest(item), item.task_id, item.plan_version, item.kind)
            != (ref.sha256, row["task_id"], row["plan_version"], ref.kind)
            or ref.artifact_id != ref.sha256
            or item.run_id != self.run_id
        ):
            raise AgentFailure("EVIDENCE_INVALID", "Durable artifact identity/hash differs")
        return item

    def export(self):
        from datapilot.orchestration.contracts import EvidenceRef

        with self.backend.transaction() as conn:
            rows = (
                execute(
                    conn,
                    "SELECT artifact_id,kind FROM execution.artifacts WHERE run_id=:run",
                    run=self.run_id,
                )
                .mappings()
                .all()
            )
        return {
            row["artifact_id"]: self.get(
                EvidenceRef(
                    artifact_id=row["artifact_id"], sha256=row["artifact_id"], kind=row["kind"]
                )
            )
            for row in rows
        }
