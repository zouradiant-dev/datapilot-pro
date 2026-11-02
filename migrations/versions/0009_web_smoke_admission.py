"""Persist one-shot Web smoke case admission; execution stays in the original outbox."""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE execution.web_smoke_admissions (
            owner TEXT NOT NULL,
            case_id TEXT NOT NULL,
            permit_sha256 TEXT NOT NULL,
            freeze_sha256 TEXT NOT NULL,
            request_sha256 TEXT NOT NULL,
            message_id TEXT NOT NULL,
            goal_contract_sha256 TEXT,
            run_id TEXT,
            binding JSONB NOT NULL CHECK(octet_length(binding::text)<=32768),
            admitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(owner,case_id),
            UNIQUE(run_id),
            UNIQUE(message_id)
        )
        """
    )
    op.execute("GRANT SELECT,INSERT,UPDATE ON execution.web_smoke_admissions TO datapilot_web")


def downgrade():
    raise RuntimeError("Smoke admission history requires an explicit retention decision")
