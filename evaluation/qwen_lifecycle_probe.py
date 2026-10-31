"""Opt-in local engineering probe, no provider calls, ingestion or quality scoring.

Run with the pinned Qwen interpreter and a trusted synthetic RagScope. Existing
MCP authorization/readiness/10s limits remain in force. Output belongs in artifacts/.
"""

import argparse
import asyncio
import json
import math
import statistics
import subprocess
import time
from pathlib import Path

import psutil

from datapilot.config import Settings
from datapilot.persistence.session import run_async
from datapilot.rag.cli import read_scope
from datapilot.rag.mcp import rag_session


async def probe(settings, scope, goal):
    samples, searches = [], []

    async def sample():
        parent = psutil.Process()
        while True:
            rss, pids = 0, []
            for child in parent.children(recursive=True):
                try:
                    if child.name().lower().startswith("python"):
                        rss += child.memory_info().rss
                        pids.append(child.pid)
                except psutil.NoSuchProcess:
                    pass
            row = {
                "wall_time": time.time(),
                "rss": rss,
                "python_child_pids": pids,
                "available_ram": psutil.virtual_memory().available,
            }
            try:
                gpu = await asyncio.to_thread(
                    subprocess.run,
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.used,memory.total,utilization.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    timeout=2,
                    text=True,
                )
                row["gpu_mib_utilization"] = gpu.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
            samples.append(row)
            await asyncio.sleep(0.25)

    begin = time.perf_counter()
    sampler = asyncio.create_task(sample())
    try:
        async with rag_session(settings, scope, goal=goal) as tools:
            ready = time.perf_counter()
            owner = tools.process_owner
            for _ in range(20):
                now = time.perf_counter()
                result = await tools.search(goal, 3)
                searches.append(
                    {
                        "seconds": time.perf_counter() - now,
                        "usage": result.embedding_usage.model_dump(),
                        "document_count": len(result.documents),
                    }
                )
                await asyncio.sleep(0.05)
            health = (await tools.call("health", {}))["embedding"]
            close = time.perf_counter()
        cleanup = time.perf_counter() - close
        await asyncio.sleep(1)
    finally:
        sampler.cancel()
        await asyncio.gather(sampler, return_exceptions=True)
    after = psutil.pid_exists(owner.pid)
    values = sorted(s["seconds"] for s in searches)
    return {
        "ready_seconds": ready - begin,
        "spawn_wall_started": tools.spawn_wall_started,
        "startup": tools.startup_trace,
        "searches": searches,
        "samples": samples,
        "health": health,
        "p50_seconds": statistics.median(values),
        "p95_seconds": values[math.ceil(len(values) * 0.95) - 1],
        "cleanup_seconds": cleanup,
        "process_exists_after_close": after,
        "owner_events": owner.events,
        "note": "NVIDIA values are whole-GPU sampled usage, not allocator/process peak",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run_async(
        probe(
            Settings(_env_file=None, llm_mode="fake", api_key=None),
            read_scope(args.scope),
            args.goal,
        )
    )
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in {"startup", "health", "samples", "searches"}
            }
        )
    )


if __name__ == "__main__":
    main()
