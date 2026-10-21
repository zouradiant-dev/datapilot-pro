"""Bounded UTF-8 plain text snapshots with exact Unicode/line spans. No markup execution."""

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.rag.contracts import Chunker, ChunkSpan, Limits, SourceInfo


@dataclass(frozen=True)
class ParsedSource:
    info: SourceInfo
    raw: bytes
    text: str


def decode(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise AgentFailure("DOCUMENT_FORMAT", "Only explicit UTF-8 text is supported") from exc
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        raise AgentFailure("DOCUMENT_FORMAT", "Binary/control content is not text")
    return text


def parse_sources(
    paths: list[Path], corpus_id: str, chunker: Chunker, limits: Limits
) -> list[ParsedSource]:
    if not 1 <= len(paths) <= limits.files:
        raise AgentFailure("DOCUMENT_LIMIT", "Explicit source file count exceeds quota")
    started, total, count, names, parsed = time.monotonic(), 0, 0, set(), []
    for path in paths:
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix.lower() not in {".md", ".txt"}
            or not re.fullmatch(r"[\w .-]{1,128}", path.name)
            or path.name in names
        ):
            raise AgentFailure("DOCUMENT_FORMAT", "Use distinct regular TXT/Markdown files")
        names.add(path.name)
        with path.open("rb") as stream:
            raw = stream.read(limits.file_bytes + 1)
        total += len(raw)
        if len(raw) > limits.file_bytes or total > limits.total_bytes:
            raise AgentFailure("DOCUMENT_LIMIT", "Source bytes exceed quota")
        text = decode(raw)
        version = hashlib.sha256(raw).hexdigest()
        source_id = digest({"corpus": corpus_id, "name": path.name})
        document_id = digest({"source_id": source_id, "version": version})
        spans = []
        for start in range(0, len(text), chunker.chars - chunker.overlap):
            end = min(start + chunker.chars, len(text))
            fragment = text[start:end]
            if not fragment.strip():
                continue
            sha = hashlib.sha256(fragment.encode()).hexdigest()
            spans.append(
                ChunkSpan(
                    chunk_id=digest(
                        {
                            "document": document_id,
                            "start": start,
                            "end": end,
                            "chunker": chunker.model_dump(mode="json"),
                            "sha256": sha,
                        }
                    ),
                    start=start,
                    end=end,
                    line_start=1 + text.count("\n", 0, start),
                    line_end=1 + text.count("\n", 0, end - 1),
                    sha256=sha,
                )
            )
            count += 1
            if count > limits.chunks or time.monotonic() - started > limits.parse_seconds:
                raise AgentFailure("DOCUMENT_LIMIT", "Chunk count or parse time exceeds quota")
            if end == len(text):
                break
        parsed.append(
            ParsedSource(
                SourceInfo(
                    source_id=source_id,
                    document_id=document_id,
                    version=version,
                    name=path.name,
                    bytes=len(raw),
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    chunks=spans,
                ),
                raw,
                text,
            )
        )
    if time.monotonic() - started > limits.parse_seconds:
        raise AgentFailure("DOCUMENT_LIMIT", "Parsing exceeded deadline")
    return parsed
