"""Actual API/worker OS processes and PG/MCP; no paid model invocation."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from test_web_postgres import import_sample

from datapilot.db.management import management_url
from datapilot.web.config import bootstrap

pytestmark = pytest.mark.integration
ROOT = Path(__file__).parents[1]


def start_api(path, *, dispatch):
    child = subprocess.Popen(
        [
            sys.executable,
            "scripts/web_recovery_probe.py",
            "api",
            str(path),
            *(["--dispatch"] if dispatch else []),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    return child


def connect(path, child):
    policy = json.loads(path.read_text(encoding="utf-8"))
    c = httpx.Client(
        base_url="http://" + policy["api_host"],
        timeout=120,
        trust_env=False,
        headers={"Origin": policy["ui_origin"]},
    )
    for _ in range(100):
        assert child.poll() is None, "API exited during startup"
        try:
            r = c.post("/api/v1/session", headers={"X-DataPilot-Host-Key": policy["secret"]})
            if r.status_code == 200:
                c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
                return c
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise AssertionError("API startup timeout")


@pytest.mark.parametrize(
    "cut,expected", [("report_metric_committed", "completed"), ("model_issued", "blocked")]
)
def test_api_crash_restart_committed_replay_and_unknown(pg_settings, tmp_path, cut, expected):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    path = tmp_path / "host.json"
    bootstrap(path, api_host=f"127.0.0.1:{port}")
    initial = json.loads(path.read_text(encoding="utf-8"))
    initial["owner"] = "restart-" + uuid4().hex[:12]
    path.write_text(json.dumps(initial), encoding="utf-8")
    child = start_api(path, dispatch=False)
    c = connect(path, child)
    admin = sa.create_engine(management_url("owner"), hide_parameters=True)
    try:
        body = import_sample(c)
        body["require_review"] = False
        key = uuid4().hex
        ack = c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": key})
        assert ack.status_code == 200, ack.text
        id_ = ack.json()["run_id"]
        worker = subprocess.run(
            [
                sys.executable,
                "scripts/web_recovery_probe.py",
                "worker",
                str(path),
                "--run-id",
                id_,
                "--cut",
                cut,
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=90,
        )
        assert worker.returncode == 91
        with admin.connect() as conn:
            before = conn.execute(
                sa.text(
                    "SELECT call_key,status FROM execution.calls WHERE run_id=:r ORDER BY call_key"
                ),
                {"r": id_},
            ).all()
            ledger_before = conn.execute(
                sa.text("SELECT payload FROM execution.ledger WHERE run_id=:r"), {"r": id_}
            ).scalar_one()
            evidence_before = conn.execute(
                sa.text(
                    "SELECT evidence_id,body_sha256 FROM "
                    "catalog.evidence WHERE body->'request'->>'goal_id'='revenue' "
                    "AND dataset_id=:d"
                ),
                {"d": body["metrics"][0]["dataset_id"]},
            ).all()
            verification_before = conn.execute(
                sa.text(
                    "SELECT verification_id,body_sha256,verdict FROM catalog.verification_runs "
                    "WHERE dataset_id=:d ORDER BY verification_id"
                ),
                {"d": body["metrics"][0]["dataset_id"]},
            ).all()
        c.close()
        child.kill()
        child.wait(timeout=10)
        child = start_api(path, dispatch=True)
        c = connect(path, child)
        # Same logical create remains the same run across the API process boundary.
        replay = c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": key})
        assert replay.json() == ack.json(), replay.text
        for _ in range(60):
            state = c.get(f"/api/v1/tasks/{id_}")
            assert state.status_code == 200, state.text
            if state.json()["status"] in {"completed", "blocked", "failed"}:
                break
            time.sleep(0.5)
        assert state.json()["status"] == expected, state.text
        with admin.connect() as conn:
            after = conn.execute(
                sa.text(
                    "SELECT call_key,status FROM execution.calls WHERE run_id=:r ORDER BY call_key"
                ),
                {"r": id_},
            ).all()
            ledger = conn.execute(
                sa.text("SELECT payload FROM execution.ledger WHERE run_id=:r"), {"r": id_}
            ).scalar_one()
            evidence = conn.execute(
                sa.text(
                    "SELECT evidence_id,body_sha256 FROM "
                    "catalog.evidence WHERE body->'request'->>'goal_id'='revenue' "
                    "AND dataset_id=:d"
                ),
                {"d": body["metrics"][0]["dataset_id"]},
            ).all()
            verification = conn.execute(
                sa.text(
                    "SELECT verification_id,body_sha256,verdict FROM catalog.verification_runs "
                    "WHERE dataset_id=:d ORDER BY verification_id"
                ),
                {"d": body["metrics"][0]["dataset_id"]},
            ).all()
        if expected == "completed":
            assert evidence == evidence_before  # Same original P3 Verified IDs/hashes.
            assert verification == verification_before and verification[0][2] == "verified"
            report = c.get(f"/api/v1/tasks/{id_}/report")
            assert report.status_code == 200, report.text
            assert report.json()["facts"][0]["evidence_id"] == evidence[0][0]
            assert report.json()["facts"][0]["verification_id"] == verification[0][0]
            assert len([r for r in after if r[0].startswith("model:")]) == len(
                [r for r in before if r[0].startswith("model:")]
            )
            assert ledger["state"]["receipts"] == ledger_before["state"]["receipts"]
            for account, item in ledger_before["state"]["accounts"].items():
                assert ledger["state"]["accounts"][account] == item
        else:
            assert state.json()["error"]["code"] == "RECOVERY_UNCERTAIN"
            assert state.json()["error"]["manual_action_required"]
            assert len(after) == len(before)
            assert any(status == "uncertain" for _, status in after)
            root = ledger["state"]["accounts"]["root"]["usage"]
            assert root["total_tokens"] > 0 and root["calls"] > 0
            assert (
                c.post(
                    f"/api/v1/tasks/{id_}/resume", json={}, headers={"Idempotency-Key": uuid4().hex}
                ).status_code
                == 403
            )
    finally:
        c.close()
        admin.dispose()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
