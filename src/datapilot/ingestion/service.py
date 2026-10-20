"""Trusted local ingestion service. Never register this module or its credentials as model tools."""

import hashlib
import os
import time
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import sqlalchemy as sa
from psycopg import sql
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding, ImportRequest, ImportResult
from datapilot.db import catalog
from datapilot.ingestion.common import read_file
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import (
    ColumnOverride,
    ConfirmationOverrides,
    ConfirmedColumn,
    ParsedDataset,
    ParseFailure,
    ParseLimits,
    SchemaConfirmation,
)
from datapilot.ingestion.parser import parse_bytes
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.types import convert_value


def verify_ingest(conn) -> None:
    row = conn.exec_driver_sql(
        "SELECT current_user,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,"
        "EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid) "
        "FROM pg_roles r WHERE rolname=current_user"
    ).one()
    if row[0] != "datapilot_ingest" or any(row[1:]):
        raise AgentFailure("ROLE_UNSAFE", "Imports require the isolated ingest identity")
    unsafe = conn.exec_driver_sql(
        "SELECT has_database_privilege(current_user,current_database(),'CREATE,TEMP') OR "
        "NOT has_schema_privilege(current_user,'uploads','CREATE') OR "
        "EXISTS(SELECT 1 FROM pg_namespace WHERE left(nspname,3) <> 'pg_' "
        "AND nspname <> 'uploads' AND has_schema_privilege(current_user,oid,'CREATE')) OR "
        "has_schema_privilege(current_user,'saas','USAGE') OR "
        "has_schema_privilege(current_user,'rag','USAGE')"
    ).scalar_one()
    if unsafe:
        raise AgentFailure("ROLE_UNSAFE", "Ingest may create objects only in uploads")


def validate_confirmation(
    data: ParsedDataset, confirmation: SchemaConfirmation
) -> SchemaConfirmation:
    """Compare reconstructed overrides against a fresh full-data confirmation."""
    overrides = []
    keys = {}
    for table in confirmation.tables:
        mapping = {c.normalized_name: c.source_column for c in table.columns}
        if len(mapping) != len(table.columns) or any(k not in mapping for k in table.primary_key):
            raise ParseFailure("CONFIRMATION_INVALID", "Invalid confirmed column/key mapping")
        keys[table.table_id] = [mapping[k] for k in table.primary_key]
        overrides.extend(
            ColumnOverride(
                table_id=table.table_id,
                column=c.source_column,
                logical_type=c.logical_type,
                normalized_name=c.normalized_name,
                date_format=c.date_format,
            )
            for c in table.columns
        )
    expected = confirm_schema(
        data,
        propose_schema(data),
        reviewed=True,
        overrides=ConfirmationOverrides(
            columns=overrides,
            primary_keys=keys,
            relation_ids=[r.relation_id for r in confirmation.accepted_relations],
        ),
    )
    if expected != confirmation:
        raise ParseFailure(
            "CONFIRMATION_STALE", "Source or confirmation changed; preview and confirm again"
        )
    return expected


def column_type(column: ConfirmedColumn, values: list) -> sa.types.TypeEngine:
    if column.logical_type == "NUMERIC":
        return sa.Numeric(precision=column.precision, scale=column.scale)
    if column.logical_type == "TIMESTAMP":
        awareness = {v.tzinfo is not None for v in values if isinstance(v, datetime)}
        if len(awareness) > 1:
            raise ParseFailure(
                "TIMESTAMP_AMBIGUOUS", "A timestamp column cannot mix naive and aware values"
            )
        return sa.DateTime(timezone=True in awareness)
    return {"TEXT": sa.Text, "INTEGER": sa.BigInteger, "BOOLEAN": sa.Boolean, "DATE": sa.Date}[
        column.logical_type
    ]()


