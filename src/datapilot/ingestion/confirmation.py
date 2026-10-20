"""Validate reviewed mappings against a fresh full-file parse, never trust preview samples."""

from pathlib import Path

from datapilot.ingestion.common import Guard, digest, render_json
from datapilot.ingestion.contracts import (
    ConfirmationOverrides,
    ConfirmedColumn,
    ConfirmedTable,
    ParsedDataset,
    ParseFailure,
    SchemaConfirmation,
    SchemaProposal,
)
from datapilot.ingestion.parser import RESERVED, parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.types import convert_value, numeric_shape


def confirm_schema(
    dataset: ParsedDataset,
    proposal: SchemaProposal,
    *,
    reviewed: bool,
    overrides: ConfirmationOverrides | None = None,
) -> SchemaConfirmation:
    if reviewed is not True:
        raise ParseFailure(
            "REVIEW_REQUIRED", "Explicit review is required before confirming a schema"
        )
    expected = propose_schema(dataset)
    if expected != proposal:
        raise ParseFailure(
            "PROPOSAL_STALE", "Source, parser settings or proposal changed; preview again"
        )
    if any(i.code == "HEADER_AMBIGUOUS" for t in proposal.tables for i in t.issues):
        raise ParseFailure(
            "HEADER_CONFIRMATION_REQUIRED", "Reparse with explicit present/absent header settings"
        )
    overrides = overrides or ConfirmationOverrides()
    guard = Guard(dataset.limits)
    known = {(t.table_id, c.column.normalized_name) for t in proposal.tables for c in t.columns}
    by_column = {}
    for override in overrides.columns:
        key = (override.table_id, override.column)
        if key not in known or key in by_column:
            raise ParseFailure(
                "OVERRIDE_INVALID", "Override references an unknown or repeated column"
            )
        by_column[key] = override
    table_ids = {t.table_id for t in dataset.tables}
    if not set(overrides.primary_keys) <= table_ids:
        raise ParseFailure("KEY_INVALID", "Primary key references an unknown table")
    confirmed = []
    typed = {}
    types = {}
    for table, preview in zip(dataset.tables, proposal.tables, strict=True):
        if not table.columns or not table.rows:
            raise ParseFailure(
                "EMPTY_TABLE_CONFIRMATION", "Select a table with columns and data before confirming"
            )
        columns = []
        typed_columns = {}
        name_map = {}
        for profile in preview.columns:
            guard.check()
            source = profile.column.normalized_name
            override = by_column.get((table.table_id, source))
            kind = (
                override.logical_type
                if override and override.logical_type
                else profile.suggested_type
            )
            target = override.normalized_name if override and override.normalized_name else source
            date_format = override.date_format if override else None
            if (
                target in RESERVED
                or target in name_map.values()
                or (date_format and kind != "DATE")
            ):
                raise ParseFailure(
                    "OVERRIDE_INVALID", "Duplicate/reserved name or inapplicable date format"
                )
            name_map[source] = target
            try:
                values = []
                for i, row in enumerate(table.rows):
                    if i % 256 == 0:
                        guard.check()
                    values.append(
                        convert_value(row[profile.column.position - 1], kind, date_format)
                    )
                precision = scale = None
                if kind == "NUMERIC":
                    precision, scale = numeric_shape([v for v in values if v is not None])
            except ValueError as exc:
                raise ParseFailure(
                    "OVERRIDE_DATA_INVALID",
                    "Selected type/format fails full-column validation",
                    table_id=table.table_id,
                    column=profile.column.position,
                ) from exc
            typed_columns[source] = values
            typed[(table.table_id, source)] = values
            types[(table.table_id, source)] = kind
            columns.append(
                ConfirmedColumn(
                    original_name=profile.column.original_name,
                    source_column=source,
                    normalized_name=target,
                    logical_type=kind,
                    date_format=(date_format or "YYYY-MM-DD") if kind == "DATE" else None,
                    precision=precision,
                    scale=scale,
                )
            )
        key = overrides.primary_keys.get(table.table_id, [])
        if len(key) != len(set(key)) or any(c not in typed_columns for c in key):
            raise ParseFailure("KEY_INVALID", "Primary key contains repeated or unknown columns")
        if key:
            records = list(zip(*(typed_columns[c] for c in key), strict=True))
            if not records or any(None in r for r in records) or len(set(records)) != len(records):
                raise ParseFailure(
                    "KEY_INVALID", "Confirmed key must be non-null and unique on all rows"
                )
        confirmed.append(
            ConfirmedTable(
                table_id=table.table_id, columns=columns, primary_key=[name_map[c] for c in key]
            )
        )
    candidates = {r.relation_id: r for r in proposal.candidate_relations}
    if len(set(overrides.relation_ids)) != len(overrides.relation_ids) or any(
        r not in candidates for r in overrides.relation_ids
    ):
        raise ParseFailure(
            "RELATION_INVALID", "Relation selection must reference unique existing candidates"
        )
    for relation_id in overrides.relation_ids:
        relation = candidates[relation_id]
        child = (relation.child_table, relation.child_column)
        parent = (relation.parent_table, relation.parent_column)
        parent_values, child_values = typed[parent], typed[child]
        if (
            types[child] != types[parent]
            or None in parent_values
            or len(set(parent_values)) != len(parent_values)
            or not set(child_values) - {None} <= set(parent_values)
        ):
            raise ParseFailure(
                "RELATION_INVALID", "Selected relation fails validation after type overrides"
            )
    result = SchemaConfirmation(
        source_sha256=dataset.upload.sha256,
        parsed_content_sha256=proposal.parsed_content_sha256,
        proposal_sha256=proposal.proposal_sha256,
        options=dataset.options,
        limits=dataset.limits,
        reviewed=True,
        tables=confirmed,
        accepted_relations=[candidates[r] for r in overrides.relation_ids],
        confirmation_sha256="0" * 64,
    )
    result.confirmation_sha256 = digest(
        result.model_dump(mode="json", exclude={"confirmation_sha256"})
    )
    render_json(result, dataset.limits.max_preview_bytes)
    return result


def confirm_file(
    path: str | Path,
    proposal: SchemaProposal,
    *,
    reviewed: bool,
    overrides: ConfirmationOverrides | None = None,
) -> SchemaConfirmation:
    fresh = parse_file(path, options=proposal.options, limits=proposal.limits)
    return confirm_schema(fresh, proposal, reviewed=reviewed, overrides=overrides)
