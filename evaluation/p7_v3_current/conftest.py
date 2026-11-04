"""Public synthetic bindings; no private campaign, credentials, or sealed Gold."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def synthetic_binding(tmp_path, monkeypatch):
    import current_binding

    root = tmp_path / "public-repository"
    base = root / "artifacts/p7/final-evaluation-v1"
    snapshot = base / "snapshot"
    snapshot.mkdir(parents=True)
    (root / "src").mkdir()
    (snapshot / "src").mkdir()
    content = b"public_synthetic_source = True\n"
    for parent in (root, snapshot):
        (parent / "src/public.py").write_bytes(content)
    manifest = {
        "source_snapshot": snapshot.relative_to(root).as_posix(),
        "source_manifest_lf": hashlib.sha256(content).hexdigest(),
        "files": {"src/public.py": {"lf_sha256": hashlib.sha256(content).hexdigest()}},
        "evaluation_files": {},
    }
    (base / "current-evaluation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(current_binding, "ROOT", root)
    monkeypatch.setattr(current_binding, "BASE", base)
    return root, snapshot, manifest
