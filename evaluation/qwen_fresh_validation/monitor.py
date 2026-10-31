"""One read-only process sampler, no model loading, credentials or service architecture."""

import json
import shutil
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
    gpu = shutil.which("nvidia-smi")
    known = {}
    with output.open("x", encoding="utf-8") as stream:
        while parent.is_running() and parent.create_time() == created:
            rss = 0
            cpu = 0
            measured = 0
            pids = []
            for p in [parent, *parent.children(recursive=True)]:
                try:
                    identity = (p.pid, p.create_time())
                    p = known.setdefault(identity, p)
                    rss += p.memory_info().rss
                    pids.append(p.pid)
                    value = p.cpu_percent()
                    cpu += value
                    measured += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            row = {
                "wall_time": time.time(),
                "python_tree_rss_bytes": rss,
                "available_ram_bytes": psutil.virtual_memory().available,
                "tree_cpu_percent": cpu if measured else None,
                "cpu_note": "un-normalized sum; initial samples may be zero",
                "system_cpu_percent": psutil.cpu_percent(),
                "pids": pids,
                "whole_gpu_sample": None,
                "gpu_missing_reason": "nvidia-smi not on trusted host PATH",
            }
            if gpu:
                try:
                    x = subprocess.run(
                        [
                            gpu,
                            "--query-gpu=memory.used,memory.total,utilization.gpu",
                            "--format=csv,noheader,nounits",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                    row.update(
                        whole_gpu_sample=x.stdout.strip() if x.returncode == 0 else None,
                        gpu_missing_reason=None if x.returncode == 0 else "nvidia-smi nonzero exit",
                    )
                except (OSError, subprocess.TimeoutExpired):
                    row["gpu_missing_reason"] = "telemetry unavailable/timeout"
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except psutil.NoSuchProcess:
        pass
