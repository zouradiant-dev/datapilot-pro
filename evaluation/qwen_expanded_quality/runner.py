"""Serial batch driver of the original Durable; immutable intent, no retry or recovery engine."""

import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from datapilot.cli import json_default
from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.persistence.backend import Backend, DurableArtifacts, execute
from datapilot.persistence.inspection import inspect_run
from datapilot.persistence.session import run_async, run_durable

from .common import ARMS, OUT, ROOT, cases, run_id, scopes, sha, verify, write_new
from .prepare import environment
from .scoring import score

sys.path.insert(0, str(ROOT / "scripts"))
from p7_business_scoring import sign_collection  # noqa: E402
from report_recovery_probe import ReportDecisions  # noqa: E402


def encoded(value):
    return json.loads(json.dumps(value, default=json_default))


def instrument(timings, stage):
    import datapilot.persistence.inspection as inspection
    import datapilot.rag.mcp as rag
    import datapilot.runtime.mcp_client as client

    connector, session = client._connection, rag.rag_session

    @asynccontextmanager
    async def measured_connector(*args, **kwargs):
        begin = time.perf_counter()
        env = args[1] if len(args) > 1 else kwargs.get("env", {})
        role = (
            "rag"
            if "DATAPILOT_RAG_SCOPE" in env
            else "dataset"
            if "DATAPILOT_DATASET_SCOPE" in env
            else "sql"
        )
        async with connector(*args, **kwargs) as value:
            timings.append(
                {
                    "stage": stage[0],
                    "component": "mcp_startup_to_ready",
                    "role": role,
                    "seconds": time.perf_counter() - begin,
                }
            )
            yield value

    @asynccontextmanager
    async def measured_rag(*args, **kwargs):
        begin = time.perf_counter()
        async with session(*args, **kwargs) as tools:
            if tools:
                timings.append(
                    {
                        "stage": stage[0],
                        "component": "rag_ready_total",
                        "seconds": time.perf_counter() - begin,
                        "explicit_prepare": tools.startup_trace,
                        "note": (
                            "BGE has no separate explicit prepare telemetry; its readiness "
                            "includes server initialization"
                        ),
                    }
                )
            yield tools

    client._connection = rag._connection = measured_connector
    rag.rag_session = inspection.rag_session = measured_rag


async def one(case, arm):
    reg = verify()
    active_batch = next(i for i, ids in enumerate(reg["batches"]) if case.id in ids)
    if not (OUT / f"batch-{active_batch}-manifest.json").exists():
        raise ValueError("No authorized active evaluation batch")
    if active_batch:
        previous = json.loads((OUT / f"batch-{active_batch - 1}-seal.json").read_bytes())
        if not previous["complete"] or not previous["offline_equal"] or previous["stopped"]:
            raise ValueError("Earlier batch is incomplete or stopped; Validation remains unopened")
    bindseal = json.loads((OUT / "bindings-seal.json").read_bytes())
    assert sha(OUT / "bindings.json") == bindseal["sha256"]
    bindings = json.loads((OUT / "bindings.json").read_bytes())
    _, settings = environment()
    rag, report = scopes(case, arm, bindings)
    id_ = run_id(case, arm)
    write_new(
        OUT / "dispatch" / f"{case.id}-{arm}.json",
        {
            "run_id": id_,
            "case_sha256": digest(case),
            "at": datetime.now(UTC).isoformat(),
            "paid": False,
        },
    )
    key = (OUT / "collector-key-private.bin").read_bytes()
    timings = []
    stage = ["runtime"]
    instrument(timings, stage)
    started = time.perf_counter()
    payload = {"case_id": case.id, "case_sha256": digest(case), "arm": arm, "run_id": id_}
    try:
        begin = time.perf_counter()
        result = await run_durable(
            settings,
            id_,
            case.query,
            owner="expanded-public-v1",
            rag_scope=rag,
            report_scope=report,
            transport=ReportDecisions(case.doc_query or case.query),
        )
        timings.append(
            {
                "stage": "runtime",
                "component": "durable_total",
                "seconds": time.perf_counter() - begin,
            }
        )
        stage[0] = "inspector"
        begin = time.perf_counter()
        snapshot = await inspect_run(
            settings, id_, report.owner, case.query, report_scope=report, rag_scope=rag
        )
        timings.append(
            {
                "stage": "inspector",
                "component": "inspector_total",
                "seconds": time.perf_counter() - begin,
            }
        )
        if snapshot["unknown"] or snapshot["report"] is None:
            raise AgentFailure(
                "EVALUATION_INTEGRITY", "Inspector found unknown or no verified report"
            )
        backend = Backend(settings.runtime_database_url.get_secret_value(), id_, report.owner)
        try:
            artifacts = DurableArtifacts(backend).export()
            with backend.transaction() as conn:
                manifest = backend.authorize(conn)["manifest"]
                calls = [
                    dict(r)
                    for r in execute(
                        conn,
                        "SELECT * FROM execution.calls WHERE run_id=:r ORDER BY call_key",
                        r=id_,
                    ).mappings()
                ]
                events = [
                    dict(r)
                    for r in execute(
                        conn,
                        "SELECT payload FROM execution.events WHERE run_id=:r ORDER BY event_id",
                        r=id_,
                    ).mappings()
                ]
        finally:
            backend.close()
        if manifest["policy"]["llm_mode"] != "fake":
            raise ValueError("Paid mode prohibited")
        payload.update(
            stage="runtime",
            inspector_verified=True,
            result=encoded(result),
            snapshot=encoded(snapshot),
            manifest=encoded(manifest),
            artifacts=encoded(artifacts),
            calls=encoded(calls),
            events=encoded(events),
        )
    except AgentFailure as exc:
        payload.update(
            stage="preflight" if case.preflight else "runtime",
            error=exc.error.model_dump(),
            inspector_verified=False,
        )
    payload.update(seconds=time.perf_counter() - started, timings=timings)
    signed = sign_collection(payload, key)
    write_new(OUT / "collections" / f"{case.id}-{arm}.json", signed)
    rated = score(case, arm, signed, key, bindings)
    write_new(OUT / "scores" / f"{case.id}-{arm}.json", rated)
    print(
        json.dumps(
            {
                "case": case.id,
                "arm": arm,
                "status": rated["actual_status"],
                "strict": rated["strict_correct"],
                "safety": rated["safety_violations"],
            }
        ),
        flush=True,
    )


