"""Explicit deployment only. Requests never call official Saver.setup()."""

import psycopg
import sqlalchemy as sa
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from datapilot.db.management import management_url


def runtime_init():
    url = make_url(management_url("checkpoint_owner"))
    conninfo = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(
        conninfo, autocommit=True, prepare_threshold=0, row_factory=dict_row
    ) as conn:
        conn.execute("SET search_path=checkpoints,pg_catalog")
        PostgresSaver(conn).setup()
        for table in (
            "checkpoint_migrations",
            "checkpoints",
            "checkpoint_blobs",
            "checkpoint_writes",
        ):
            if table == "checkpoint_migrations":
                conn.execute(
                    "REVOKE ALL ON checkpoints.checkpoint_migrations FROM datapilot_runtime"
                )
                conn.execute(
                    "GRANT SELECT ON checkpoints.checkpoint_migrations TO datapilot_runtime"
                )
                conn.execute(
                    "GRANT SELECT ON checkpoints.checkpoint_migrations TO datapilot_maintenance"
                )
            else:
                conn.execute(
                    f"GRANT SELECT,INSERT,UPDATE ON checkpoints.{table} TO datapilot_runtime"
                )
                conn.execute(f"GRANT SELECT,DELETE ON checkpoints.{table} TO datapilot_maintenance")
    engine = sa.create_engine(management_url("runtime"), hide_parameters=True)
    try:
        with engine.connect() as conn:
            if (
                conn.exec_driver_sql(
                    "SELECT max(v) FROM checkpoints.checkpoint_migrations"
                ).scalar_one()
                != len(PostgresSaver.MIGRATIONS) - 1
            ):
                raise ValueError("Saver schema is not at the pinned version")
            conn.exec_driver_sql("SELECT 1 FROM execution.runs LIMIT 0")
    finally:
        engine.dispose()
