"""Public Dev calibration and resource measurements. Not a business/Live evaluator."""

import argparse
import gc
import hashlib
import json
import math
import statistics
import time
from pathlib import Path

from datapilot.rag.qwen import QwenEmbedding


def select_threshold(rows, grid, *, goal=False):
    """Calibration only; goal labels are independent of model-selected query words."""
    if not rows or any(r["split"] != "calibration" for r in rows):
        raise ValueError("Only preregistered calibration rows may select a threshold")
    candidates = []
    for threshold in grid:
        if goal:
            relevant = [
                (score, name in r["goal_relevant"]) for r in rows for name, score in r["goals"]
            ]
            fp = sum(score >= threshold and not label for score, label in relevant)
            tp = sum(score >= threshold and label for score, label in relevant)
            positives = sum(label for _, label in relevant)
            recall = tp / positives if positives else 0
        else:
            fp = sum(
                any(score >= threshold for _, score in r["ranked"])
                for r in rows
                if not r["relevant"]
            )
            recalls = [
                len({n for n, score in r["ranked"] if score >= threshold} & set(r["relevant"]))
                / len(r["relevant"])
                for r in rows
                if r["relevant"]
            ]
            recall = statistics.mean(recalls)
        if fp == 0:
            candidates.append((recall, threshold))
    if not candidates:
        raise ValueError("No safe calibration threshold; reject profile activation")
    return max(candidates)[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["qwen3-cpu-v1", "qwen3-cuda-fp16-v1"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".calibration-lock.json").exists():
        raise ValueError("Use a new experiment output; never overwrite recorded calibration")
    path = Path("tests/fixtures/rag/qwen-migration-dev.json")
    data = json.loads(path.read_bytes())
    before = time.perf_counter()
    import torch

    if args.profile.endswith("fp16-v1"):
        torch.cuda.reset_peak_memory_stats()
    model = QwenEmbedding(args.profile)
    load = time.perf_counter() - before
    warm_start = time.perf_counter()
    model.encode(["Public operational reference."], query=True)
    warm = time.perf_counter() - warm_start
    rows, latency = [], []
    for split, pack in data["splits"].items():
        names = list(pack["sources"])
        documents, _ = model.encode(list(pack["sources"].values()))
        for case in pack["cases"]:
            begin = time.perf_counter()
            queries, _ = model.encode([case["query"], case["goal"]], query=True)
            latency.append((time.perf_counter() - begin) * 500)  # measured two encodings
            pool = [
                i
                for i, n in enumerate(names)
                if case["pool"] == "all" or n.endswith("-" + case["pool"] + ".md")
            ]
            scores = documents @ queries[0]
            ranked = sorted(pool, key=lambda i: (-scores[i], names[i]))[: data["top_k"]]
            rows.append(
                {
                    **case,
                    "split": split,
                    "ranked": [(names[i], float(scores[i])) for i in ranked],
                    "goals": [(names[i], float(documents[i] @ queries[1])) for i in ranked],
                    "goal_relevant": case.get("goal_relevant", case["relevant"]),
                }
            )
        if split == "calibration":
            search = select_threshold(rows, data["threshold_grid"])
            goal = select_threshold(rows, data["threshold_grid"], goal=True)
            lock = {
                "search_threshold": search,
                "goal_threshold": goal,
                "fixture_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            args.output.with_suffix(".calibration-lock.json").write_text(
                json.dumps(lock, indent=2), encoding="utf-8"
            )
    import ctypes

    from evaluation.embedding_ab.model_worker import rss

    resources = {
        "load_seconds_including_imports_hash": load,
        "warmup_seconds": warm,
        "paired_encoding_half_p50_ms": statistics.median(latency),
        "paired_encoding_half_p95_ms": sorted(latency)[math.ceil(0.95 * len(latency)) - 1],
        "peak_rss_bytes": rss() if hasattr(ctypes, "windll") else None,
        "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated()
        if model.device == "cuda"
        else 0,
        "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved()
        if model.device == "cuda"
        else 0,
        "device": model.device,
        "dtype": str(next(model.model.parameters()).dtype),
        "cuda_version": torch.version.cuda,
        "torch_version": torch.__version__,
        "gpu": torch.cuda.get_device_name() if model.device == "cuda" else None,
    }
    result = {
        "profile": args.profile,
        "model": model.spec.model_dump(),
        "lock": lock,
        "rows": rows,
        "resources": resources,
        "paid_calls": 0,
    }
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({"profile": args.profile, "lock": lock, "resources": resources}))
    del model
    gc.collect()


if __name__ == "__main__":
    main()
