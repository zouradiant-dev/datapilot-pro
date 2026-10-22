"""Local product command/session/grant metadata; no business or Saver DDL."""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE execution.web_sessions (
            session_hash TEXT PRIMARY KEY, owner TEXT NOT NULL, csrf_hash TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE execution.web_uploads (
            upload_id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload JSONB NOT NULL,
            payload_hash TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE execution.web_datasets (
            owner TEXT NOT NULL, dataset_id TEXT NOT NULL, version INTEGER NOT NULL,
            source_sha256 TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT true,
            payload JSONB NOT NULL, payload_hash TEXT NOT NULL,
            PRIMARY KEY(owner,dataset_id,version)
        )
    """)
    op.execute("""
        CREATE TABLE execution.web_corpora (
            owner TEXT NOT NULL, corpus_id TEXT NOT NULL, index_version TEXT NOT NULL,
            dataset_id TEXT NOT NULL, dataset_version INTEGER NOT NULL,
            payload JSONB NOT NULL, payload_hash TEXT NOT NULL,
            PRIMARY KEY(owner,corpus_id,index_version)
        )
    """)
    op.execute("""
        CREATE TABLE execution.web_runs (
            run_id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload JSONB NOT NULL,
            payload_hash TEXT NOT NULL, action TEXT NOT NULL,
            command_seq BIGINT NOT NULL DEFAULT 1, processed_seq BIGINT NOT NULL DEFAULT 0,
            status_hint TEXT NOT NULL DEFAULT 'pending',
            cancel_requested BOOLEAN NOT NULL DEFAULT false,
            last_error JSONB, expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE execution.web_requests (
            owner TEXT NOT NULL, idempotency_key TEXT NOT NULL, operation TEXT NOT NULL,
            body_hash TEXT NOT NULL, object_id TEXT NOT NULL, response JSONB NOT NULL,
            retired BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(owner,idempotency_key)
        )
    """)
    op.execute("""
        CREATE TABLE execution.retention_holds (
            run_id TEXT PRIMARY KEY, active BOOLEAN NOT NULL DEFAULT true,
            reason TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE execution.retention_audit (
            audit_id TEXT PRIMARY KEY, run_id_hash TEXT NOT NULL, plan_hash TEXT NOT NULL,
            counts JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    for name in ("sessions", "uploads", "datasets", "corpora", "runs", "requests"):
        op.execute(f"GRANT SELECT,INSERT,UPDATE ON execution.web_{name} TO datapilot_web")
    for name in ("runs", "ledger", "calls", "artifacts", "events", "web_runs"):
        op.execute(f"GRANT SELECT,DELETE ON execution.{name} TO datapilot_maintenance")
    op.execute("GRANT SELECT ON execution.web_requests TO datapilot_maintenance")
    op.execute("GRANT UPDATE (retired,response) ON execution.web_requests TO datapilot_maintenance")
    op.execute("GRANT SELECT,INSERT,UPDATE ON execution.retention_holds TO datapilot_maintenance")
    op.execute("GRANT SELECT,INSERT ON execution.retention_audit TO datapilot_maintenance")


def downgrade():
    raise RuntimeError("Product history requires an explicit retention procedure, not downgrade")
