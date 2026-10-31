"""Host policy is local configuration, never a browser request DTO."""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

ROOT = Path(__file__).resolve().parents[3]


def private_directory(path: Path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Private storage cannot be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform == "win32":
        import csv
        import io

        result = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True
        )
        sid = next(csv.reader(io.StringIO(result.stdout.strip())))[1]
        if not sid.startswith("S-1-"):
            raise ValueError("Cannot establish host storage identity")
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
            capture_output=True,
            check=True,
        )
    else:
        path.chmod(0o700)
    return path.resolve()


class HostPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    owner: str = Field(default="local-user", min_length=1, max_length=64)
    secret: SecretStr
    data_dir: Path
    api_host: str = "127.0.0.1:8000"
    ui_origin: str = "http://127.0.0.1:8501"
    max_workers: int = Field(default=1, ge=1, le=2)
    max_pending: int = Field(default=20, ge=1, le=100)
    ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    telemetry: str = "off"
    rag_embedding_profile: Literal["qwen3-cpu-v1", "qwen3-cuda-fp16-v1"] | None = None

    def object_path(self, ref):
        import re

        if not re.fullmatch(r"[a-f0-9-]{36}/[\w .-]{1,128}", ref):
            raise ValueError("Invalid private object reference")
        root = self.data_dir.resolve() / "objects"
        path = root / ref
        if (
            root.is_symlink()
            or path.parent.is_symlink()
            or path.is_symlink()
            or not root.resolve().is_relative_to(self.data_dir.resolve())
            or not path.resolve().is_relative_to(root.resolve())
        ):
            raise ValueError("Object escaped private storage")
        return path


def load_policy(path: Path | None = None):
    path = Path(path or os.environ.get("DATAPILOT_WEB_HOST_FILE", ROOT / "artifacts/web/host.json"))
    if path.is_symlink() or path.stat().st_size > 16384:
        raise ValueError("Invalid local host policy file")
    return HostPolicy.model_validate_json(path.read_bytes())


def bootstrap(path: Path, *, api_host="127.0.0.1:8000", ui_origin="http://127.0.0.1:8501"):
    path = Path(path)
    private_directory(path.parent)
    if path.exists():
        return load_policy(path)
    policy = HostPolicy(
        secret=SecretStr(secrets.token_urlsafe(48)),
        data_dir=path.parent.resolve(),
        api_host=api_host,
        ui_origin=ui_origin,
    )
    body = policy.model_dump(mode="json")
    body["secret"] = policy.secret.get_secret_value()
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(body, indent=2))
    if sys.platform != "win32":
        path.chmod(0o600)
    return policy
