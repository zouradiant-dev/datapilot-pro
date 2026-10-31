"""Bounded paired host harness. Uses the original Durable/Inspector, no paid transport."""

import argparse
import json
import subprocess
import sys
import time

from datapilot.cli import json_default
from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.persistence.backend import Backend, DurableArtifacts, execute
from datapilot.persistence.inspection import inspect_run
from datapilot.persistence.session import run_async, run_durable

from .common import ARMS, OUT, ROOT, load, run_id, scopes, sha, write_new
from .prepare import environment, verify_registration
from .scoring import score

sys.path.insert(0, str(ROOT / "scripts"))
from p7_business_scoring import sign_collection  # noqa: E402
from report_recovery_probe import ReportDecisions  # noqa: E402


def encoded(value):
    return json.loads(json.dumps(value, default=json_default))


async def one(case, arm):
    verify_registration()
    seal = json.loads((OUT / "bindings-seal.json").read_bytes())
    assert sha(OUT / "bindings.json") == seal["sha256"]
    binding = json.loads((OUT / "bindings.json").read_bytes())
    _, settings = environment()
    p = load()
    rag, report = scopes(case, arm, binding)
    id_ = run_id(case, arm)
    key = (OUT / "collector-key-private.bin").read_bytes()
    write_new(
        OUT / "dispatch" / f"{case.id}-{arm}.json",
        {
            "run_id": id_,
            "case_sha256": digest(case),
            "arm": arm,
            "registration_sha256": sha(OUT / "registration.json"),
            "bindings_sha256": seal["sha256"],
            "paid_authorized": False,
        },
    )
    begin = time.perf_counter()
    payload = {"case_id": case.id, "case_sha256": digest(case), "arm": arm, "run_id": id_}
    try:
        result = await run_durable(
            settings,
            id_,
            case.query,
            owner=p.owner,
            rag_scope=rag,
            report_scope=report,
            transport=ReportDecisions(case.doc_query or case.query),
        )
        snapshot = await inspect_run(
            settings, id_, p.owner, case.query, report_scope=report, rag_scope=rag
        )
        if snapshot["unknown"] or snapshot["report"] is None:
            raise AgentFailure("EVALUATION_INTEGRITY", "Inspector found unknown/unverified report")
        backend = Backend(settings.runtime_database_url.get_secret_value(), id_, p.owner)
        try:
            store = DurableArtifacts(backend)
            artifacts = store.export()
            with backend.transaction() as conn:
                stored_manifest = backend.authorize(conn)["manifest"]
                calls = [
                    dict(row)
                    for row in execute(
                        conn,
                        "SELECT * FROM execution.calls WHERE run_id=:r ORDER BY call_key",
                        r=id_,
                    ).mappings()
                ]
        finally:
            backend.close()
        payload.update(
            stage="runtime",
            inspector_verified=True,
            result=encoded(result),
            snapshot=encoded(snapshot),
            manifest=encoded(stored_manifest),
            artifacts=encoded(artifacts),
            calls=encoded(calls),
        )
    except AgentFailure as exc:
        payload.update(
            stage="preflight" if case.foreign_owner else "runtime",
            error=exc.error.model_dump(),
            inspector_verified=False,
        )
    payload["seconds"] = time.perf_counter() - begin
    signed = sign_collection(payload, key)
    write_new(OUT / "collections" / f"{case.id}-{arm}.json", signed)
    rated = score(case, arm, signed, key, binding)
    write_new(OUT / "scores" / f"{case.id}-{arm}.json", rated)
    print(
        json.dumps(
            {
                "case_id": case.id,
                "arm": arm,
                "status": rated["actual_status"],
                "strict": rated["strict_correct"],
                "safety": rated["safety_violations"],
            }
        )
    )


def run():
    verify_registration()
    if list((OUT / "dispatch").glob("*.json")):
        raise ValueError("Pilot already dispatched; no automatic reruns or unknown recovery")
    rows = [{"case_id": c.id, "arm": a, "status": "not_run"} for c in load().cases for a in ARMS]
    write_new(OUT / "planned.json", rows)
    for i, case in enumerate(load().cases):
        for arm in list(ARMS) if i % 2 == 0 else list(reversed(ARMS)):
            if (OUT / "STOP").exists():
                return
            # A separate host process bounds native imports and keeps each run independent.
            log = OUT / "logs" / f"{case.id}-{arm}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("x", encoding="utf-8") as stream:
                try:
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            __package__ + ".runner",
                            "one",
                            "--case",
                            case.id,
                            "--arm",
                            arm,
                        ],
                        cwd=ROOT,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        timeout=360,
                    )
                except subprocess.TimeoutExpired:
                    write_new(
                        OUT / "stopped.json",
                        {"case_id": case.id, "arm": arm, "reason": "Host process timeout/unknown"},
                    )
                    return
            path = OUT / "scores" / f"{case.id}-{arm}.json"
            if result.returncode != 0 or not path.exists():
                write_new(
                    OUT / "stopped.json",
                    {
                        "case_id": case.id,
                        "arm": arm,
                        "reason": "Collector/scorer/infrastructure process failed",
                        "returncode": result.returncode,
                    },
                )
                return
            observation = json.loads(path.read_bytes())
            if observation["safety_violations"] or observation["infrastructure_failure"]:
                write_new(
                    OUT / "stopped.json",
                    {
                        "case_id": case.id,
                        "arm": arm,
                        "reason": observation["safety_violations"]
                        or observation["error_categories"],
                    },
                )
                return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["run", "one"])
    parser.add_argument("--case")
    parser.add_argument("--arm", choices=list(ARMS))
    args = parser.parse_args()
    if args.action == "run":
        run()
    else:
        case = next(c for c in load().cases if c.id == args.case)
        run_async(one(case, args.arm))


if __name__ == "__main__":
    main()
