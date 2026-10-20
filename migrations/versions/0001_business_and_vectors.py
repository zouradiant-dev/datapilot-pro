"""Frozen Day 1 schema snapshot. Do not import mutable application metadata here."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

BUSINESS_TABLES = ("customers", "subscriptions", "invoices", "usage_events", "customer_feedback")
metadata = sa.MetaData(naming_convention={"ix": "ix_%(table_name)s_%(column_0_name)s"})

customers = sa.Table(
    "customers",
    metadata,
    sa.Column("customer_id", sa.Integer, primary_key=True, autoincrement=False),
    sa.Column("name", sa.String(128), nullable=False),
    sa.Column("segment", sa.String(32), nullable=False),
    sa.Column("industry", sa.String(32), nullable=False),
    sa.Column("region", sa.String(32), nullable=False),
    sa.Column("created_at", sa.Date, nullable=False),
    sa.CheckConstraint("segment IN ('small','midmarket','enterprise')"),
    schema="saas",
)
subscriptions = sa.Table(
    "subscriptions",
    metadata,
    sa.Column("subscription_id", sa.Integer, primary_key=True, autoincrement=False),
    sa.Column(
        "customer_id", sa.ForeignKey("saas.customers.customer_id"), nullable=False, index=True
    ),
    sa.Column("plan", sa.String(32), nullable=False),
    sa.Column("monthly_price_cents", sa.BigInteger, nullable=False),
    sa.Column("start_date", sa.Date, nullable=False, index=True),
    sa.Column("end_date", sa.Date),
    sa.Column("status", sa.String(32), nullable=False),
    sa.CheckConstraint("plan IN ('starter','pro','enterprise')"),
    sa.CheckConstraint("monthly_price_cents >= 0"),
    sa.CheckConstraint("end_date IS NULL OR end_date > start_date"),
    sa.CheckConstraint(
        "(status='active' AND end_date IS NULL) OR "
        "(status IN ('churned','downgraded') AND end_date IS NOT NULL)"
    ),
    schema="saas",
)
invoices = sa.Table(
    "invoices",
    metadata,
    sa.Column("invoice_id", sa.Integer, primary_key=True, autoincrement=False),
    sa.Column(
        "subscription_id",
        sa.ForeignKey("saas.subscriptions.subscription_id"),
        nullable=False,
        index=True,
    ),
    sa.Column("invoice_date", sa.Date, nullable=False, index=True),
    sa.Column("amount_cents", sa.BigInteger, nullable=False),
    sa.Column("currency", sa.String(3), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.CheckConstraint("amount_cents >= 0 AND currency='CNY'"),
    sa.CheckConstraint("status IN ('paid','unpaid')"),
    schema="saas",
)
usage_events = sa.Table(
    "usage_events",
    metadata,
    sa.Column("event_id", sa.Integer, primary_key=True, autoincrement=False),
    sa.Column(
        "subscription_id",
        sa.ForeignKey("saas.subscriptions.subscription_id"),
        nullable=False,
        index=True,
    ),
    sa.Column("event_date", sa.Date, nullable=False, index=True),
    sa.Column("feature", sa.String(64), nullable=False),
    sa.Column("event_count", sa.Integer, nullable=False),
    sa.CheckConstraint("event_count >= 0"),
    schema="saas",
)
customer_feedback = sa.Table(
    "customer_feedback",
    metadata,
    sa.Column("feedback_id", sa.Integer, primary_key=True, autoincrement=False),
    sa.Column(
        "customer_id", sa.ForeignKey("saas.customers.customer_id"), nullable=False, index=True
    ),
    sa.Column(
        "subscription_id", sa.ForeignKey("saas.subscriptions.subscription_id"), nullable=False
    ),
    sa.Column("submitted_at", sa.Date, nullable=False),
    sa.Column("category", sa.String(64), nullable=False),
    sa.Column("score", sa.Integer, nullable=False),
    sa.Column("comment", sa.String(2048), nullable=False),
    sa.CheckConstraint("score BETWEEN 1 AND 5"),
    schema="saas",
)
seed_runs = sa.Table(
    "seed_runs",
    metadata,
    sa.Column("seed_id", sa.Integer, primary_key=True, autoincrement=False),
    sa.Column("manifest", sa.JSON, nullable=False),
    schema="saas",
)
document_chunks = sa.Table(
    "document_chunks",
    metadata,
    sa.Column("chunk_id", sa.Integer, primary_key=True, autoincrement=False),
    sa.Column("source_uri", sa.Text, nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("embedding_model", sa.String(128), nullable=False),
    sa.Column("embedding_dim", sa.Integer, nullable=False),
    # Dimension/index will be pinned in Day 3 when the embedding model is selected.
    sa.Column("embedding", Vector(), nullable=False),
    sa.CheckConstraint("embedding_dim > 0 AND public.vector_dims(embedding)=embedding_dim"),
    schema="rag",
)


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade():
    metadata.drop_all(op.get_bind(), checkfirst=False)
