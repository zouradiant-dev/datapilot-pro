import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("evaluation/p7_v3").resolve()))
from current_binding import verify_current, verify_manifest


def test_current_binding_accepts_current_lf_source():
    assert verify_current() is True


def test_current_binding_rejects_wrong_source_bytes(tmp_path):
    root = tmp_path / "root"
    snap = tmp_path / "snap"
    root.mkdir()
    snap.mkdir()
    content = b"public synthetic source\n"
    (root / "src.py").write_bytes(content)
    (snap / "src.py").write_bytes(content)
    manifest = {
        "files": {"src.py": {"lf_sha256": hashlib.sha256(content).hexdigest()}},
        "evaluation_files": {},
    }
    assert verify_manifest(root, snap, manifest) is True
    (root / "src.py").write_bytes(b"wrong\n")
    with pytest.raises(ValueError, match="current source LF drift"):
        verify_manifest(root, snap, manifest)


def test_current_binding_rejects_snapshot_drift(tmp_path):
    root = tmp_path / "root"
    snap = tmp_path / "snap"
    root.mkdir()
    snap.mkdir()
    content = b"public synthetic source\n"
    (root / "src.py").write_bytes(content)
    (snap / "src.py").write_bytes(content)
    manifest = {
        "files": {"src.py": {"lf_sha256": hashlib.sha256(content).hexdigest()}},
        "evaluation_files": {},
    }
    (snap / "src.py").write_bytes(b"snapshot changed\n")
    with pytest.raises(ValueError, match="snapshot drift"):
        verify_manifest(root, snap, manifest)