class IngestionService:
    def __init__(self, url: str, *, storage_dir: Path, limits: ParseLimits | None = None):
        parsed = make_url(url)
        if parsed.drivername != "postgresql+psycopg" or parsed.username != "datapilot_ingest":
            raise ValueError("Use the isolated PostgreSQL ingest role")
        self.engine = sa.create_engine(
            url, hide_parameters=True, connect_args={"connect_timeout": 5}
        )
        self.storage_dir = Path(storage_dir)
        self.limits = limits or ParseLimits()

    def close(self) -> None:
        self.engine.dispose()

    def _configure(self, conn):
        conn.exec_driver_sql("SET LOCAL statement_timeout='30s'")
        conn.exec_driver_sql("SET LOCAL lock_timeout='5s'")
        conn.exec_driver_sql("SET LOCAL search_path=pg_catalog")
        conn.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
        verify_ingest(conn)

    def _lock(self, conn, dataset_id):
        key = int.from_bytes(hashlib.sha256(dataset_id.encode()).digest()[:8], "big", signed=True)
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    def _snapshot(self, payload: bytes, source_hash: str, file_format: str) -> str:
        # Only a verified digest and a whitelisted format enter the physical filename.
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        if self.storage_dir.is_symlink():
            raise AgentFailure("SOURCE_STORAGE_ERROR", "Snapshot directory must not be a symlink")
        ref = f"{source_hash}.{file_format}"
        path = self.storage_dir / ref
        if path.is_symlink():
            raise AgentFailure("SOURCE_STORAGE_ERROR", "Snapshot must not be a symlink")
        staging = self.storage_dir / f".{source_hash}.{uuid4().hex}.tmp"
        try:
            with staging.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Atomic exclusive publication: readers never see a partial snapshot.
                os.link(staging, path)
            except FileExistsError:
                pass
            if (
                hashlib.sha256(read_file(path, self.limits.max_file_bytes)).hexdigest()
                != source_hash
            ):
                raise AgentFailure(
                    "SOURCE_STORAGE_ERROR", "Existing snapshot failed its integrity check"
                ) from None
        except OSError as exc:
            raise AgentFailure(
                "SOURCE_STORAGE_ERROR", "Cannot publish the local source snapshot"
            ) from exc
        finally:
            staging.unlink(missing_ok=True)
        return ref

    def _write_rows(self, conn, table, rows, deadline):
        for start in range(0, len(rows), 1000):
            if time.monotonic() > deadline:
                raise AgentFailure("IMPORT_TIMEOUT", "Import exceeded its execution budget")
            conn.execute(table.insert(), rows[start : start + 1000])

    def import_file(
        self, path: str | Path, confirmation: SchemaConfirmation, request: ImportRequest
    ) -> ImportResult:
        # Roundtrip enforces validation even if the caller used model_copy/model_construct.
        confirmation = SchemaConfirmation.model_validate_json(confirmation.model_dump_json())
        request = ImportRequest.model_validate_json(request.model_dump_json())
        for key in type(self.limits).model_fields:
            if key.startswith("max_") and getattr(confirmation.limits, key) > getattr(
                self.limits, key
            ):
                raise ParseFailure(
                    "IMPORT_LIMIT", "Confirmation exceeds the service resource policy"
                )
        payload = read_file(Path(path), self.limits.max_file_bytes)
        data = parse_bytes(
            payload, Path(path).name, options=confirmation.options, limits=confirmation.limits
        )
        validate_confirmation(data, confirmation)
        dataset_id = request.dataset_id or str(
            uuid5(NAMESPACE_URL, "datapilot:local:" + request.name)
        )
        source_ref = self._snapshot(payload, data.upload.sha256, data.upload.file_format)
        deadline = time.monotonic() + 120
        try:
            with self.engine.begin() as conn:
                self._configure(conn)
                self._lock(conn, dataset_id)
                dataset = (
                    conn.execute(
                        sa.select(catalog.datasets)
                        .where(catalog.datasets.c.dataset_id == dataset_id)
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if dataset is None:
                    if request.dataset_id is not None:
                        raise AgentFailure(
                            "DATASET_NOT_FOUND", "Select an existing dataset or create one by name"
                        )
                    conn.execute(
                        catalog.datasets.insert().values(dataset_id=dataset_id, name=request.name)
                    )
                elif dataset["name"] != request.name:
                    raise AgentFailure(
                        "DATASET_NAME_MISMATCH", "Existing dataset name does not match"
                    )
                base = catalog.versions.c.dataset_id == dataset_id
                existing = (
                    conn.execute(
                        sa.select(catalog.versions).where(
                            base,
                            catalog.versions.c.confirmation_sha256
                            == confirmation.confirmation_sha256,
                            catalog.versions.c.status == "ready",
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing:
                    return ImportResult(
                        dataset_id=dataset_id,
                        version=existing["version"],
                        source_sha256=existing["source_sha256"],
                        confirmation_sha256=existing["confirmation_sha256"],
                        reused=True,
                        row_count=existing["row_count"],
                    )
                version = (
                    conn.execute(
                        sa.select(sa.func.max(catalog.versions.c.version)).where(base)
                    ).scalar_one()
                    or 0
                ) + 1
                if version > 1_000_000:
                    raise AgentFailure("VERSION_LIMIT", "Dataset version quota reached")
                row_count = sum(len(t.rows) for t in data.tables)
                conn.execute(
                    catalog.versions.insert().values(
                        dataset_id=dataset_id,
                        version=version,
                        status="importing",
                        source_sha256=data.upload.sha256,
                        confirmation_sha256=confirmation.confirmation_sha256,
                        source_ref=source_ref,
                        source_filename=data.upload.filename,
                        file_format=data.upload.file_format,
                        parser_version=data.parser_version,
                        confirmation=confirmation.model_dump(mode="json"),
                        row_count=row_count,
                    )
                )
                for index, (raw, confirmed) in enumerate(
                    zip(data.tables, confirmation.tables, strict=True), 1
                ):
                    physical = f"u_{dataset_id.replace('-', '')}_v{version}_t{index}"
                    typed = [
                        [
                            convert_value(value, c.logical_type, c.date_format)
                            for value, c in zip(row, confirmed.columns, strict=True)
                        ]
                        for row in raw.rows
                    ]
                    types = [
                        column_type(c, [r[i] for r in typed])
                        for i, c in enumerate(confirmed.columns)
                    ]
                    table = sa.Table(
                        physical,
                        sa.MetaData(),
                        *[
                            sa.Column(
                                c.normalized_name,
                                kind,
                                primary_key=c.normalized_name in confirmed.primary_key,
                                autoincrement=False,
                                quote=True,
                            )
                            for c, kind in zip(confirmed.columns, types, strict=True)
                        ],
                        schema="uploads",
                        quote=True,
                    )
                    # Transactional PostgreSQL DDL, using only vetted identifiers/types.
                    table.create(conn)
                    names = [c.normalized_name for c in confirmed.columns]
                    self._write_rows(
                        conn, table, [dict(zip(names, row, strict=True)) for row in typed], deadline
                    )
                    conn.execute(
                        catalog.tables.insert().values(
                            dataset_id=dataset_id,
                            version=version,
                            table_id=raw.table_id,
                            source_name=raw.source_name,
                            physical_name=physical,
                            row_count=len(raw.rows),
                            primary_key=confirmed.primary_key,
                        )
                    )
                    conn.execute(
                        catalog.columns.insert(),
                        [
                            dict(
                                dataset_id=dataset_id,
                                version=version,
                                table_id=raw.table_id,
                                position=i,
                                source_column=c.source_column,
                                original_name=c.original_name,
                                normalized_name=c.normalized_name,
                                logical_type=c.logical_type,
                                sql_type=str(kind.compile(dialect=postgresql.dialect())),
                            )
                            for i, (c, kind) in enumerate(
                                zip(confirmed.columns, types, strict=True), 1
                            )
                        ],
                    )
                    with conn.connection.driver_connection.cursor() as cursor:
                        cursor.execute(
                            sql.SQL("GRANT SELECT ON {}.{} TO datapilot_upload_reader").format(
                                sql.Identifier("uploads"), sql.Identifier(physical)
                            )
                        )
                conn.execute(
                    catalog.versions.update()
                    .where(base, catalog.versions.c.version == version)
                    .values(status="ready")
                )
                conn.execute(
                    catalog.datasets.update()
                    .where(catalog.datasets.c.dataset_id == dataset_id)
                    .values(current_version=version)
                )
                result = ImportResult(
                    dataset_id=dataset_id,
                    version=version,
                    source_sha256=data.upload.sha256,
                    confirmation_sha256=confirmation.confirmation_sha256,
                    reused=False,
                    row_count=row_count,
                )
            return result
        except sa.exc.SQLAlchemyError as exc:
            # Retain the snapshot; do not put SQL, row values or credentials in the error.
            raise AgentFailure(
                "IMPORT_DATABASE_ERROR", "Import transaction rolled back; source snapshot retained"
            ) from exc

    def activate_version(self, binding: DatasetBinding) -> DatasetBinding:
        binding = DatasetBinding.model_validate_json(binding.model_dump_json())
        if binding.version is None:
            raise AgentFailure("VERSION_REQUIRED", "Activation requires an explicit ready version")
        try:
            with self.engine.begin() as conn:
                self._configure(conn)
                self._lock(conn, binding.dataset_id)
                exists = conn.execute(
                    sa.select(catalog.versions.c.version).where(
                        catalog.versions.c.dataset_id == binding.dataset_id,
                        catalog.versions.c.version == binding.version,
                        catalog.versions.c.status == "ready",
                    )
                ).scalar_one_or_none()
                if exists is None:
                    raise AgentFailure("DATASET_NOT_FOUND", "Ready dataset version does not exist")
                conn.execute(
                    catalog.datasets.update()
                    .where(catalog.datasets.c.dataset_id == binding.dataset_id)
                    .values(current_version=binding.version)
                )
            return binding
        except sa.exc.SQLAlchemyError as exc:
            raise AgentFailure("IMPORT_DATABASE_ERROR", "Version activation rolled back") from exc
