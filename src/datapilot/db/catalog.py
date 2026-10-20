"""Fixed P2 catalog tables. Dynamic uploads tables are not part of migration metadata."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()
datasets = sa.Table(
    "datasets",
    metadata,
    sa.Column("dataset_id", sa.String(36), primary_key=True),
    sa.Column("name", sa.String(128), nullable=False, unique=True),
    sa.Column("current_version", sa.Integer),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    schema="catalog",
)
versions = sa.Table(
    "versions",
    metadata,
    sa.Column(
        "dataset_id", sa.String(36), sa.ForeignKey("catalog.datasets.dataset_id"), primary_key=True
    ),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("source_sha256", sa.String(64), nullable=False),
    sa.Column("confirmation_sha256", sa.String(64), nullable=False),
    sa.Column("source_ref", sa.String(80), nullable=False),
    sa.Column("source_filename", sa.String(255), nullable=False),
    sa.Column("file_format", sa.String(8), nullable=False),
    sa.Column("parser_version", sa.String(16), nullable=False),
    sa.Column("confirmation", JSONB, nullable=False),
    sa.Column("row_count", sa.Integer, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("dataset_id", "confirmation_sha256"),
    sa.CheckConstraint("version BETWEEN 1 AND 1000000"),
    sa.CheckConstraint("status IN ('importing','ready')"),
    sa.CheckConstraint("row_count BETWEEN 0 AND 100000"),
    schema="catalog",
)
tables = sa.Table(
    "tables",
    metadata,
    sa.Column("dataset_id", sa.String(36), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("table_id", sa.String(63), primary_key=True),
    sa.Column("source_name", sa.String(255), nullable=False),
    sa.Column("physical_name", sa.String(63), nullable=False, unique=True),
    sa.Column("row_count", sa.Integer, nullable=False),
    sa.Column("primary_key", JSONB, nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_id", "version"], ["catalog.versions.dataset_id", "catalog.versions.version"]
    ),
    sa.CheckConstraint("row_count BETWEEN 0 AND 100000"),
    schema="catalog",
)
columns = sa.Table(
    "columns",
    metadata,
    sa.Column("dataset_id", sa.String(36), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("table_id", sa.String(63), primary_key=True),
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("source_column", sa.String(63), nullable=False),
    sa.Column("original_name", sa.Text),
    sa.Column("normalized_name", sa.String(63), nullable=False),
    sa.Column("logical_type", sa.String(16), nullable=False),
    sa.Column("sql_type", sa.String(64), nullable=False),
    sa.UniqueConstraint("dataset_id", "version", "table_id", "normalized_name"),
    sa.ForeignKeyConstraint(
        ["dataset_id", "version", "table_id"],
        ["catalog.tables.dataset_id", "catalog.tables.version", "catalog.tables.table_id"],
    ),
    sa.CheckConstraint("position BETWEEN 1 AND 100"),
    schema="catalog",
)
datasets.append_constraint(
    sa.ForeignKeyConstraint(
        ["dataset_id", "current_version"],
        ["catalog.versions.dataset_id", "catalog.versions.version"],
        name="fk_current_dataset_version",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
    )
)
