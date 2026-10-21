"""Pinned local CPU inference; no training, API credential, network or arbitrary model code."""

import hashlib
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import numpy as np

from datapilot.contracts import AgentFailure
from datapilot.rag.contracts import EmbeddingUsage, ModelSpec

REVISION = "46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59"
FILES = {
    "model_optimized.onnx": (
        94781076,
        "1294ea4b6331115a353d81f96b85e8c8d7fdcc284453d5b2fab5b016230aad38",
    ),
    "tokenizer.json": (439125, "48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26"),
}
ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = ROOT / ".cache/rag-models" / REVISION
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def specification() -> ModelSpec:
    return ModelSpec(
        model="BAAI/bge-small-zh-v1.5/Qdrant-onnx",
        revision=REVISION,
        recipe="cls-l2-query-prefix-1/ort-1.31.0/tokenizers-0.23.3",
        files={name: entry[1] for name, entry in FILES.items()},
    )


def checked_file(name: str) -> Path:
    path = MODEL_DIR / name
    size, expected = FILES[name]
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
        raise AgentFailure("EMBEDDING_NOT_READY", "Explicitly fetch the pinned local model first")
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise AgentFailure("EMBEDDING_NOT_READY", "Local model integrity check failed")
    return path


def fetch_model() -> None:
    """Trusted explicit deployment command. Never registered as an MCP/model tool."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, (size, expected) in FILES.items():
        destination = MODEL_DIR / name
        if destination.exists():
            checked_file(name)
            continue
        temporary = MODEL_DIR / (name + "." + uuid4().hex + ".partial")
        url = f"https://huggingface.co/Qdrant/bge-small-zh-v1.5/resolve/{REVISION}/{name}"
        started, count, sha = time.monotonic(), 0, hashlib.sha256()
        try:
            with urllib.request.urlopen(url, timeout=20) as response, temporary.open("xb") as out:
                while block := response.read(1024 * 1024):
                    count += len(block)
                    if count > size or time.monotonic() - started > 180:
                        raise AgentFailure("EMBEDDING_NOT_READY", "Bounded model download failed")
                    sha.update(block)
                    out.write(block)
            if count != size or sha.hexdigest() != expected:
                raise AgentFailure("EMBEDDING_NOT_READY", "Downloaded model hash differs")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def validate_vectors(values, count):
    matrix = np.asarray(values, dtype=np.float32)
    if matrix.shape != (count, 512) or not np.isfinite(matrix).all():
        raise AgentFailure("EMBEDDING_INVALID", "Embedding dimensions/finite values differ")
    norms = np.linalg.norm(matrix, axis=1)
    if np.any(np.abs(norms - 1) > 0.001):
        raise AgentFailure("EMBEDDING_INVALID", "Embeddings must be normalized and nonzero")
    return matrix


class LocalEmbedding:
    def __init__(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.spec = specification()
        self.tokenizer = Tokenizer.from_file(str(checked_file("tokenizer.json")))
        self.tokenizer.no_truncation()
        self.tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(checked_file("model_optimized.onnx")),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.inputs = {i.name for i in self.session.get_inputs()}

    def encode(self, texts: list[str], *, query=False):
        if not texts:
            return np.empty((0, 512), dtype=np.float32), EmbeddingUsage(
                mode="local_onnx", tokens=0, elapsed_ms=0, calls=0
            )
        if len(texts) > 1024 or any(len(t) > 512 for t in texts):
            raise AgentFailure("EMBEDDING_LIMIT", "Embedding batch exceeds input quota")
        started, result, tokens = time.perf_counter(), [], 0
        for start in range(0, len(texts), 16):
            batch = texts[start : start + 16]
            encoded = self.tokenizer.encode_batch(
                [(QUERY_PREFIX if query else "") + t for t in batch]
            )
            if any(sum(e.attention_mask) > 512 for e in encoded):
                raise AgentFailure("EMBEDDING_LIMIT", "Input cannot fit model; refusing truncation")
            tokens += sum(sum(e.attention_mask) for e in encoded)
            feeds = {
                "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
                "token_type_ids": np.array([e.type_ids for e in encoded], dtype=np.int64),
            }
            vectors = self.session.run(None, {k: v for k, v in feeds.items() if k in self.inputs})[
                0
            ]
            vectors = vectors[:, 0, :] if vectors.ndim == 3 else vectors
            vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
            result.extend(vectors)
            if time.perf_counter() - started > 30:
                raise AgentFailure("EMBEDDING_TIMEOUT", "Bounded local embedding exceeded deadline")
        return validate_vectors(result, len(texts)), EmbeddingUsage(
            mode="local_onnx",
            tokens=tokens,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            calls=1,
        )
