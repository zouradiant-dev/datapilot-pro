"""Fixed deployment attestation. This CLI is never registered as a model/MCP tool."""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import platform
import sys
from pathlib import Path

from packaging.requirements import Requirement

from datapilot.contracts import AgentFailure
from datapilot.rag.models import ROOT

PREFIX = ROOT / ".venv-qwen"
MANIFEST = PREFIX / "datapilot-runtime.json"
PYTHON = {"win32": "3.11.16", "linux": "3.11.14"}


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def executable():
    return PREFIX / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def lock_file():
    return (
        ROOT
        / "requirements"
        / ("qwen-mcp.lock" if sys.platform == "win32" else "qwen-mcp-linux.lock")
    )


def pinned_packages():
    expected = {}
    for line in lock_file().read_text(encoding="utf-8").splitlines():
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        req = Requirement(line.rstrip(" \\"))
        if req.marker and not req.marker.evaluate(
            {
                "python_version": "3.11",
                "python_full_version": PYTHON[sys.platform],
            }
        ):
            continue
        expected[req.name.lower().replace("_", "-")] = str(next(iter(req.specifier)).version)
    return expected


def source_hash():
    names = (
        "rag/qwen.py",
        "rag/qwen_runtime.py",
        "rag/lifecycle.py",
        "rag/mcp.py",
        "rag/models.py",
        "rag/storage.py",
        "rag/contracts.py",
        "runtime/mcp_client.py",
        "runtime/owned_process.py",
        "runtime/mcp_server.py",
    )
    files = {name: file_hash(ROOT / "src/datapilot" / name) for name in names}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def current():
    if sys.platform not in PYTHON or platform.python_version() != PYTHON[sys.platform]:
        raise ValueError("Pinned platform/Python required")
    if PREFIX.is_symlink() or Path(sys.prefix).resolve() != PREFIX.resolve():
        raise ValueError("Use the fixed deployment environment")
    if Path(sys.executable).absolute() != executable().absolute():
        raise ValueError("Interpreter differs from fixed deployment path")
    installed = {
        d.metadata["Name"].lower().replace("_", "-"): d.version
        for d in importlib.metadata.distributions()
    }
    if installed != pinned_packages():
        raise ValueError("Installed packages differ from platform lock")
    for module in ("torch", "transformers", "tokenizers"):
        origin = Path(importlib.util.find_spec(module).origin).resolve()
        if not origin.is_relative_to(PREFIX.resolve()):
            raise ValueError("Dependency loaded outside the fixed environment")
    return {
        "schema_version": "qwen-runtime-1",
        "python": platform.python_version(),
        "platform": sys.platform,
        "executable_sha256": file_hash(executable()),
        "base_executable_sha256": file_hash(Path(sys._base_executable)),
        "pyvenv_sha256": file_hash(PREFIX / "pyvenv.cfg"),
        "lock_sha256": file_hash(lock_file()),
        "packages": installed,
    }


def expected():
    try:
        if MANIFEST.is_symlink() or MANIFEST.stat().st_size > 64 * 1024:
            raise ValueError("Invalid deployment manifest")
        raw = MANIFEST.read_bytes()
        value = json.loads(raw)
        if (
            PREFIX.is_symlink()
            or value["schema_version"] != "qwen-runtime-1"
            or value["platform"] != sys.platform
            or value["python"] != PYTHON[sys.platform]
            or value["packages"] != pinned_packages()
            or value["executable_sha256"] != file_hash(executable())
            or value["pyvenv_sha256"] != file_hash(PREFIX / "pyvenv.cfg")
            or value["lock_sha256"] != file_hash(lock_file())
        ):
            raise ValueError("Deployment identity differs")
        return value, hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, KeyError, TypeError):
        raise AgentFailure(
            "EMBEDDING_NOT_READY", "Qwen deployment attestation is missing or changed"
        ) from None


def verify():
    value, sha = expected()
    try:
        if current() != value:
            raise ValueError("Actual runtime differs from deployment")
        return {
            "manifest_sha256": sha,
            "source_sha256": source_hash(),
            "python": value["python"],
            "lock_sha256": value["lock_sha256"],
        }
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        raise AgentFailure("EMBEDDING_VERSION", "Actual Qwen interpreter/packages differ") from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true", required=True)
    parser.parse_args()
    value = current()
    # Explicit trusted deployment command, refuses replacing a different binding.
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if MANIFEST.exists():
        if MANIFEST.read_text(encoding="utf-8") != encoded:
            raise ValueError("Deployment manifest exists; inspect drift before changing it")
    else:
        with MANIFEST.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(json.dumps({"status": "deployment_attested", "manifest_sha256": file_hash(MANIFEST)}))


if __name__ == "__main__":
    main()
