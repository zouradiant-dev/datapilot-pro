"""Read-only catalog resolution and per-request physical policies, inside the MCP server."""

import hashlib
import threading

import sqlalchemy as sa
from pydantic import ValidationError

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import (
    DatasetColumn,
    DatasetListing,
    DatasetQueryResult,
    DatasetSchema,
    DatasetScope,
    DatasetSummary,
    DatasetTable,
)
from datapilot.db import catalog
from datapilot.ingestion.common import digest
from datapilot.tools.sql import SQLPolicy, SQLRepository, validate_sql, verify_reader


class DatasetRepository:
    def __init__(
        self, url: str, scope: DatasetScope, *, max_rows: int = 100, timeout_seconds: float = 2
    ):
        self.scope = DatasetScope.model_validate_json(scope.model_dump_json())
        self.bindings = {b.dataset_id: b.version for b in self.scope.bindings}
        self.pinned: dict[str, DatasetSchema] = {}
        self._pin_lock = threading.RLock()
        self.sql = SQLRepository(
            url, profile="uploads", max_rows=max_rows, timeout_seconds=timeout_seconds
        )

    def close(self):
        self.sql.close()

    def schema(self, dataset_id: str) -> DatasetSchema:
        with self._pin_lock:
            return self._resolve_schema(dataset_id)

    def _resolve_schema(self, dataset_id: str) -> DatasetSchema:
        if dataset_id not in self.bindings:
            raise AgentFailure(
                "DATASET_NOT_AUTHORIZED", "Dataset is outside the server-bound scope"
            )
        if dataset_id in self.pinned:
            return self.pinned[dataset_id].model_copy(deep=True)
        try:
            with self.sql.engine.connect() as conn, conn.begin():
                self.sql._configure(conn)
                selected = self.bindings[dataset_id]
                ds = (
                    conn.execute(
                        sa.select(catalog.datasets).where(
                            catalog.datasets.c.dataset_id == dataset_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if ds is None:
                    raise AgentFailure("DATASET_NOT_FOUND", "Ready dataset version does not exist")
                selected = selected if selected is not None else ds["current_version"]
                version = (
                    conn.execute(
                        sa.select(catalog.versions).where(
                            catalog.versions.c.dataset_id == dataset_id,
                            catalog.versions.c.version == selected,
                            catalog.versions.c.status == "ready",
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if version is None:
                    raise AgentFailure("DATASET_NOT_FOUND", "Ready dataset version does not exist")
                table_rows = (
                    conn.execute(
                        sa.select(catalog.tables)
                        .where(
                            catalog.tables.c.dataset_id == dataset_id,
                            catalog.tables.c.version == selected,
                        )
                        .order_by(catalog.tables.c.table_id)
                        .limit(33)
                    )
                    .mappings()
                    .all()
                )
                tables = []
                for row in table_rows:
                    column_rows = (
                        conn.execute(
                            sa.select(catalog.columns)
                            .where(
                                catalog.columns.c.dataset_id == dataset_id,
                                catalog.columns.c.version == selected,
                                catalog.columns.c.table_id == row["table_id"],
                            )
                            .order_by(catalog.columns.c.position)
                            .limit(101)
                        )
                        .mappings()
                        .all()
                    )
                    tables.append(
                        DatasetTable(
                            table_id=row["table_id"],
                            source_name=row["source_name"],
                            physical_name=row["physical_name"],
                            row_count=row["row_count"],
                            primary_key=row["primary_key"],
                            columns=[
                                DatasetColumn(
                                    **{key: col[key] for key in DatasetColumn.model_fields}
                                )
                                for col in column_rows
                            ],
                        )
                    )
                schema = DatasetSchema(
                    dataset_id=dataset_id,
                    name=ds["name"],
                    version=selected,
                    source_sha256=version["source_sha256"],
                    row_count=version["row_count"],
                    tables=tables,
                )
                if len(schema.model_dump_json().encode("utf-8")) > 2 * 1024**2:
                    raise AgentFailure(
                        "RESULT_TOO_LARGE", "Dataset metadata exceeds the byte limit"
                    )
                # Validate real SELECT grants in addition to catalog records and AST policy.
                verify_reader(
                    conn, SQLPolicy("uploads", frozenset(t.physical_name for t in tables))
                )
            self.pinned[dataset_id] = schema
            return schema.model_copy(deep=True)
        except (sa.exc.SQLAlchemyError, ValidationError, ValueError) as exc:
            raise AgentFailure(
                "DATASET_METADATA_ERROR", "Cannot resolve ready dataset metadata and grants"
            ) from exc

    def listing(self) -> DatasetListing:
        return DatasetListing(
            datasets=[
                DatasetSummary(**{key: getattr(schema, key) for key in DatasetSummary.model_fields})
                for dataset_id in self.bindings
                for schema in [self.schema(dataset_id)]
            ]
        )

    def execute(self, dataset_id: str, sql: str) -> DatasetQueryResult:
        schema = self.schema(dataset_id)
        policy = SQLPolicy("uploads", frozenset(t.physical_name for t in schema.tables))
        checked = validate_sql(sql, policy)
        result = self.sql.execute(checked, policy)
        return DatasetQueryResult(
            dataset_id=dataset_id,
            version=schema.version,
            source_sha256=schema.source_sha256,
            query_sha256=hashlib.sha256(checked.encode("utf-8")).hexdigest(),
            result_sha256=digest(result.model_dump(mode="json", exclude={"elapsed_ms"})),
            result=result,
        )
