"""Trusted metadata-only registry operations. Never exposed as model write tools."""

import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetColumn, DatasetSchema, DatasetTable
from datapilot.db import catalog
from datapilot.db.semantic_schema import (
    evidence,
    metric_versions,
    semantic_versions,
    verification_runs,
)
from datapilot.ingestion.common import digest
from datapilot.semantics.contracts import (
    Evidence,
    MetricDraft,
    MetricVersion,
    SemanticDraft,
    SemanticVersion,
    VerificationRecord,
)


def decode(model, value):
    return model.model_validate_json(json.dumps(value, allow_nan=False))


def load_schema(conn, dataset_id: str, version: int) -> DatasetSchema:
    ds = (
        conn.execute(sa.select(catalog.datasets).where(catalog.datasets.c.dataset_id == dataset_id))
        .mappings()
        .one_or_none()
    )
    row = (
        conn.execute(
            sa.select(catalog.versions).where(
                catalog.versions.c.dataset_id == dataset_id,
                catalog.versions.c.version == version,
                catalog.versions.c.status == "ready",
            )
        )
        .mappings()
        .one_or_none()
    )
    if ds is None or row is None:
        raise AgentFailure("DATASET_NOT_FOUND", "Select an existing ready dataset version")
    source_tables = (
        conn.execute(
            sa.select(catalog.tables)
            .where(
                catalog.tables.c.dataset_id == dataset_id,
                catalog.tables.c.version == version,
            )
            .order_by(catalog.tables.c.table_id)
            .limit(33)
        )
        .mappings()
        .all()
    )
    tables = []
    for table in source_tables:
        columns = (
            conn.execute(
                sa.select(catalog.columns)
                .where(
                    catalog.columns.c.dataset_id == dataset_id,
                    catalog.columns.c.version == version,
                    catalog.columns.c.table_id == table["table_id"],
                )
                .order_by(catalog.columns.c.position)
                .limit(101)
            )
            .mappings()
            .all()
        )
        tables.append(
            DatasetTable(
                table_id=table["table_id"],
                source_name=table["source_name"],
                physical_name=table["physical_name"],
                row_count=table["row_count"],
                primary_key=table["primary_key"],
                columns=[
                    DatasetColumn(**{k: c[k] for k in DatasetColumn.model_fields}) for c in columns
                ],
            )
        )
    return DatasetSchema(
        dataset_id=dataset_id,
        name=ds["name"],
        version=version,
        source_sha256=row["source_sha256"],
        row_count=row["row_count"],
        tables=tables,
    )


