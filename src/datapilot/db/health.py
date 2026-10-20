"""Checks actual version, extension, migration, seed and runtime role."""

import sqlalchemy as sa

from datapilot.db.management import migration_head
from datapilot.tools.sql import SQLPolicy, verify_reader


def database_health(reader_url: str, *, upload_reader_url: str | None = None) -> dict:
    engine = sa.create_engine(reader_url, hide_parameters=True, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as conn:
            verify_reader(conn)
            version = int(conn.exec_driver_sql("SHOW server_version_num").scalar_one())
            extension = conn.exec_driver_sql(
                "SELECT extversion FROM pg_extension WHERE extname='vector'"
            ).scalar_one_or_none()
            if version // 10000 != 17 or not extension:
                raise ValueError("PostgreSQL 17 and pgvector are required")
            revision = conn.exec_driver_sql(
                "SELECT version_num FROM saas.alembic_version"
            ).scalar_one()
            if revision != migration_head():
                raise ValueError("Database migration is not at the expected revision")
            count = conn.exec_driver_sql("SELECT COUNT(*) FROM saas.customers").scalar_one()
            if not count:
                raise ValueError("Business data is not seeded")
            result = {
                "status": "healthy",
                "postgres_version_num": version,
                "pgvector": extension,
                "migration": revision,
                "customers": count,
                "seeded": count > 0,
            }
        if upload_reader_url:
            upload = sa.create_engine(
                upload_reader_url, hide_parameters=True, connect_args={"connect_timeout": 5}
            )
            try:
                with upload.connect() as conn:
                    verify_reader(conn, SQLPolicy("uploads", frozenset()))
                    for table in ("datasets", "versions", "tables", "columns"):
                        conn.exec_driver_sql(f"SELECT 1 FROM catalog.{table} LIMIT 0")
                    result["uploads"] = {"status": "healthy", "catalog_tables": 4}
            finally:
                upload.dispose()
        return result
    finally:
        engine.dispose()
