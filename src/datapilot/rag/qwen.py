"""Opt-in Qwen profile in the existing MCP process; no network or remote model code."""

import hashlib
import importlib.metadata
import time

import numpy as np

from datapilot.contracts import AgentFailure
from datapilot.rag.contracts import EmbeddingUsage, ModelSpec
from datapilot.rag.models import ROOT, validate_vectors

REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
DIRECTORY = ROOT / ".cache/rag-models/qwen3" / REVISION
FILES = {
    "config.json": "b5bf1f51fc45be473a54718cef92448d90a1be001bf9b9a44b8c7f10a19feaa9",
    "model.safetensors": "0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd",
    "tokenizer.json": "def76fb086971c7867b829c23a26261e38d9d74e02139253b38aeb9df8b4b50a",
    "tokenizer_config.json": "253153d0738ceb4c668d2eff957714dd2bea0b56de772a9fdccd96cbf517e6a0",
    "vocab.json": "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
    "merges.txt": "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5",
}
PREFIX = (
    "Instruct: Given a SaaS operations question, retrieve relevant passages "
    "that answer the question.\nQuery: "
)
CALIBRATION_SHA256 = "9be20cb4b8cbffbe74a95a06d15d4bf7b6bad621a67972301decd7d98233fa2b"


def policy(profile):
    from datapilot.ingestion.common import digest

    # Selected independently on the new calibration split, not copied from BGE.
    # Coincident numerical equality does not make these interchangeable policies.
    return {
        "model_sha256": digest(specification(profile)),
        "calibration_sha256": CALIBRATION_SHA256,
        "search_policy": profile + "/search-cosine-v1",
        "search_threshold": 0.55,
        "goal_policy": profile + "/host-goal-cosine-v1",
        "goal_threshold": 0.55,
    }


def specification(profile):
    if profile not in {"qwen3-cpu-v1", "qwen3-cuda-fp16-v1"}:
        raise AgentFailure("EMBEDDING_VERSION", "Unknown host embedding profile")
    precision = "fp32-cpu" if profile == "qwen3-cpu-v1" else "fp16-cuda"
    return ModelSpec(
        model="Qwen/Qwen3-Embedding-0.6B",
        revision=REVISION,
        dimensions=1024,
        recipe=f"last-l2-saas-v1/{precision}/torch2.8.0-cu128/transformers4.57.1/tok0.22.2",
        files=FILES,
    )


def interpreter():
    from datapilot.rag.qwen_runtime import executable, expected

    expected()  # Allows a standard Linux venv symlink only with an exact binary binding.
    return str(executable())


def check_files():
    if not DIRECTORY.is_dir() or DIRECTORY.resolve() != DIRECTORY.absolute():
        raise AgentFailure("EMBEDDING_NOT_READY", "Deploy the pinned Qwen files explicitly")
    if {p.name for p in DIRECTORY.iterdir()} != set(FILES):
        raise AgentFailure("EMBEDDING_NOT_READY", "Unexpected Qwen model artifacts")
    for name, expected in FILES.items():
        path = DIRECTORY / name
        if path.is_symlink() or not path.is_file():
            raise AgentFailure("EMBEDDING_NOT_READY", "Model artifacts must be regular files")
        with path.open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != expected:
                raise AgentFailure("EMBEDDING_NOT_READY", "Qwen model artifact hash differs")


class QwenEmbedding:
    def __init__(self, profile, *, observer=None):
        self.spec = specification(profile)
        observe = observer or (lambda *args, **kwargs: None)
        try:
            from datapilot.rag.qwen_runtime import verify

            verify()
            for package, version in {
                "torch": "2.8.0+cu128",
                "transformers": "4.57.1",
                "tokenizers": "0.22.2",
                "huggingface-hub": "0.36.0",
            }.items():
                if importlib.metadata.version(package) != version:
                    raise ValueError("Dependency profile differs")
            observe("imports_started")
            import torch
            from transformers import AutoModel, AutoTokenizer

            observe("imports_complete")
            observe("file_hash_started")
            check_files()
            observe("file_hash_complete")
            self.torch = torch
            self.device = "cuda" if profile == "qwen3-cuda-fp16-v1" else "cpu"
            if self.device == "cuda":
                observe("cuda_initialization_started")
                if not torch.cuda.is_available():
                    raise ValueError("CUDA unavailable; no silent CPU fallback")
                free, total = torch.cuda.mem_get_info()
                observe("cuda_initialization_complete", free_vram=free, total_vram=total)
                if free < 2 * 1024**3:
                    raise AgentFailure("EMBEDDING_RESOURCE_LIMIT", "Insufficient GPU capacity")
            torch.set_num_threads(2)
            observe("tokenizer_started")
            self.tokenizer = AutoTokenizer.from_pretrained(
                DIRECTORY, local_files_only=True, trust_remote_code=False, padding_side="left"
            )
            observe("tokenizer_complete")
            observe("weights_started")
            self.model = AutoModel.from_pretrained(
                DIRECTORY,
                local_files_only=True,
                trust_remote_code=False,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                low_cpu_mem_usage=True,
                use_safetensors=True,
                attn_implementation="eager",
            ).eval()
            observe("weights_complete")
            observe("device_transfer_started")
            self.model.to(self.device)
            observe("device_transfer_complete")
        except AgentFailure:
            raise
        except (ImportError, ValueError, OSError, RuntimeError):
            raise AgentFailure(
                "EMBEDDING_NOT_READY", "Pinned Qwen runtime could not load"
            ) from None

    def encode(self, texts, *, query=False):
        if len(texts) > 1024 or any(not isinstance(t, str) or len(t) > 512 for t in texts):
            raise AgentFailure("EMBEDDING_LIMIT", "Embedding input exceeds quota")
        started, values, tokens = time.perf_counter(), [], 0
        try:
            for text in texts:
                batch = self.tokenizer(
                    [(PREFIX if query else "") + text],
                    return_tensors="pt",
                    padding=True,
                    truncation=False,
                )
                if batch["input_ids"].shape[1] > 512:
                    raise AgentFailure("EMBEDDING_LIMIT", "Refusing embedding truncation")
                tokens += int(batch["attention_mask"].sum())
                with self.torch.inference_mode():
                    hidden = self.model(**batch.to(self.device)).last_hidden_state[:, -1].float()
                    vector = self.torch.nn.functional.normalize(hidden, p=2, dim=1)[0]
                    values.append(vector.cpu().numpy())  # synchronizes CUDA before timing
                if time.perf_counter() - started > 30:
                    raise AgentFailure("EMBEDDING_TIMEOUT", "Bounded Qwen encoding timed out")
        except RuntimeError:
            raise AgentFailure("EMBEDDING_INVALID", "Local Qwen inference failed") from None
        matrix = (
            validate_vectors(values, len(texts), 1024) if texts else np.empty((0, 1024), np.float32)
        )
        return matrix, EmbeddingUsage(
            mode="local_torch",
            tokens=tokens,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            calls=int(bool(texts)),
        )
