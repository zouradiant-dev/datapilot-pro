"""Shared resource counters and deterministic serialization; no side-effecting tools."""

import hashlib
import json
import time
from pathlib import Path

from pydantic import BaseModel

from datapilot.ingestion.contracts import ParseFailure, ParseLimits


def digest(value: BaseModel | dict | list) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    body = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def render_json(value: BaseModel, max_bytes: int) -> str:
    result = value.model_dump_json(indent=2)
    if len(result.encode("utf-8")) > max_bytes:
        raise ParseFailure(
            "PREVIEW_SIZE_LIMIT", "Preview/confirmation exceeds the output byte limit"
        )
    return result


def read_file(path: Path, max_bytes: int) -> bytes:
    try:
        if not path.is_file():
            raise ParseFailure("FILE_INVALID", "A regular local file is required")
        if path.stat().st_size > max_bytes:
            raise ParseFailure("FILE_SIZE_LIMIT", "File exceeds the configured byte limit")
        with path.open("rb") as stream:
            data = stream.read(max_bytes + 1)
    except OSError as exc:
        raise ParseFailure("FILE_UNREADABLE", "Cannot read the selected local file") from exc
    if len(data) > max_bytes:
        raise ParseFailure("FILE_SIZE_LIMIT", "File exceeds the configured byte limit")
    return data


class Guard:
    """Cooperative deadline plus hard counters; not an OS process sandbox."""

    def __init__(self, limits: ParseLimits):
        self.limits = limits
        self.deadline = time.monotonic() + limits.max_seconds
        self.rows = self.cells = self.text_bytes = 0

    def check(self) -> None:
        if time.monotonic() > self.deadline:
            raise ParseFailure("PARSE_TIMEOUT", "File processing exceeded its cooperative deadline")

    def row(self, values: list[str | None]) -> None:
        self.check()
        self.rows += 1
        self.cells += len(values)
        if self.rows > self.limits.max_total_rows + self.limits.max_sheets:
            raise ParseFailure("ROW_LIMIT", "Scanned rows exceed the configured limit")
        if len(values) > self.limits.max_columns:
            raise ParseFailure("COLUMN_LIMIT", "Column count exceeds the configured limit")
        if self.cells > self.limits.max_cells:
            raise ParseFailure("CELL_COUNT_LIMIT", "Scanned cells exceed the configured limit")
        for cell in values:
            if cell is not None:
                if len(cell) > self.limits.max_cell_chars:
                    raise ParseFailure("CELL_SIZE_LIMIT", "A cell exceeds the character limit")
                self.text_bytes += len(cell.encode("utf-8"))
        if self.text_bytes > self.limits.max_parsed_bytes:
            raise ParseFailure("PARSED_SIZE_LIMIT", "Decoded cell content exceeds the byte limit")
