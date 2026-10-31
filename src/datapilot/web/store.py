"""Host-only metadata. Command outbox is not an Agent scheduler or a checkpoint."""

import hashlib
import secrets
from contextlib import contextmanager, nullcontext
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


def dataset_payload(row):
    if not row or digest(row["payload"]) != row["payload_hash"]:
        deny()
    schema = row["payload"]["schema"]
    if (schema["dataset_id"], schema["version"], schema["source_sha256"]) != (
        row["dataset_id"],
        row["version"],
        row["source_sha256"],
    ):
        deny()
    return row["payload"]


class WebStore:
    def __init__(self, url, policy):
        if make_url(url).username != "datapilot_web":
            deny("ROLE_UNSAFE", "Use the isolated Web metadata identity")
        self.policy = policy
        # Process-local trusted host provider; never reconstructed from an outbox payload.
        self.settings_provider = None
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

    def host_settings_hash(self, settings):
        excluded = {
            "api_key",
            "reader_database_url",
            "upload_reader_database_url",
            "runtime_database_url",
            "rag_reader_database_url",
        }
        identities = {}
        for name in excluded - {"api_key"}:
            secret = getattr(settings, name)
            if secret:
                u = make_url(secret.get_secret_value())
                identities[name] = {
                    "host": u.host,
                    "port": u.port,
                    "database": u.database,
                    "role": u.username,
                }
        return digest(
            {
                "owner": self.policy.owner,
                "settings": settings.model_dump(exclude=excluded),
                "identities": identities,
                **(
                    {"rag_embedding_profile": self.policy.rag_embedding_profile}
                    if self.policy.rag_embedding_profile
                    else {}
                ),
            }
        )

    def publish_host_settings(self, settings):
        # Only the trusted API configuration lifecycle calls this; workers only compare.
        with self.transaction() as conn:
            execute(
                conn,
                "INSERT INTO execution.web_requests "
                "(owner,idempotency_key,operation,body_hash,object_id,response) "
                "VALUES (:o,'host_policy','host_policy',:h,'host_policy','{}'::jsonb) "
                "ON CONFLICT(owner,idempotency_key) DO UPDATE SET body_hash=EXCLUDED.body_hash",
                o=self.policy.owner,
                h=self.host_settings_hash(settings),
            )

    def check_host_settings(self, settings):
        with self.transaction() as conn:
            actual = execute(
                conn,
                "SELECT body_hash FROM execution.web_requests WHERE owner=:o "
                "AND idempotency_key='host_policy' AND operation='host_policy'",
                o=self.policy.owner,
            ).scalar_one_or_none()
        if actual != self.host_settings_hash(settings):
            deny("RECOVERY_VERSION", "Current host policy differs; reauthorization is required")

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
        return row["session_hash"]

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
        return dataset_payload(row)

    def datasets(self, *, offset=0, limit=100):
        if not 0 <= offset <= 1_000_000 or not 1 <= limit <= 100:
            deny("WEB_PAGE", "Use a bounded dataset page")
        with self.transaction() as conn:
            return [
                dataset_payload(r)
                for r in execute(
                    conn,
                    "SELECT * FROM execution.web_datasets "
                    "WHERE owner=:o AND enabled ORDER BY dataset_id,version LIMIT :n OFFSET :off",
                    o=self.policy.owner,
                    n=limit + 1,
                    off=offset,
                )
                .mappings()
                .all()
            ]

    def has_dataset(self, id_):
        with self.transaction() as conn:
            return (
                execute(
                    conn,
                    "SELECT 1 FROM execution.web_datasets WHERE owner=:o AND dataset_id=:id "
                    "AND enabled LIMIT 1",
                    o=self.policy.owner,
                    id=id_,
                ).first()
                is not None
            )

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

    def corpora(self, *, corpus_id=None):
        with self.transaction() as conn:
            rows = (
                execute(
                    conn,
                    "SELECT c.*,d.payload AS dataset_payload,"
                    "d.payload_hash AS dataset_payload_hash,"
                    "d.source_sha256 FROM execution.web_corpora c "
                    "JOIN execution.web_datasets d ON d.owner=c.owner "
                    "AND d.dataset_id=c.dataset_id AND d.version=c.dataset_version "
                    "WHERE c.owner=:o AND d.enabled "
                    "AND (CAST(:id AS text) IS NULL OR c.corpus_id=:id) "
                    "ORDER BY c.corpus_id,c.index_version LIMIT 100",
                    o=self.policy.owner,
                    id=corpus_id,
                )
                .mappings()
                .all()
            )
        for row in rows:
            if digest(row["payload"]) != row["payload_hash"]:
                deny()
            from datapilot.rag.contracts import CorpusPin

            pin = CorpusPin.model_validate(row["payload"])
            if (pin.corpus_id, pin.index_version) != (row["corpus_id"], row["index_version"]):
                deny()
            dataset_payload(
                {
                    "dataset_id": row["dataset_id"],
                    "version": row["dataset_version"],
                    "source_sha256": row["source_sha256"],
                    "payload": row["dataset_payload"],
                    "payload_hash": row["dataset_payload_hash"],
                }
            )
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

    def command(self, key, operation, body, *, run_id=None, payload=None, no_op=False, conn=None):
        """Serialize identical requests and changes to one run in a single PG transaction."""
        if (
            not 8 <= len(key) <= 128
            or not all(c.isalnum() or c in "_-" for c in key)
            or key == "host_policy"
        ):
            deny("WEB_IDEMPOTENCY", "Use an 8-128 character idempotency key")
        hashed = digest(
            {"owner": self.policy.owner, "operation": operation, "run_id": run_id, "body": body}
        )
        with self.transaction() if conn is None else nullcontext(conn) as conn:
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
                original = self.run(old["object_id"], conn)
                if (old["operation"], old["body_hash"]) != (operation, hashed):
                    # Only the additive Web policy pin may differ on an upgrade retry.
                    # Return the OLD acknowledgement; never upgrade the saved task's authority.
                    legacy = {k: v for k, v in body.items() if k != "host_policy_sha256"}
                    legacy_hash = digest(
                        {
                            "owner": self.policy.owner,
                            "operation": operation,
                            "run_id": run_id,
                            "body": legacy,
                        }
                    )
                    if not (
                        operation == old["operation"] == "create"
                        and "host_policy_sha256" not in original["payload"]
                        and original["payload"] == legacy
                        and old["body_hash"] == legacy_hash
                    ):
                        deny("WEB_IDEMPOTENCY_CONFLICT", "Key is already bound to another request")
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
                if row["cancel_requested"] and operation != "cancel":
                    deny("CANCELLED", "Accepted cancellation cannot be reversed")
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
                        "command_seq=command_seq+1,cancel_requested=cancel_requested OR :c,"
                        "updated_at=now() "
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

    def dispatch_start(self, run_id):
        """Reuse the outbox status hint to bound launches; never replay a lost launch."""
        with self.transaction() as conn:
            row = self.run(run_id, conn)
            seq = row["command_seq"]
            if seq == row["processed_seq"]:
                return None
            hint = row["status_hint"].split(":")
            previous = len(hint) == 3 and hint[1] == str(seq)
            if previous and not hint[2].isdigit():
                self.dispatch_failed(run_id, seq, conn=conn)
                return None
            attempts = int(hint[2]) if previous else 0
            if previous and (hint[0] != "dispatch_busy" or attempts >= 3):
                self.dispatch_failed(run_id, seq, conn=conn)
                return None
            execute(
                conn,
                "UPDATE execution.web_runs SET status_hint=:h,updated_at=now() WHERE run_id=:r",
                r=run_id,
                h=f"dispatching:{seq}:{attempts + 1}",
            )
            return seq

    def dispatch_failed(self, run_id, seq, *, conn=None):
        if conn is None:
            with self.transaction() as c:
                return self.dispatch_failed(run_id, seq, conn=c)
        execute(
            conn,
            "UPDATE execution.web_runs SET processed_seq=:s,status_hint='blocked',"
            "last_error=CAST(:e AS jsonb),updated_at=now() "
            "WHERE run_id=:r AND owner=:o AND command_seq=:s AND processed_seq<:s",
            s=seq,
            r=run_id,
            o=self.policy.owner,
            e=json_value(
                {
                    "code": "WEB_DISPATCH_FAILED",
                    "message": "后台进程未确认完成；请人工核对，不自动重派",
                    "retryable": False,
                    "manual_action_required": True,
                }
            ),
        )

    def dispatch_busy(self, run_id, seq):
        # Exit 75 is reserved for failure to acquire a slot BEFORE any Runtime work.
        with self.transaction() as conn:
            row = self.run(run_id, conn)
            hint = row["status_hint"].split(":")
            if len(hint) != 3 or hint[:2] != ["dispatching", str(seq)]:
                return
            execute(
                conn,
                "UPDATE execution.web_runs SET status_hint=:h,updated_at=now() "
                "WHERE run_id=:r AND owner=:o AND command_seq=:s AND processed_seq<:s",
                o=self.policy.owner,
                r=run_id,
                s=seq,
                h=f"dispatch_busy:{seq}:{hint[2]}",
            )

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
