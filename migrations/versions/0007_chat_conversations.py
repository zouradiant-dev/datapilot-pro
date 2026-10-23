"""Private bounded conversation index; execution remains in the original outbox."""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE execution.web_conversations (
            conversation_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
            create_key TEXT NOT NULL, request_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL,
            UNIQUE(owner,create_key)
        )
    """)
    op.execute("""
        CREATE TABLE execution.web_messages (
            message_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES execution.web_conversations(conversation_id),
            sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 200),
            request_key TEXT NOT NULL, request_hash TEXT NOT NULL,
            payload JSONB NOT NULL CHECK(octet_length(payload::text)<=32768),
            payload_hash TEXT NOT NULL, run_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(conversation_id,sequence), UNIQUE(conversation_id,request_key)
        )
    """)
    op.execute("GRANT SELECT,INSERT ON execution.web_conversations TO datapilot_web")
    op.execute("GRANT SELECT,INSERT ON execution.web_messages TO datapilot_web")
    op.execute("GRANT UPDATE (run_id) ON execution.web_messages TO datapilot_web")


def downgrade():
    raise RuntimeError("Conversation history requires an explicit retention decision")
