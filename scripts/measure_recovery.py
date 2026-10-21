"""Explicit local PG/Fake baseline and opt-in two-call live recovery experiment.

Writes only measurements, never prompts, SQL, business rows or connection credentials.
"""

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from datapilot.cli import json_default
from datapilot.config import Settings
from datapilot.graph import run_question
from datapilot.persistence.backend import Backend, execute
from datapilot.persistence.session import run_async

ROOT = Path(__file__).resolve().parents[1]


def child(arguments):
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    if result.returncode:
        raise RuntimeError(f"Measurement child failed with exit code {result.returncode}")
    return json.loads(result.stdout), round((time.perf_counter() - started) * 1000, 2)


def measurements(result, elapsed):
    assert result["status"] in {"paused", "succeeded"}
    compression = [e["compression"] for e in result["trace"] if e.get("compression")]
    return {
        "wall_ms_including_process_start": elapsed,
        "usage": result["usage"],
        "compression_count": len(compression),
        "irreversible_source_loss": any(c["irreversible_source_loss"] for c in compression),
    }


def external_usage(settings, id_):
    b = Backend(settings.runtime_database_url.get_secret_value(), id_, "local-user")
    try:
        with b.transaction() as conn:
            calls = (
                execute(
                    conn,
                    "SELECT kind,status,usage,elapsed_ms FROM execution.calls "
                    "WHERE run_id=:run ORDER BY call_key",
                    run=id_,
                )
                .mappings()
                .all()
            )
            size = execute(
                conn,
                "SELECT coalesce(sum(bytes),0) FROM execution.artifacts WHERE run_id=:run",
                run=id_,
            ).scalar_one()
            checkpoints = execute(
                conn, "SELECT count(*) FROM checkpoints.checkpoints WHERE thread_id=:run", run=id_
            ).scalar_one()
        return {
            "external_calls": [dict(c) for c in calls],
            "artifact_logical_bytes": size,
            "checkpoint_rows": checkpoints,
        }
    finally:
        b.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Two opt-in paid SQL decisions")
    parser.add_argument("--memory-once", action="store_true")
    args = parser.parse_args()
    if args.memory_once:
        result = run_async(run_question(Settings(llm_mode="fake"), "查询客户总数"))
        print(json.dumps(result, default=json_default, ensure_ascii=False))
        return
    settings = Settings(llm_mode="fake")
    output = {
        "baseline": "same PG/MCP customer-count task; model decisions Fake",
        "provider_cost": {"amount": None, "status": "no_invoice_or_price_assumption"},
        "fake": [],
        "durable": [],
    }
    for _ in range(3):
        result, elapsed = child([str(Path(__file__).resolve()), "--memory-once"])
        output["fake"].append(measurements(result, elapsed))
        id_ = str(uuid4())
        result, elapsed = child(["scripts/recovery_probe.py", "start", id_])
        output["durable"].append({**measurements(result, elapsed), **external_usage(settings, id_)})
    output["wall_median_ms"] = {
        key: statistics.median(r["wall_ms_including_process_start"] for r in output[key])
        for key in ("fake", "durable")
    }
    if args.live:
        id_ = str(uuid4())
        paused, before = child(
            ["scripts/recovery_probe.py", "start", id_, "--live", "--pause-after", "worker"]
        )
        completed, after = child(["scripts/recovery_probe.py", "resume", id_, "--live"])
        repeated, repeat_time = child(["scripts/recovery_probe.py", "resume", id_, "--live"])
        assert completed["status"] == "succeeded"
        assert completed["result"]["result"]["rows"] == [[240]]
        assert paused["usage"] == completed["usage"] == repeated["usage"]
        assert paused["results"] == completed["results"] == repeated["results"]
        assert completed["usage"]["calls"] == 2
        output["live"] = {
            "model": settings.model,
            "provider": settings.model_provider,
            "thinking": "disabled_by_profile",
            "pause": measurements(paused, before),
            "resume": measurements(completed, after),
            "repeat_resume": measurements(repeated, repeat_time),
            "verified_customer_count": 240,
            **external_usage(settings, id_),
        }
    target = ROOT / "artifacts/p5b/measurements.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "artifact": str(target),
                "wall_median_ms": output["wall_median_ms"],
                "live": output.get("live"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