def batch(index):
    reg = verify()
    ids = reg["batches"][index]
    if (OUT / "STOP").exists() or (OUT / "stopped.json").exists():
        raise ValueError("STOP exists; no further dispatch")
    if index:
        previous = OUT / f"batch-{index - 1}-seal.json"
        assert previous.exists(), "Previous batch not sealed"
        seal = json.loads(previous.read_bytes())
        assert seal["complete"] and seal["offline_equal"] and not seal["stopped"]
    write_new(
        OUT / f"batch-{index}-manifest.json",
        {
            "ids": ids,
            "at": datetime.now(UTC).isoformat(),
            "registration_sha256": sha(OUT / "registration.json"),
            "implementation_sha256": sha(OUT / "registration-r2.json"),
            "expected_observations": 40,
        },
    )
    for id_ in ids:
        arms = list(ARMS) if int(id_[2:]) % 2 else list(reversed(ARMS))
        for arm in arms:
            if (OUT / "STOP").exists():
                return
            if (OUT / "dispatch" / f"{id_}-{arm}.json").exists():
                raise ValueError("Intent exists: never auto-rerun")
            log = OUT / "logs" / f"{id_}-{arm}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            begin = time.perf_counter()
            with log.open("x", encoding="utf8") as stream:
                try:
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-u",
                            "-m",
                            __package__ + ".runner",
                            "one",
                            "--case",
                            id_,
                            "--arm",
                            arm,
                        ],
                        cwd=ROOT,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                    )
                    from datapilot.rag.qwen import interpreter

                    monitor_env = {
                        k: v
                        for k, v in os.environ.items()
                        if k.upper()
                        in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE"}
                    }
                    monitor = subprocess.Popen(
                        [
                            interpreter(),
                            str(ROOT / "evaluation/qwen_expanded_quality/resource_monitor.py"),
                            str(process.pid),
                            str(OUT / "resources" / f"{id_}-{arm}.jsonl"),
                        ],
                        env=monitor_env,
                        stdout=stream,
                        stderr=stream,
                    )
                    try:
                        returncode = process.wait(timeout=360)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                        raise
                    finally:
                        try:
                            monitor.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            monitor.terminate()
                            monitor.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    write_new(
                        OUT / "stopped.json",
                        {"case": id_, "arm": arm, "reason": "Host timeout/unknown; do not resend"},
                    )
                    return
            write_new(
                OUT / "host-time" / f"{id_}-{arm}.json",
                {"seconds": time.perf_counter() - begin, "returncode": returncode},
            )
            path = OUT / "scores" / f"{id_}-{arm}.json"
            if returncode or not path.exists():
                write_new(
                    OUT / "stopped.json",
                    {
                        "case": id_,
                        "arm": arm,
                        "reason": "Collector/evaluator/infrastructure failure",
                        "returncode": returncode,
                    },
                )
                return
            row = json.loads(path.read_bytes())
            print(
                json.dumps(
                    {
                        "case": id_,
                        "arm": arm,
                        "strict": row["strict_correct"],
                        "status": row["actual_status"],
                    }
                ),
                flush=True,
            )
            if row["safety_violations"] or row["infrastructure_failure"]:
                write_new(
                    OUT / "stopped.json",
                    {
                        "case": id_,
                        "arm": arm,
                        "reason": row["safety_violations"] or row["error_categories"],
                        "at": datetime.now(UTC).isoformat(),
                    },
                )
                return


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["batch", "one"])
    p.add_argument("--index", type=int, choices=range(5))
    p.add_argument("--case")
    p.add_argument("--arm", choices=list(ARMS))
    a = p.parse_args()
    if a.action == "batch":
        batch(a.index)
    else:
        run_async(one(next(c for c in cases() if c.id == a.case), a.arm))


if __name__ == "__main__":
    main()
