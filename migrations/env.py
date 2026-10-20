from alembic import context
from sqlalchemy import create_engine, pool

from datapilot.db.management import management_url
from datapilot.db.schema import metadata

# Credentials live only in environment, never in alembic.ini or log configuration.
engine = create_engine(management_url("owner"), poolclass=pool.NullPool, hide_parameters=True)
try:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=metadata,
            include_schemas=True,
            version_table_schema="saas",
        )
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