def semantic_record(conn, dataset_id: str, dataset_version: int, version: int) -> SemanticVersion:
    row = (
        conn.execute(
            sa.select(semantic_versions).where(
                semantic_versions.c.dataset_id == dataset_id,
                semantic_versions.c.dataset_version == dataset_version,
                semantic_versions.c.semantic_version == version,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise AgentFailure(
            "SEMANTIC_NOT_CONFIRMED", "No confirmed semantic mapping for this dataset version"
        )
    definition = decode(SemanticDraft, row["definition"])
    if digest(definition) != row["definition_sha256"] or (
        definition.dataset_id,
        definition.dataset_version,
    ) != (dataset_id, dataset_version):
        raise AgentFailure(
            "REGISTRY_INTEGRITY", "Semantic definition failed its identity/hash check"
        )
    return SemanticVersion(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        semantic_version=version,
        source_sha256=row["source_sha256"],
        definition_sha256=row["definition_sha256"],
        definition=definition,
    )


def metric_record(
    conn, dataset_id: str, dataset_version: int, metric_id: str, version: int
) -> MetricVersion:
    row = (
        conn.execute(
            sa.select(metric_versions).where(
                metric_versions.c.dataset_id == dataset_id,
                metric_versions.c.dataset_version == dataset_version,
                metric_versions.c.metric_id == metric_id,
                metric_versions.c.metric_version == version,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise AgentFailure(
            "METRIC_NOT_CONFIRMED", "No confirmed metric definition for this dataset version"
        )
    definition = decode(MetricDraft, row["definition"])
    identity = (
        definition.dataset_id,
        definition.dataset_version,
        definition.metric_id,
        definition.semantic_version,
    )
    if digest(definition) != row["definition_sha256"] or identity != (
        dataset_id,
        dataset_version,
        metric_id,
        row["semantic_version"],
    ):
        raise AgentFailure("REGISTRY_INTEGRITY", "Metric definition failed its identity/hash check")
    return MetricVersion(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        metric_id=metric_id,
        metric_version=version,
        semantic_version=row["semantic_version"],
        semantic_sha256=row["semantic_sha256"],
        definition_sha256=row["definition_sha256"],
        definition=definition,
    )


def stored_record(conn, table, key_name: str, key: str, model):
    row = conn.execute(sa.select(table).where(table.c[key_name] == key)).mappings().one_or_none()
    if row is None:
        raise AgentFailure(
            "REFERENCE_NOT_FOUND", "Evidence or verification reference does not exist"
        )
    value = decode(model, row["body"])
    if digest(value) != row["body_sha256"] or getattr(value, key_name) != key:
        raise AgentFailure("REGISTRY_INTEGRITY", "Registry record failed its identity/hash check")
    if (value.dataset_id, value.dataset_version) != (row["dataset_id"], row["dataset_version"]):
        raise AgentFailure("REGISTRY_INTEGRITY", "Registry record has a mismatched source version")
    return value


def verify_registry_role(conn) -> None:
    row = conn.exec_driver_sql(
        "SELECT current_user,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,"
        "EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid) "
        "FROM pg_roles r WHERE rolname=current_user"
    ).one()
    unsafe = conn.exec_driver_sql(
        "SELECT has_database_privilege(current_user,current_database(),'CREATE,TEMP') OR "
        "EXISTS(SELECT 1 FROM pg_namespace WHERE left(nspname,3)<>'pg_' AND "
        "has_schema_privilege(current_user,oid,'CREATE')) OR "
        "has_schema_privilege(current_user,'uploads','USAGE') OR "
        "has_schema_privilege(current_user,'saas','USAGE') OR "
        "has_schema_privilege(current_user,'rag','USAGE')"
    ).scalar_one()
    if row[0] != "datapilot_registry" or any(row[1:]) or unsafe:
        raise AgentFailure("ROLE_UNSAFE", "Registry requires an isolated metadata-only identity")
    for table in (semantic_versions, metric_versions, evidence, verification_runs):
        if conn.execute(
            sa.text("SELECT has_table_privilege(current_user,:t,'UPDATE,DELETE,TRUNCATE,TRIGGER')"),
            {"t": "catalog." + table.name},
        ).scalar_one():
            raise AgentFailure("ROLE_UNSAFE", "Registry history must be append-only")


class RegistryStore:
    def __init__(self, url: str):
        parsed = make_url(url)
        if parsed.drivername != "postgresql+psycopg" or parsed.username != "datapilot_registry":
            raise ValueError("Use the metadata-only registry identity")
        self.engine = sa.create_engine(
            url, hide_parameters=True, connect_args={"connect_timeout": 5}
        )

    def close(self) -> None:
        self.engine.dispose()

    def _configure(self, conn) -> None:
        conn.exec_driver_sql("SET LOCAL statement_timeout='5s'")
        conn.exec_driver_sql("SET LOCAL lock_timeout='2s'")
        conn.exec_driver_sql("SET LOCAL search_path=pg_catalog")
        verify_registry_role(conn)

    def _lock(self, conn, identity: str) -> None:
        key = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big", signed=True)
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})

    def confirm_semantics(self, draft: SemanticDraft, *, reviewed: bool) -> SemanticVersion:
        if reviewed is not True:
            raise AgentFailure(
                "REVIEW_REQUIRED", "A user must explicitly review the semantic mapping"
            )
        draft = decode(SemanticDraft, draft.model_dump(mode="json"))
        try:
            with self.engine.begin() as conn:
                self._configure(conn)
                self._lock(conn, f"semantic:{draft.dataset_id}:{draft.dataset_version}")
                schema = load_schema(conn, draft.dataset_id, draft.dataset_version)
                by_table = {t.table_id: t for t in schema.tables}
                for mapping in draft.entities:
                    table = by_table.get(mapping.table_id)
                    names = {c.normalized_name for c in table.columns} if table else set()
                    if not (set(mapping.fields.values()) | set(mapping.grain)) <= names:
                        raise AgentFailure(
                            "MAPPING_INVALID", "Mapping/grain references an unknown physical column"
                        )
                base = (
                    semantic_versions.c.dataset_id == draft.dataset_id,
                    semantic_versions.c.dataset_version == draft.dataset_version,
                )
                sha = digest(draft)
                existing = conn.execute(
                    sa.select(semantic_versions.c.semantic_version).where(
                        *base, semantic_versions.c.definition_sha256 == sha
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return semantic_record(conn, draft.dataset_id, draft.dataset_version, existing)
                version = (
                    conn.execute(
                        sa.select(sa.func.max(semantic_versions.c.semantic_version)).where(*base)
                    ).scalar_one()
                    or 0
                ) + 1
                if version > 1_000_000:
                    raise AgentFailure("VERSION_LIMIT", "Semantic version quota reached")
                conn.execute(
                    semantic_versions.insert().values(
                        dataset_id=draft.dataset_id,
                        dataset_version=draft.dataset_version,
                        semantic_version=version,
                        source_sha256=schema.source_sha256,
                        definition_sha256=sha,
                        definition=draft.model_dump(mode="json"),
                        confirmed_by="local-user",
                    )
                )
                return semantic_record(conn, draft.dataset_id, draft.dataset_version, version)
        except sa.exc.SQLAlchemyError as exc:
            raise AgentFailure(
                "REGISTRY_ERROR", "Semantic confirmation transaction rolled back"
            ) from exc

    def confirm_metric(self, draft: MetricDraft, *, reviewed: bool) -> MetricVersion:
        if reviewed is not True:
            raise AgentFailure("REVIEW_REQUIRED", "A user must explicitly review the metric policy")
        draft = decode(MetricDraft, draft.model_dump(mode="json"))
        try:
            with self.engine.begin() as conn:
                self._configure(conn)
                self._lock(
                    conn, f"metric:{draft.dataset_id}:{draft.dataset_version}:{draft.metric_id}"
                )
                semantic = semantic_record(
                    conn, draft.dataset_id, draft.dataset_version, draft.semantic_version
                )
                base = (
                    metric_versions.c.dataset_id == draft.dataset_id,
                    metric_versions.c.dataset_version == draft.dataset_version,
                    metric_versions.c.metric_id == draft.metric_id,
                )
                sha = digest(draft)
                existing = conn.execute(
                    sa.select(metric_versions.c.metric_version).where(
                        *base, metric_versions.c.definition_sha256 == sha
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return metric_record(
                        conn, draft.dataset_id, draft.dataset_version, draft.metric_id, existing
                    )
                version = (
                    conn.execute(
                        sa.select(sa.func.max(metric_versions.c.metric_version)).where(*base)
                    ).scalar_one()
                    or 0
                ) + 1
                if version > 1_000_000:
                    raise AgentFailure("VERSION_LIMIT", "Metric version quota reached")
                conn.execute(
                    metric_versions.insert().values(
                        dataset_id=draft.dataset_id,
                        dataset_version=draft.dataset_version,
                        metric_id=draft.metric_id,
                        metric_version=version,
                        semantic_version=draft.semantic_version,
                        semantic_sha256=semantic.definition_sha256,
                        definition_sha256=sha,
                        definition=draft.model_dump(mode="json"),
                        confirmed_by="local-user",
                    )
                )
                return metric_record(
                    conn, draft.dataset_id, draft.dataset_version, draft.metric_id, version
                )
        except sa.exc.SQLAlchemyError as exc:
            raise AgentFailure(
                "REGISTRY_ERROR", "Metric confirmation transaction rolled back"
            ) from exc

    def _append(self, table, key_name, value, **columns) -> None:
        body = value.model_dump(mode="json")
        if len(json.dumps(body, ensure_ascii=False).encode()) > 2 * 1024**2:
            raise AgentFailure("REGISTRY_SIZE_LIMIT", "Evidence/verification record is too large")
        try:
            with self.engine.begin() as conn:
                self._configure(conn)
                key = getattr(value, key_name)
                self._lock(conn, key)
                existing = conn.execute(
                    sa.select(table.c.body_sha256).where(table.c[key_name] == key)
                ).scalar_one_or_none()
                if existing:
                    if existing != digest(value):
                        raise AgentFailure(
                            "REGISTRY_CONFLICT",
                            "An immutable registry ID already has different content",
                        )
                    return
                conn.execute(
                    table.insert().values(
                        **{key_name: key},
                        dataset_id=value.dataset_id,
                        dataset_version=value.dataset_version,
                        body=body,
                        body_sha256=digest(value),
                        **columns,
                    )
                )
        except sa.exc.SQLAlchemyError as exc:
            raise AgentFailure("REGISTRY_ERROR", "Registry append transaction rolled back") from exc

    def append_evidence(self, value: Evidence) -> None:
        value = decode(Evidence, value.model_dump(mode="json"))
        self._append(
            evidence,
            "evidence_id",
            value,
            metric_id=value.metric_id,
            metric_version=value.metric_version,
            semantic_version=value.semantic_version,
        )

    def append_verification(self, value: VerificationRecord) -> None:
        value = decode(VerificationRecord, value.model_dump(mode="json"))
        self._append(
            verification_runs,
            "verification_id",
            value,
            evidence_id=value.evidence_id,
            verdict=value.verdict,
        )

    def get_evidence(self, evidence_id: str) -> Evidence:
        with self.engine.begin() as conn:
            self._configure(conn)
            return stored_record(conn, evidence, "evidence_id", evidence_id, Evidence)

    def get_verification(self, verification_id: str) -> VerificationRecord:
        with self.engine.begin() as conn:
            self._configure(conn)
            return stored_record(
                conn, verification_runs, "verification_id", verification_id, VerificationRecord
            )
