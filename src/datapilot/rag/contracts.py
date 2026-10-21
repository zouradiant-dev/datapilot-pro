"""Document authority is supplied by the host, never inferred from retrieved text."""

from typing import Literal

from pydantic import Field, model_validator

from datapilot.contracts import Contract
from datapilot.datasets.contracts import DatasetId, DatasetScope, Version
from datapilot.ingestion.contracts import Digest

DIMENSIONS = 512
RETRIEVER = "pg-cosine-exact-1"


class ModelSpec(Contract):
    model: str = Field(min_length=1, max_length=128)
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    dimensions: Literal[512] = DIMENSIONS
    recipe: str = Field(min_length=1, max_length=128)
    files: dict[str, Digest] = Field(min_length=1, max_length=4)
    fixture: bool = False


class Chunker(Contract):
    version: Literal["unicode-window-1"] = "unicode-window-1"
    chars: int = Field(default=192, ge=64, le=256)
    overlap: int = Field(default=32, ge=0, le=64)

    @model_validator(mode="after")
    def bounded_overlap(self):
        if self.overlap >= self.chars:
            raise ValueError("Overlap must be smaller than a chunk")
        return self


class Limits(Contract):
    files: int = Field(default=16, ge=1, le=32)
    file_bytes: int = Field(default=256 * 1024, ge=1, le=256 * 1024)
    total_bytes: int = Field(default=1024 * 1024, ge=1, le=1024 * 1024)
    chunks: int = Field(default=1024, ge=1, le=1024)
    parse_seconds: float = Field(default=3, gt=0, le=10)


class Target(Contract):
    corpus_id: DatasetId
    owner: str = Field(default="local-user", min_length=1, max_length=64)
    dataset_id: DatasetId | None = None
    dataset_version: Version | None = None

    @model_validator(mode="after")
    def fixed_dataset(self):
        if (self.dataset_id is None) != (self.dataset_version is None):
            raise ValueError("Pin both dataset ID and version or explicitly use SaaS documents")
        return self


class CorpusPin(Contract):
    corpus_id: DatasetId
    index_version: Digest
    document_ids: list[Digest] = Field(max_length=32)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("Repeated document grant")
        return self


class RagScope(Contract):
    owner: str = Field(default="local-user", min_length=1, max_length=64)
    corpora: list[CorpusPin] = Field(default_factory=list, max_length=8)
    datasets: DatasetScope = Field(default_factory=DatasetScope)
    allow_saas: bool = False
    min_score: float = Field(default=0.55, ge=-1, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def unique(self):
        if len({p.corpus_id for p in self.corpora}) != len(self.corpora):
            raise ValueError("One index version per corpus per session")
        if any(b.version is None for b in self.datasets.bindings):
            raise ValueError("RAG dataset grants require explicit versions")
        if len(self.datasets.bindings) > 8:
            raise ValueError("RAG context supports at most eight pinned datasets")
        return self

    def permits(self, target: Target) -> bool:
        return target.owner == self.owner and (
            self.allow_saas
            if target.dataset_id is None
            else (target.dataset_id, target.dataset_version)
            in {(b.dataset_id, b.version) for b in self.datasets.bindings}
        )


class ChunkSpan(Contract):
    chunk_id: Digest
    start: int = Field(ge=0, le=1024 * 1024)
    end: int = Field(ge=0, le=1024 * 1024)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    sha256: Digest

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start or self.end - self.start > 256 or self.line_end < self.line_start:
            raise ValueError("Invalid bounded source span")
        return self


class SourceInfo(Contract):
    source_id: Digest
    document_id: Digest
    version: Digest
    name: str = Field(min_length=1, max_length=128, pattern=r"^[\w .-]+$")
    bytes: int = Field(ge=0, le=256 * 1024)
    text_sha256: Digest
    chunks: list[ChunkSpan] = Field(max_length=1024)


class IndexManifest(Contract):
    target: Target
    model: ModelSpec
    chunker: Chunker
    retriever: Literal["pg-cosine-exact-1"] = RETRIEVER
    sources: list[SourceInfo] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def bounded_unique_sources(self):
        if (
            len({s.document_id for s in self.sources}) != len(self.sources)
            or len({s.source_id for s in self.sources}) != len(self.sources)
            or sum(s.bytes for s in self.sources) > 1024 * 1024
            or sum(len(s.chunks) for s in self.sources) > 1024
        ):
            raise ValueError("Duplicate identities or index size exceeds quota")
        return self


class ChunkCitation(ChunkSpan):
    corpus_id: DatasetId
    index_version: Digest
    source_id: Digest
    document_id: Digest
    version: Digest
    source_sha256: Digest
    model_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    chunker_sha256: Digest
    retriever: Literal["pg-cosine-exact-1"] = RETRIEVER
    score: float = Field(ge=-1, le=1, allow_inf_nan=False)
    page: None = None  # TXT/Markdown only; never fabricate PDF page numbers.


class EmbeddingUsage(Contract):
    mode: Literal["local_onnx", "synthetic_test"]
    tokens: int = Field(ge=0, le=512 * 1024)
    elapsed_ms: float = Field(ge=0)
    calls: int = Field(ge=0, le=1024)
