"""P5B domain runtime metadata; official Saver owns its separate schema/migrations."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE execution.runs (
            run_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            manifest JSONB NOT NULL,
            manifest_hash TEXT NOT NULL,
            cancelled BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE execution.ledger (
            run_id TEXT PRIMARY KEY REFERENCES execution.runs(run_id),
            payload JSONB NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE execution.artifacts (
            run_id TEXT NOT NULL REFERENCES execution.runs(run_id),
            artifact_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            plan_version INTEGER NOT NULL,
            kind TEXT NOT NULL,
            payload JSONB NOT NULL,
            bytes INTEGER NOT NULL CHECK (bytes > 0),
            PRIMARY KEY (run_id,artifact_id)
        )
    """)
    op.execute("""
        CREATE TABLE execution.calls (
            run_id TEXT NOT NULL REFERENCES execution.runs(run_id),
            call_key TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('model','tool')),
            account TEXT NOT NULL,
            tool_name TEXT,
            status TEXT NOT NULL CHECK (status IN ('issued','complete','uncertain')),
            ticket TEXT,
            payload JSONB,
            payload_hash TEXT,
            elapsed_ms DOUBLE PRECISION,
            usage JSONB,
            PRIMARY KEY (run_id,call_key)
        )
    """)
    op.execute("""
        CREATE TABLE execution.events (
            run_id TEXT NOT NULL REFERENCES execution.runs(run_id),
            event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "GRANT SELECT,INSERT,UPDATE ON execution.runs,execution.ledger,execution.calls "
        "TO datapilot_runtime"
    )
    op.execute("GRANT SELECT,INSERT ON execution.artifacts,execution.events TO datapilot_runtime")
    op.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA execution TO datapilot_runtime")


def downgrade():
    raise RuntimeError(
        "Runtime history is retained; destructive downgrade requires a separate procedure"
    )
