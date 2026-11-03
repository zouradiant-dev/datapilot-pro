"""Minimal current-source container adapter; no second Runner/Runtime."""

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from p7_smoke_pack import DOCKER
from p7_smoke_run import checked_process
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
MAN = ROOT / "artifacts/p7/final-evaluation-v1/current-evaluation-manifest.json"
NETWORK = "datapilot-p7-current-v1_default"


def build_command(
    config,
    folder,
    mode,
    action,
    values,
    product,
    deadline,
    permit_path=None,
    worker_name="current_worker.py",
):
    manifest = json.loads(MAN.read_text(encoding="utf-8"))
    snapshot = (ROOT / manifest["source_snapshot"]).resolve()
    if not snapshot.is_dir():
        raise ValueError("snapshot missing")
    env = {"PYTHONUTF8": "1", "DATAPILOT_LLM_MODE": mode}
    for role in ["reader", "upload_reader", "runtime", "rag_reader", "registry"]:
        key = "DATAPILOT_" + role.upper() + "_DATABASE_URL"
        u = make_url(values[key]).set(host="datapilot-p7-current-v1-postgres-1", port=5432)
        env[key] = u.render_as_string(hide_password=False)
    if worker_name == "mock_worker.py":
        env["DATAPILOT_API_KEY"] = "test-mock-only"
    elif mode == "live":
        import dotenv

        env["DATAPILOT_API_KEY"] = os.environ.get("DATAPILOT_API_KEY") or dotenv.dotenv_values(
            ROOT / ".env"
        ).get("DATAPILOT_API_KEY", "")
    path = folder / "private.env"
    path.write_text("\n".join(k + "=" + v for k, v in env.items()) + "\n", encoding="utf-8")
    name = "datapilot-v3-current-" + config["run_id"][:12]
    command = [
        DOCKER,
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--network",
        NETWORK,
        "--env-file",
        str(path.resolve()),
    ]
    mounts = [
        (snapshot / "src", "/app/src"),
        (folder / "config.json", "/bench/config.json"),
        (ROOT / ".cache/rag-models", "/app/.cache/rag-models"),
        (ROOT / "artifacts/p7/dev-smoke-v1/empty-fixtures", "/app/tests/fixtures"),
        (ROOT / "artifacts/p7/dev-smoke-v1/empty-fixtures", "/app/scripts"),
    ]
    mounts.append(
        (
            Path(__file__).resolve().parent / "current_worker.py",
            "/bench/current_worker.py",
        )
    )
    if worker_name != "current_worker.py":
        mounts.append((Path(__file__).resolve().parent / worker_name, "/bench/" + worker_name))
    for filename in ["p7_business_runtime.py", "report_recovery_probe.py"]:
        mounts.append((snapshot / "scripts" / filename, "/bench/" + filename))
    if permit_path:
        mounts.append((permit_path, "/bench/permit.json"))
    for host, target in mounts:
        command += ["-v", str(Path(host).resolve()) + ":" + target + ":ro"]
    command += [
        "--entrypoint",
        "/app/.venv/bin/python",
        "datapilot-current:local",
        "/bench/" + worker_name,
        action,
        "--config",
        "/bench/config.json",
        "--config-sha",
        hashlib.sha256((folder / "config.json").read_bytes()).hexdigest(),
        "--mode",
        mode,
    ]
    if permit_path:
        command += ["--permit", "/bench/permit.json"]
    return command, name, snapshot


def run(
    config,
    folder,
    mode,
    action,
    values,
    product,
    deadline,
    permit_path=None,
    worker_name="current_worker.py",
):
    command, name, snapshot = build_command(
        config, folder, mode, action, values, product, deadline, permit_path, worker_name
    )
    global_stop = ROOT / "artifacts/p7/final-evaluation-v1/STOP"
    campaign_stop = folder.parent / "STOP"
    if global_stop.exists() or campaign_stop.exists():
        raise ValueError("STOP present before dispatch")
    output, error, code = checked_process(
        command,
        env=os.environ.copy(),
        name=name,
        deadline=deadline,
        stop_path=campaign_stop,
    )
    for _k, v in {**values}.items():
        if len(v) > 8:
            output = output.replace(v, "[REDACTED]")
            error = error.replace(v, "[REDACTED]")
    (folder / (action + "-process.json")).write_text(
        json.dumps(
            {
                "exit_code": code,
                "stdout": output,
                "stderr": error,
                "command_redacted": [("***" if "--env-file" in x else x) for x in command],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if code:
        raise RuntimeError("Candidate process failed; see process.json")
    return json.loads(output)


def env_for(values):
    return {"PYTHONUTF8": "1"}
