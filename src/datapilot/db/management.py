"""Explicit administrative operations; never exposed as MCP tools."""

import os

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from psycopg import sql
from sqlalchemy.engine import make_url

from datapilot.db.schema import BUSINESS_TABLES


def management_url(role: str) -> str:
    load_dotenv()
    value = os.environ.get(f"DATAPILOT_{role.upper()}_DATABASE_URL", "")
    url = make_url(value)
    expected = {"owner": "datapilot_owner", "seed": "datapilot_seed"}.get(role)
    if url.drivername != "postgresql+psycopg" or (expected and url.username != expected):
        raise ValueError("Use the designated PostgreSQL role")
    return value


def initialize() -> None:
    """Idempotently establish database roles, schemas and pgvector with admin credentials."""
    url = management_url("admin")
    engine = sa.create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 5})
    try:
        with engine.begin() as conn:
            version = int(conn.exec_driver_sql("SHOW server_version_num").scalar_one())
            if version // 10000 != 17:
                raise ValueError("PostgreSQL 17 is required")
            raw = conn.connection.driver_connection
            with raw.cursor() as cursor:
                for suffix in ("owner", "seed", "reader"):
                    role = "datapilot_" + suffix
                    password = os.environ.get(f"DATAPILOT_{suffix.upper()}_PASSWORD", "")
                    if not password or password.startswith("CHANGE_ME"):
                        raise ValueError("Set distinct non-placeholder role passwords")
                    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
                    if not cursor.fetchone():
                        cursor.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
                    cursor.execute(
                        sql.SQL(
                            "ALTER ROLE {} PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                            "NOREPLICATION NOBYPASSRLS NOINHERIT"
                        ).format(sql.Identifier(role), sql.Literal(password))
                    )
                db = make_url(url).database
                cursor.execute(
                    sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(db))
                )
                cursor.execute(
                    sql.SQL(
                        "GRANT CONNECT ON DATABASE {} "
                        "TO datapilot_owner,datapilot_seed,datapilot_reader"
                    ).format(sql.Identifier(db))
                )
            conn.exec_driver_sql("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS saas AUTHORIZATION datapilot_owner")
            conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS rag AUTHORIZATION datapilot_owner")
            conn.exec_driver_sql("ALTER ROLE datapilot_reader SET default_transaction_read_only=on")
            conn.exec_driver_sql("ALTER ROLE datapilot_reader SET statement_timeout='2s'")
            conn.exec_driver_sql("ALTER ROLE datapilot_reader SET lock_timeout='1s'")
            conn.exec_driver_sql("ALTER ROLE datapilot_reader SET search_path=pg_catalog,saas")
            conn.exec_driver_sql("GRANT USAGE ON SCHEMA saas TO datapilot_reader,datapilot_seed")
    finally:
        engine.dispose()


def migrate() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")


def grant_business_access() -> None:
    engine = sa.create_engine(management_url("owner"), hide_parameters=True)
    try:
        with engine.begin() as conn:
            for table in BUSINESS_TABLES:
                conn.exec_driver_sql(f"GRANT SELECT ON saas.{table} TO datapilot_reader")
                conn.exec_driver_sql(f"GRANT SELECT,INSERT ON saas.{table} TO datapilot_seed")
            conn.exec_driver_sql("GRANT SELECT,INSERT ON saas.seed_runs TO datapilot_seed")
            # Metadata-only health checks; never exposed by the SQL table whitelist.
            conn.exec_driver_sql("GRANT SELECT ON saas.alembic_version TO datapilot_reader")
    finally:
        engine.dispose()
