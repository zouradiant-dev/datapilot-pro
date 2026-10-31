"""One isolated CPU embedding process, fixed local weights, no generation/training/network."""

import argparse
import ctypes
import hashlib
import json
import os
import threading
import time
from pathlib import Path

import numpy as np


class MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
        (name, ctypes.c_size_t)
        for name in [
            "peak_rss",
            "rss",
            "peak_paged",
            "paged",
            "peak_nonpaged",
            "nonpaged",
            "pagefile",
            "peak_pagefile",
            "private",
        ]
    ]


def rss():
    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    if not ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.c_void_p(handle), ctypes.byref(counters), counters.cb
    ):
        raise OSError("Process resource sampling failed")
    return counters.peak_rss


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args()
    job = json.loads(args.job.read_bytes())
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    peak = [0]
    stopped = threading.Event()

    def monitor():
        while not stopped.wait(0.05):
            peak[0] = max(peak[0], rss())
            if peak[0] > 5 * 1024**3:
                os._exit(88)

    threading.Thread(target=monitor, daemon=True).start()
    started = time.perf_counter()
    before_cpu = time.process_time()
    dimensions = job["model"]["dimensions"]
    if job["id"] == "bge-small":
        from datapilot.rag.models import LocalEmbedding

        model = LocalEmbedding()

        def encode(text, query):
            values, usage = model.encode([text], query=query)
            return values[0], usage.tokens
    else:
        import torch
        from transformers import AutoModel, AutoTokenizer

        folder = Path(job["model"]["path"])
        for name, info in job["model"]["files"].items():
            with (folder / name).open("rb") as f:
                if hashlib.file_digest(f, "sha256").hexdigest() != info["sha256"]:
                    raise ValueError("Pinned model file changed")
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        tokenizer = AutoTokenizer.from_pretrained(
            folder, local_files_only=True, trust_remote_code=False, padding_side="left"
        )
        model = AutoModel.from_pretrained(
            folder,
            local_files_only=True,
            trust_remote_code=False,
            torch_dtype=torch.float32,
            low_cpu_mem_usage=True,
            weights_only=True,
        ).eval()

        def encode(text, query):
            if query and job["id"] == "qwen3":
                text = (
                    "Instruct: Given a SaaS operations question, retrieve relevant passages "
                    "that answer the question.\nQuery: " + text
                )
            tokens = tokenizer([text], return_tensors="pt", padding=True, truncation=False)
            if tokens["input_ids"].shape[1] > 512:
                raise ValueError("Reject rather than truncate")
            with torch.inference_mode():
                hidden = model(**tokens).last_hidden_state
                value = hidden[:, -1] if job["id"] == "qwen3" else hidden[:, 0]
                value = torch.nn.functional.normalize(value, p=2, dim=1)[0].cpu().numpy()
            return value, int(tokens["attention_mask"].sum())

    loaded = time.perf_counter() - started
    # Fixed unscored warmups, same texts for all models.
    encode("Public SaaS operational policy.", True)
    encode("Public SaaS operational policy.", False)
    vectors = {"documents": {}, "queries": {}}
    measurements = []
    for kind in ["documents", "queries"]:
        for id_, text in job["texts"][kind].items():
            begin = time.perf_counter()
            value, tokens = encode(text, kind == "queries")
            if (
                value.shape != (dimensions,)
                or not np.isfinite(value).all()
                or abs(float(np.linalg.norm(value)) - 1) > 0.001
            ):
                raise ValueError("Native vector shape/normalization changed")
            vectors[kind][id_] = value.tolist()
            measurements.append(
                {
                    "kind": kind,
                    "id": id_,
                    "tokens": tokens,
                    "milliseconds": (time.perf_counter() - begin) * 1000,
                }
            )
    stopped.set()
    peak[0] = max(peak[0], rss())
    output = {
        "model": job["model"],
        "id": job["id"],
        "vectors": vectors,
        "measurements": measurements,
        "resources": {
            "peak_process_rss_bytes": peak[0],
            "model_load_seconds": loaded,
            "total_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - before_cpu,
            "threads": 2,
            "device": "cpu",
            "batch": 1,
            "precision": "float32",
            "gpu_used": False,
        },
        "inference_only": True,
        "paid_calls": 0,
    }
    with Path(job["output"]).open("x", encoding="utf-8") as f:
        json.dump(output, f, allow_nan=False)
    print(
        json.dumps(
            {
                "model": job["id"],
                "dimensions": dimensions,
                "rss": peak[0],
                "seconds": output["resources"]["total_seconds"],
            }
        )
    )


if __name__ == "__main__":
    main()
