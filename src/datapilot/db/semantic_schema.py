"""Fixed, append-only P3 registry tables. Owner migration only; no business-data privileges."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from datapilot.db.catalog import metadata

semantic_versions = sa.Table(
    "semantic_versions",
    metadata,
    sa.Column("dataset_id", sa.String(36), primary_key=True),
    sa.Column("dataset_version", sa.Integer, primary_key=True),
    sa.Column("semantic_version", sa.Integer, primary_key=True),
    sa.Column("source_sha256", sa.String(64), nullable=False),
    sa.Column("definition_sha256", sa.String(64), nullable=False),
    sa.Column("definition", JSONB, nullable=False),
    sa.Column("confirmed_by", sa.String(64), nullable=False),
    sa.Column(
        "confirmed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("dataset_id", "dataset_version", "definition_sha256"),
    sa.ForeignKeyConstraint(
        ["dataset_id", "dataset_version"],
        ["catalog.versions.dataset_id", "catalog.versions.version"],
    ),
    sa.CheckConstraint("semantic_version BETWEEN 1 AND 1000000"),
    schema="catalog",
)
metric_versions = sa.Table(
    "metric_versions",
    metadata,
    sa.Column("dataset_id", sa.String(36), primary_key=True),
    sa.Column("dataset_version", sa.Integer, primary_key=True),
    sa.Column("metric_id", sa.String(48), primary_key=True),
    sa.Column("metric_version", sa.Integer, primary_key=True),
    sa.Column("semantic_version", sa.Integer, nullable=False),
    sa.Column("semantic_sha256", sa.String(64), nullable=False),
    sa.Column("definition_sha256", sa.String(64), nullable=False),
    sa.Column("definition", JSONB, nullable=False),
    sa.Column("confirmed_by", sa.String(64), nullable=False),
    sa.Column(
        "confirmed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("dataset_id", "dataset_version", "metric_id", "definition_sha256"),
    sa.UniqueConstraint(
        "dataset_id", "dataset_version", "metric_id", "metric_version", "semantic_version"
    ),
    sa.ForeignKeyConstraint(
        ["dataset_id", "dataset_version", "semantic_version"],
        [
            "catalog.semantic_versions.dataset_id",
            "catalog.semantic_versions.dataset_version",
            "catalog.semantic_versions.semantic_version",
        ],
    ),
    sa.CheckConstraint("metric_version BETWEEN 1 AND 1000000"),
    schema="catalog",
)
evidence = sa.Table(
    "evidence",
    metadata,
    sa.Column("evidence_id", sa.String(36), primary_key=True),
    sa.Column("dataset_id", sa.String(36), nullable=False),
    sa.Column("dataset_version", sa.Integer, nullable=False),
    sa.Column("metric_id", sa.String(48), nullable=False),
    sa.Column("metric_version", sa.Integer, nullable=False),
    sa.Column("semantic_version", sa.Integer, nullable=False),
    sa.Column("body", JSONB, nullable=False),
    sa.Column("body_sha256", sa.String(64), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("evidence_id", "dataset_id", "dataset_version"),
    sa.ForeignKeyConstraint(
        ["dataset_id", "dataset_version", "metric_id", "metric_version", "semantic_version"],
        [
            "catalog.metric_versions.dataset_id",
            "catalog.metric_versions.dataset_version",
            "catalog.metric_versions.metric_id",
            "catalog.metric_versions.metric_version",
            "catalog.metric_versions.semantic_version",
        ],
    ),
    schema="catalog",
)
verification_runs = sa.Table(
    "verification_runs",
    metadata,
    sa.Column("verification_id", sa.String(36), primary_key=True),
    sa.Column("evidence_id", sa.String(36), nullable=False),
    sa.Column("dataset_id", sa.String(36), nullable=False),
    sa.Column("dataset_version", sa.Integer, nullable=False),
    sa.Column("verdict", sa.String(16), nullable=False),
    sa.Column("body", JSONB, nullable=False),
    sa.Column("body_sha256", sa.String(64), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.ForeignKeyConstraint(
        ["evidence_id", "dataset_id", "dataset_version"],
        [
            "catalog.evidence.evidence_id",
            "catalog.evidence.dataset_id",
            "catalog.evidence.dataset_version",
        ],
    ),
    sa.CheckConstraint("verdict IN ('verified','unavailable','rejected')"),
    schema="catalog",
)

REGISTRY_TABLES = (semantic_versions, metric_versions, evidence, verification_runs)
