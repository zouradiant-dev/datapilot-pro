"""Host-only P7 disposable PG17 operations; never targets the user's database.

No down/delete/volume operation exists here. Restart validates name AND label.
Private credentials/environment remain under ignored artifacts/p7/private/.
"""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "artifacts/p7/private"
NAME = "datapilot-p7-postgres-1"
IMAGE = (
    "pgvector/pgvector:0.8.6-pg17@sha256:"
    "cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f"
)
PORT = 55439
ROLES = (
    "owner",
    "seed",
    "reader",
    "ingest",
    "upload_reader",
    "registry",
    "runtime",
    "checkpoint_owner",
    "rag_ingest",
    "rag_reader",
    "web",
    "maintenance",
)


def docker(*args):
    executable = shutil.which("docker") or r"D:\downloads\DockerDesktop\resources\bin\docker.exe"
    return subprocess.run([executable, *args], capture_output=True, text=True, check=True).stdout


def environment():
    values = json.loads((PRIVATE / "environment.json").read_text(encoding="utf-8"))
    for key, value in values.items():
        if key.endswith("DATABASE_URL"):
            url = make_url(value)
            if (url.host, url.port, url.database) != ("127.0.0.1", PORT, "datapilot_p7"):
                raise ValueError("P7 environment escaped the disposable instance")
    return os.environ | values


def inspect():
    info = json.loads(docker("inspect", NAME))[0]
    if (
        info["Name"] != "/" + NAME
        or info["Config"]["Labels"].get("datapilot.p7.disposable") != "true"
        or info["Config"]["Image"] != IMAGE
    ):
        raise ValueError("Refusing operations on a non-P7 container")
    return info


def ready():
    for _ in range(40):
        info = inspect()
        if info["State"].get("Health", {}).get("Status") == "healthy":
            return
        time.sleep(1)
    raise RuntimeError("Disposable PostgreSQL did not become healthy")


def initialize():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    env_path = PRIVATE / "environment.json"
    if env_path.exists():
        raise ValueError("P7 environment already exists; do not reseed or overwrite it")
    passwords = {r: secrets.token_urlsafe(28) for r in ("admin", *ROLES)}
    values = {
        "DATAPILOT_LLM_MODE": "fake",
        "DATAPILOT_RUN_DB_TESTS": "1",
        "DATAPILOT_RUN_LIVE_TESTS": "0",
        "PYTHONUTF8": "1",
    }
    for role, password in passwords.items():
        user = "postgres" if role == "admin" else "datapilot_" + role
        values[f"DATAPILOT_{role.upper()}_DATABASE_URL"] = (
            f"postgresql+psycopg://{user}:{password}@127.0.0.1:{PORT}/datapilot_p7"
        )
        values[f"DATAPILOT_{role.upper()}_PASSWORD"] = password
    env_path.write_text(json.dumps(values, indent=2), encoding="utf-8")
    compose = {
        "services": {
            "postgres": {
                "image": IMAGE,
                "container_name": NAME,
                "labels": {"datapilot.p7.disposable": "true"},
                "environment": {
                    "POSTGRES_DB": "datapilot_p7",
                    "POSTGRES_USER": "postgres",
                    "POSTGRES_PASSWORD": passwords["admin"],
                    "POSTGRES_INITDB_ARGS": "--auth-host=scram-sha-256",
                },
                "ports": [f"127.0.0.1:{PORT}:5432"],
                "volumes": ["p7data:/var/lib/postgresql/data"],
                "healthcheck": {
                    "test": ["CMD-SHELL", "pg_isready -U postgres -d datapilot_p7"],
                    "interval": "2s",
                    "timeout": "2s",
                    "retries": 30,
                },
            }
        },
        "volumes": {"p7data": {}},
    }
    path = PRIVATE / "compose.json"
    path.write_text(json.dumps(compose, indent=2), encoding="utf-8")
    docker(
        "compose",
        "--project-name",
        "datapilot-p7",
        "--file",
        str(path),
        "up",
        "-d",
        "--pull",
        "never",
    )
    ready()
    configure()


def configure():
    inspect()
    ready()
    env = environment()
    values = json.loads((PRIVATE / "environment.json").read_text(encoding="utf-8"))
    log_path = ROOT / "artifacts/p7/isolation-setup.json"
    logs = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    for command in (["db-init"], ["migrate"], ["runtime-init"], ["seed", "--customers", "48"]):
        if any(row["command"] == command and row["exit_code"] == 0 for row in logs):
            continue
        result = subprocess.run(
            [sys.executable, "-m", "datapilot.cli", *command],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        output = result.stdout + result.stderr
        for value in values.values():
            if len(value) >= 12:
                output = output.replace(value, "[REDACTED]")
        logs.append({"command": command, "exit_code": result.returncode, "output": output})
        (ROOT / "artifacts/p7/isolation-setup.json").write_text(
            json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if result.returncode:
            raise RuntimeError("P7 setup failed; see redacted isolation-setup.json; never reseed")
    print(
        json.dumps(
            {
                "container": NAME,
                "healthy": True,
                "port": PORT,
                "new_isolated_database": True,
                "original_database_untouched": True,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["initialize", "configure", "status", "restart"])
    args = parser.parse_args()
    if args.action == "initialize":
        initialize()
    elif args.action == "configure":
        configure()
    elif args.action == "restart":
        inspect()
        docker("restart", "--time", "2", NAME)
        ready()
        print(json.dumps({"container": NAME, "actual_instance_restart": True, "healthy": True}))
    else:
        info = inspect()
        print(
            json.dumps(
                {
                    "container": NAME,
                    "state": info["State"]["Status"],
                    "health": info["State"].get("Health", {}),
                }
            )
        )


if __name__ == "__main__":
    main()
