"""Host-only metadata. Command outbox is not an Agent scheduler or a checkpoint."""

import hashlib
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.persistence.backend import execute, json_value


def deny(code="WEB_FORBIDDEN", message="Host authorization or source version is invalid"):
    raise AgentFailure(code, message)


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


class WebStore:
    def __init__(self, url, policy):
        if make_url(url).username != "datapilot_web":
            deny("ROLE_UNSAFE", "Use the isolated Web metadata identity")
        self.policy = policy
        self.engine = sa.create_engine(
            url, hide_parameters=True, connect_args={"connect_timeout": 5}
        )
        with self.engine.connect() as conn:
            flags = conn.exec_driver_sql(
                "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication "
                "OR rolbypassrls OR rolinherit FROM pg_roles WHERE rolname=current_user"
            ).scalar_one()
            members = conn.exec_driver_sql(
                "SELECT count(*) FROM pg_auth_members WHERE "
                "member=(SELECT oid FROM pg_roles WHERE rolname=current_user)"
            ).scalar_one()
            ddl = conn.exec_driver_sql(
                "SELECT has_schema_privilege(current_user,'execution','CREATE') OR "
                "has_table_privilege(current_user,'execution.runs','DELETE')"
            ).scalar_one()
            if flags or members or ddl:
                self.close()
                deny("ROLE_UNSAFE", "Web role must have no inherited, DDL or runtime-delete power")

    def close(self):
        self.engine.dispose()

    @contextmanager
    def transaction(self):
        with self.engine.begin() as conn:
            yield conn

    def session(self):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.transaction() as conn:
            execute(
                conn,
                "INSERT INTO execution.web_sessions "
                "(session_hash,owner,csrf_hash,expires_at) VALUES (:s,:o,:c,:e)",
                s=token_hash(token),
                o=self.policy.owner,
                c=token_hash(csrf),
                e=datetime.now(UTC) + timedelta(hours=8),
            )
        return token, csrf

    def authenticate(self, token, csrf=None):
        if not token or len(token) > 128:
            deny()
        with self.transaction() as conn:
            row = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_sessions WHERE session_hash=:s",
                    s=token_hash(token),
                )
                .mappings()
                .one_or_none()
            )
        if not row or row["owner"] != self.policy.owner or row["expires_at"] <= datetime.now(UTC):
            deny()
        if csrf is not None and not secrets.compare_digest(row["csrf_hash"], token_hash(csrf)):
            deny("WEB_CSRF", "A current host session and CSRF token are required")

    def put_upload(self, upload_id, payload):
        with self.transaction() as conn:
            execute(
                conn,
                "INSERT INTO execution.web_uploads "
                "(upload_id,owner,payload,payload_hash,expires_at) "
                "VALUES (:id,:o,CAST(:p AS jsonb),:h,:e) "
                "ON CONFLICT(upload_id) DO UPDATE SET payload=EXCLUDED.payload,"
                "payload_hash=EXCLUDED.payload_hash WHERE web_uploads.owner=EXCLUDED.owner",
                id=upload_id,
                o=self.policy.owner,
                p=json_value(payload),
                h=digest(payload),
                e=datetime.now(UTC) + timedelta(seconds=self.policy.ttl_seconds),
            )

    def upload(self, upload_id):
        with self.transaction() as conn:
            row = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_uploads WHERE upload_id=:id "
                    "AND owner=:o AND expires_at>now()",
                    id=upload_id,
                    o=self.policy.owner,
                )
                .mappings()
                .one_or_none()
            )
        if not row or digest(row["payload"]) != row["payload_hash"]:
            deny()
        return row["payload"]

    def grant(self, schema):
        payload = {"schema": schema.model_dump(mode="json"), "semantics": [], "metrics": []}
        with self.transaction() as conn:
            execute(
                conn,
                "INSERT INTO execution.web_datasets "
                "(owner,dataset_id,version,source_sha256,payload,payload_hash) "
                "VALUES (:o,:id,:v,:s,CAST(:p AS jsonb),:h) ON CONFLICT DO NOTHING",
                o=self.policy.owner,
                id=schema.dataset_id,
                v=schema.version,
                s=schema.source_sha256,
                p=json_value(payload),
                h=digest(payload),
            )

    def dataset(self, id_, version):
        with self.transaction() as conn:
            row = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_datasets WHERE owner=:o "
                    "AND dataset_id=:id AND version=:v AND enabled",
                    o=self.policy.owner,
                    id=id_,
                    v=version,
                )
                .mappings()
                .one_or_none()
            )
        if not row or digest(row["payload"]) != row["payload_hash"]:
            deny()
        return row["payload"]

    def datasets(self):
        with self.transaction() as conn:
            return [
                self.dataset(r[0], r[1])
                for r in execute(
                    conn,
                    "SELECT dataset_id,version FROM execution.web_datasets "
                    "WHERE owner=:o AND enabled ORDER BY dataset_id,version LIMIT 101",
                    o=self.policy.owner,
                ).all()
            ]

    def definition(self, record, kind):
        with self.transaction() as conn:
            row = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_datasets WHERE owner=:o "
                    "AND dataset_id=:id AND version=:v AND enabled FOR UPDATE",
                    o=self.policy.owner,
                    id=record.dataset_id,
                    v=record.dataset_version,
                )
                .mappings()
                .one()
            )
            p = row["payload"]
            if digest(p) != row["payload_hash"]:
                deny()
            value = record.model_dump(mode="json")
            if value not in p[kind]:
                p[kind].append(value)
            execute(
                conn,
                "UPDATE execution.web_datasets SET payload=CAST(:p AS jsonb),"
                "payload_hash=:h WHERE owner=:o AND dataset_id=:id AND version=:v",
                p=json_value(p),
                h=digest(p),
                o=self.policy.owner,
                id=record.dataset_id,
                v=record.dataset_version,
            )

    def corpus(self, target, pin):
        payload = pin.model_dump(mode="json")
        with self.transaction() as conn:
            execute(
                conn,
                "INSERT INTO execution.web_corpora "
                "(owner,corpus_id,index_version,dataset_id,dataset_version,payload,payload_hash) "
                "VALUES (:o,:id,:v,:d,:dv,CAST(:p AS jsonb),:h) ON CONFLICT DO NOTHING",
                o=self.policy.owner,
                id=target.corpus_id,
                v=pin.index_version,
                d=target.dataset_id,
                dv=target.dataset_version,
                p=json_value(payload),
                h=digest(payload),
            )

    def corpora(self):
        with self.transaction() as conn:
            rows = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_corpora WHERE owner=:o "
                    "ORDER BY corpus_id,index_version LIMIT 100",
                    o=self.policy.owner,
                )
                .mappings()
                .all()
            )
        for row in rows:
            if digest(row["payload"]) != row["payload_hash"]:
                deny()
            self.dataset(row["dataset_id"], row["dataset_version"])
        return rows

    def run(self, run_id, conn=None):
        if conn is None:
            with self.transaction() as c:
                return self.run(run_id, c)
        row = (
            execute(
                conn,
                "SELECT * FROM execution.web_runs WHERE run_id=:id "
                "AND owner=:o AND expires_at>now() FOR UPDATE",
                id=run_id,
                o=self.policy.owner,
            )
            .mappings()
            .one_or_none()
        )
        if not row or digest(row["payload"]) != row["payload_hash"]:
            deny()
        return dict(row)

    def replay(self, key, operation, body, run_id=None):
        hashed = digest(
            {"owner": self.policy.owner, "operation": operation, "run_id": run_id, "body": body}
        )
        with self.transaction() as conn:
            old = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_requests WHERE owner=:o AND idempotency_key=:k",
                    o=self.policy.owner,
                    k=key,
                )
                .mappings()
                .one_or_none()
            )
            if not old:
                return None
            if old["retired"]:
                deny("WEB_EXPIRED", "The original command has expired")
            if (old["operation"], old["body_hash"]) != (operation, hashed):
                deny("WEB_IDEMPOTENCY_CONFLICT", "Key is bound to another request")
            self.run(old["object_id"], conn)
            return old["response"]

    def command(self, key, operation, body, *, run_id=None, payload=None, no_op=False):
        """Serialize identical requests and changes to one run in a single PG transaction."""
        if not 8 <= len(key) <= 128 or not all(c.isalnum() or c in "_-" for c in key):
            deny("WEB_IDEMPOTENCY", "Use an 8-128 character idempotency key")
        hashed = digest(
            {"owner": self.policy.owner, "operation": operation, "run_id": run_id, "body": body}
        )
        with self.transaction() as conn:
            execute(
                conn, "SELECT pg_advisory_xact_lock(hashtextextended(:o,6153))", o=self.policy.owner
            )
            execute(
                conn,
                "SELECT pg_advisory_xact_lock(hashtextextended(:key,6154))",
                key=self.policy.owner + ":" + key,
            )
            old = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_requests WHERE owner=:o AND idempotency_key=:k",
                    o=self.policy.owner,
                    k=key,
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["retired"]:
                    deny("WEB_EXPIRED", "The original command has expired")
                if (old["operation"], old["body_hash"]) != (operation, hashed):
                    deny("WEB_IDEMPOTENCY_CONFLICT", "Key is already bound to another request")
                self.run(old["object_id"], conn)
                return old["response"]
            if operation == "create":
                count = execute(
                    conn,
                    "SELECT count(*) FROM execution.web_runs WHERE "
                    "owner=:o AND command_seq>processed_seq AND expires_at>now()",
                    o=self.policy.owner,
                ).scalar_one()
                if count >= self.policy.max_pending:
                    deny("WEB_QUEUE_FULL", "Local pending task limit reached")
                run_id = str(uuid4())
                execute(
                    conn,
                    "INSERT INTO execution.web_runs "
                    "(run_id,owner,payload,payload_hash,action,expires_at) "
                    "VALUES (:id,:o,CAST(:p AS jsonb),:h,'start',:e)",
                    id=run_id,
                    o=self.policy.owner,
                    p=json_value(payload),
                    h=digest(payload),
                    e=datetime.now(UTC) + timedelta(seconds=self.policy.ttl_seconds),
                )
            else:
                row = self.run(run_id, conn)
                if row["command_seq"] != row["processed_seq"]:
                    if operation != "cancel":
                        deny("WEB_BUSY", "An earlier command is still being processed")
                if no_op:
                    execute(
                        conn,
                        "UPDATE execution.web_runs SET command_seq=command_seq+1,"
                        "processed_seq=command_seq+1,updated_at=now() WHERE run_id=:id",
                        id=run_id,
                    )
                else:
                    execute(
                        conn,
                        "UPDATE execution.web_runs SET action=:a,"
                        "command_seq=command_seq+1,cancel_requested=:c,updated_at=now() "
                        "WHERE run_id=:id",
                        a=operation,
                        c=operation == "cancel",
                        id=run_id,
                    )
            response = {"schema_version": "api-v1", "run_id": run_id, "accepted": True}
            execute(
                conn,
                "INSERT INTO execution.web_requests "
                "(owner,idempotency_key,operation,body_hash,object_id,response) "
                "VALUES (:o,:k,:op,:h,:id,CAST(:r AS jsonb))",
                o=self.policy.owner,
                k=key,
                op=operation,
                h=hashed,
                id=run_id,
                r=json_value(response),
            )
            return response

    def pending(self):
        with self.transaction() as conn:
            return [
                r[0]
                for r in execute(
                    conn,
                    "SELECT run_id FROM execution.web_runs WHERE "
                    "owner=:o AND command_seq>processed_seq AND expires_at>now() "
                    "ORDER BY created_at LIMIT 100",
                    o=self.policy.owner,
                ).all()
            ]

    def mark(self, run_id, seq, status, error=None):
        with self.transaction() as conn:
            execute(
                conn,
                "UPDATE execution.web_runs SET processed_seq=:s,status_hint=:st,"
                "last_error=CAST(:e AS jsonb),updated_at=now() "
                "WHERE run_id=:id AND owner=:o AND command_seq=:s",
                s=seq,
                st=status,
                e=json_value(error),
                id=run_id,
                o=self.policy.owner,
            )
