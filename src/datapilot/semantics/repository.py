"""MCP-only scoped semantic metadata and bounded raw-row verification snapshots."""

import json
import time

import sqlalchemy as sa

from datapilot.contracts import AgentFailure
from datapilot.datasets.repository import DatasetRepository
from datapilot.db.semantic_schema import evidence, verification_runs
from datapilot.ingestion.common import digest
from datapilot.semantics.contracts import (
    Evidence,
    MetricContext,
    MetricProof,
    MetricRequest,
    VerificationRecord,
)
from datapilot.semantics.recipes import build_context, missing, quote, request_missing
from datapilot.semantics.recompute import RecomputationUnavailable, compute_rows
from datapilot.semantics.registry import metric_record, semantic_record, stored_record
from datapilot.tools.sql import SQLPolicy

PROOF_MAX_BYTES = 8 * 1024**2


class MetricRepository:
    def __init__(self, datasets: DatasetRepository):
        self.datasets = datasets

    def context(self, request: MetricRequest) -> MetricContext:
        schema = self.datasets.schema(request.dataset_id)
        if schema.version != request.dataset_version:
            raise AgentFailure("DATASET_NOT_AUTHORIZED", "Request version is outside bound scope")
        try:
            with self.datasets.sql.engine.connect() as conn, conn.begin():
                self.datasets.sql._configure(conn)
                semantic = semantic_record(
                    conn, schema.dataset_id, schema.version, request.semantic_version
                )
                metric = metric_record(
                    conn,
                    schema.dataset_id,
                    schema.version,
                    request.metric_id,
                    request.metric_version,
                )
                return build_context(schema, semantic, metric)
        except sa.exc.SQLAlchemyError as exc:
            raise AgentFailure("REGISTRY_ERROR", "Cannot read confirmed metric metadata") from exc

    def proof(self, request: MetricRequest) -> MetricProof:
        context = self.context(request)
        problems = request_missing(context, request)
        rows, hashes = [], []
        raw_bytes = 0
        if not problems:
            expected = context.table.row_count
            size = self.datasets.sql.max_rows
            if expected > 20_000 or expected // size + 1 > 256:
                problems = [
                    missing("proof_quota", "独立复算超过 20000 行或 256 页上限；不能声明已验证")
                ]
            else:
                policy = SQLPolicy("uploads", frozenset({context.table.physical_name}))
                fields = context.entity.fields
                projection = ",".join(
                    quote(column) + " AS " + quote(role) for role, column in fields.items()
                )
                base = (
                    f"SELECT {projection} FROM uploads.{quote(context.table.physical_name)} "
                    f"ORDER BY {quote(fields['record_id'])}"
                )
                deadline = time.monotonic() + 5
                try:
                    # One immutable PostgreSQL snapshot for all raw projection pages.
                    with (
                        self.datasets.sql.engine.connect().execution_options(
                            isolation_level="REPEATABLE READ"
                        ) as conn,
                        conn.begin(),
                    ):
                        self.datasets.sql._configure(conn, policy)
                        for offset in range(0, expected + 1, size):
                            if time.monotonic() > deadline:
                                raise ValueError("Independent recomputation exceeded five seconds")
                            page = self.datasets.sql.read_page(
                                conn, base + f" LIMIT {size} OFFSET {offset}", policy
                            )
                            if page.truncated:
                                raise ValueError("Raw projection was truncated")
                            raw_bytes += len(
                                json.dumps(page.model_dump(mode="json"), ensure_ascii=False).encode(
                                    "utf-8"
                                )
                            )
                            if raw_bytes > PROOF_MAX_BYTES:
                                raise ValueError("Independent raw projection exceeded eight MiB")
                            hashes.append(
                                digest(page.model_dump(mode="json", exclude={"elapsed_ms"}))
                            )
                            rows.extend(
                                dict(zip(page.columns, row, strict=True)) for row in page.rows
                            )
                            if len(rows) > expected:
                                raise ValueError("Source row count differs from version metadata")
                            if page.row_count < size:
                                break
                        if len(rows) != expected:
                            raise ValueError("Incomplete raw projection")
                    value = compute_rows(context, request, rows)
                    return MetricProof(
                        context_sha256=context.context_sha256,
                        request_sha256=digest(request),
                        status="computed",
                        value=value,
                        source_rows=len(rows),
                        page_hashes=hashes,
                    )
                except RecomputationUnavailable as exc:
                    problems = [exc.reason]
                except (ValueError, ArithmeticError) as exc:
                    problems = [missing("data_not_verifiable", str(exc)[:256])]
                except (AgentFailure, sa.exc.SQLAlchemyError):
                    problems = [
                        missing("proof_query_failed", "独立复算查询失败或超时；未生成可验证数值")
                    ]
        return MetricProof(
            context_sha256=context.context_sha256,
            request_sha256=digest(request),
            status="unavailable",
            missing=problems,
            source_rows=min(len(rows), 20_000),
            page_hashes=hashes,
        )

    def evidence(self, dataset_id: str, evidence_id: str) -> Evidence:
        schema = self.datasets.schema(dataset_id)
        with self.datasets.sql.engine.connect() as conn, conn.begin():
            self.datasets.sql._configure(conn)
            # Filter source identity before loading body; an Evidence ID is not authorization.
            found = conn.execute(
                sa.select(evidence.c.evidence_id).where(
                    evidence.c.evidence_id == evidence_id,
                    evidence.c.dataset_id == dataset_id,
                    evidence.c.dataset_version == schema.version,
                )
            ).scalar_one_or_none()
            if found is None:
                raise AgentFailure(
                    "REFERENCE_NOT_FOUND", "Evidence is outside the bound source version"
                )
            return stored_record(conn, evidence, "evidence_id", evidence_id, Evidence)

    def verification(self, dataset_id: str, verification_id: str) -> VerificationRecord:
        schema = self.datasets.schema(dataset_id)
        with self.datasets.sql.engine.connect() as conn, conn.begin():
            self.datasets.sql._configure(conn)
            found = conn.execute(
                sa.select(verification_runs.c.verification_id).where(
                    verification_runs.c.verification_id == verification_id,
                    verification_runs.c.dataset_id == dataset_id,
                    verification_runs.c.dataset_version == schema.version,
                )
            ).scalar_one_or_none()
            if found is None:
                raise AgentFailure("DATASET_NOT_AUTHORIZED", "Verification is outside bound scope")
            return stored_record(
                conn,
                verification_runs,
                "verification_id",
                verification_id,
                VerificationRecord,
            )
