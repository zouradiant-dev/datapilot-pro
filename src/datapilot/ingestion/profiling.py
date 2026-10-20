"""Full-data quality checks with sampled suggestions and conservative schema proposals."""

import unicodedata
from decimal import Decimal, localcontext

from datapilot.ingestion.common import Guard, digest, render_json
from datapilot.ingestion.contracts import (
    ColumnProfile,
    Issue,
    ParsedColumn,
    ParsedDataset,
    ParsedTable,
    RelationCandidate,
    SchemaProposal,
    TablePreview,
)
from datapilot.ingestion.types import convert_value, infer


def _outliers(values: list[Decimal]) -> int:
    if len(values) < 4:
        return 0
    ordered = sorted(values)

    def quartile(numerator: int) -> Decimal:
        index, remainder = divmod((len(values) - 1) * numerator, 4)
        return (
            ordered[index]
            if not remainder
            else (ordered[index] + (ordered[index + 1] - ordered[index]) * Decimal(remainder) / 4)
        )

    with localcontext() as context:
        context.prec = 80
        q1, q3 = quartile(1), quartile(3)
        spread = (q3 - q1) * Decimal("1.5")
        return sum(v < q1 - spread or v > q3 + spread for v in values)


def _profile(
    table: ParsedTable, column: ParsedColumn, dataset: ParsedDataset, guard: Guard
) -> ColumnProfile:
    values = [r[column.position - 1] for r in table.rows]
    present = [v for v in values if v not in (None, "")]
    guard.check()
    sample_kind = infer(present[: dataset.limits.sample_size])[0]
    kind, codes, precision, scale = infer(present)
    if column.normalized_name in table.forced_text_columns:
        kind, codes, precision, scale = "TEXT", ["SOURCE_CELL_REQUIRES_TEXT"], None, None
    if kind != sample_kind:
        codes.append("SAMPLE_TYPE_MISMATCH")
    examples = list(dict.fromkeys(present))[:5]
    examples_truncated = any(len(v) > 200 for v in examples)
    minimum = maximum = None
    outlier_count = 0
    if present and kind in {"INTEGER", "NUMERIC"}:
        numbers = [Decimal(v) for v in present]
        minimum, maximum = str(min(numbers)), str(max(numbers))
        outlier_count = _outliers(numbers)
        if outlier_count:
            codes.append("IQR_OUTLIERS")
    elif present and kind == "DATE":
        minimum, maximum = min(present), max(present)
    guard.check()
    return ColumnProfile(
        column=column,
        suggested_type=kind,
        sample_type=sample_kind,
        confidence=0.0 if not present else 0.5 if kind == "TEXT" else 1.0,
        requires_confirmation=bool(codes) or kind == "TEXT",
        null_count=len(values) - len(present),
        distinct_count=len(set(present)),
        duplicate_count=len(present) - len(set(present)),
        examples=[v[:200] for v in examples],
        examples_truncated=examples_truncated,
        precision=precision,
        scale=scale,
        minimum=minimum,
        maximum=maximum,
        outlier_count=outlier_count,
        issues=[
            Issue(
                code=code,
                message="Full-column check requires review; no source rows changed",
                column=column.normalized_name,
            )
            for code in codes
        ],
    )


def _name_key(column: ParsedColumn) -> str:
    return "".join(
        c
        for c in unicodedata.normalize(
            "NFKC", column.original_name or column.normalized_name
        ).casefold()
        if c.isalnum()
    )


def propose_schema(dataset: ParsedDataset) -> SchemaProposal:
    guard = Guard(dataset.limits)
    tables = []
    column_values = {}
    for table in dataset.tables:
        profiles = [_profile(table, col, dataset, guard) for col in table.columns]
        candidates = []
        for profile in profiles:
            col, kind = profile.column, profile.suggested_type
            if kind not in {"TEXT", "INTEGER"} or col.normalized_name in table.forced_text_columns:
                continue
            values = {convert_value(r[col.position - 1], kind) for r in table.rows}
            column_values[(table.table_id, col.normalized_name)] = values - {None}
            if table.rows and profile.null_count == 0 and len(values) == len(table.rows):
                candidates.append(col.normalized_name)
        candidates.sort(
            key=lambda name: (
                not (
                    "id" in name
                    or "编号"
                    in next(
                        c.original_name or "" for c in table.columns if c.normalized_name == name
                    )
                ),
                name,
            )
        )
        issues = list(table.issues)
        if len(candidates) > 10:
            issues.append(
                Issue(code="KEY_CANDIDATES_TRUNCATED", message="Only first 10 candidate keys shown")
            )
        preview = [r[:] for r in table.rows[: dataset.limits.preview_rows]]
        # Preview clipping is explicit; full raw values remain in ParsedDataset.
        clipped = any(v is not None and len(v) > 200 for row in preview for v in row)
        preview = [[v[:200] if v is not None else None for v in row] for row in preview]
        if clipped:
            issues.append(
                Issue(
                    code="PREVIEW_CELLS_CLIPPED", message="Preview cells clipped to 200 characters"
                )
            )
        tables.append(
            TablePreview(
                table_id=table.table_id,
                source_name=table.source_name,
                row_count=len(table.rows),
                header_row=table.header_row,
                preview_source_rows=table.source_rows[: len(preview)],
                columns=profiles,
                preview_rows=preview,
                preview_truncated=len(preview) < len(table.rows) or clipped,
                duplicate_rows=len(table.rows) - len({tuple(row) for row in table.rows}),
                skipped_blank_rows=table.skipped_blank_rows,
                candidate_primary_keys=candidates[:10],
                issues=issues,
            )
        )
    relations = []
    for parent in tables:
        for pcol in parent.columns:
            if pcol.column.normalized_name not in parent.candidate_primary_keys:
                continue
            parent_values = column_values[(parent.table_id, pcol.column.normalized_name)]
            for child in tables:
                if child.table_id == parent.table_id:
                    continue
                for ccol in child.columns:
                    guard.check()
                    if ccol.suggested_type != pcol.suggested_type or _name_key(
                        ccol.column
                    ) != _name_key(pcol.column):
                        continue
                    values = column_values.get((child.table_id, ccol.column.normalized_name), set())
                    if not values or not values <= parent_values:
                        continue
                    relation_key = [
                        child.table_id,
                        ccol.column.normalized_name,
                        parent.table_id,
                        pcol.column.normalized_name,
                    ]
                    relations.append(
                        RelationCandidate(
                            relation_id="relation_" + digest(relation_key)[:24],
                            child_table=child.table_id,
                            child_column=ccol.column.normalized_name,
                            parent_table=parent.table_id,
                            parent_column=pcol.column.normalized_name,
                            matched_distinct_values=len(values),
                        )
                    )
                    if len(relations) > 50:
                        break
                if len(relations) > 50:
                    break
            if len(relations) > 50:
                break
        if len(relations) > 50:
            break
    body = {
        "upload": dataset.upload,
        "parser_version": dataset.parser_version,
        "options": dataset.options,
        "limits": dataset.limits,
        "parsed_content_sha256": digest(dataset),
        "proposal_sha256": "0" * 64,
        "tables": tables,
        "candidate_relations": relations[:50],
        "relation_candidates_truncated": len(relations) > 50,
    }
    proposal = SchemaProposal(**body)
    payload = proposal.model_dump(mode="json", exclude={"proposal_sha256"})
    proposal.proposal_sha256 = digest(payload)
    render_json(proposal, dataset.limits.max_preview_bytes)
    guard.check()
    return proposal
