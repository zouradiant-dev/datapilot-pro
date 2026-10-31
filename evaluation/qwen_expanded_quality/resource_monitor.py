"""Read-only sampler using the already pinned Qwen environment's psutil; no model import."""

import json
import subprocess
import sys
import time
from pathlib import Path

import psutil


def main():
    parent = psutil.Process(int(sys.argv[1]))
    created = parent.create_time()
    output = Path(sys.argv[2])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf8") as stream:
        while parent.is_running() and parent.create_time() == created:
            processes = [parent, *parent.children(recursive=True)]
            rss, pids = 0, []
            for p in processes:
                try:
                    rss += p.memory_info().rss
                    pids.append(p.pid)
                except psutil.NoSuchProcess:
                    pass
            row = {
                "wall_time": time.time(),
                "python_tree_rss_bytes": rss,
                "available_ram_bytes": psutil.virtual_memory().available,
                "pids": pids,
            }
            try:
                gpu = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.used,memory.total,utilization.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                row["whole_gpu_sample"] = gpu.stdout.strip() if gpu.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                row["whole_gpu_sample"] = None
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except psutil.NoSuchProcess:
        pass
