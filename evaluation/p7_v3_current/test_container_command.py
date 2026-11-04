import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import container_adapter
from container_adapter import build_command


def test_command_mounts_current_snapshot_and_isolated_network(
    tmp_path, monkeypatch, synthetic_binding
):
    root, expected_snapshot, _ = synthetic_binding
    monkeypatch.setattr(container_adapter, "ROOT", root)
    monkeypatch.setattr(
        container_adapter,
        "MAN",
        root / "artifacts/p7/final-evaluation-v1/current-evaluation-manifest.json",
    )
    values = {
        f"DATAPILOT_{role.upper()}_DATABASE_URL": (
            f"postgresql+psycopg://datapilot_{role}:public-test-only@127.0.0.1:55499/datapilot_test_public"
        )
        for role in ("reader", "upload_reader", "runtime", "rag_reader", "registry")
    }
    product = {"docker": {"image_id": "datapilot-current:local"}}
    config = {
        "run_id": "command-test",
        "case_id": "probe-v3-completed",
        "synthetic_probe": True,
        "profile": {},
        "report_scope": {},
        "rag_scope": None,
        "owner": "x",
        "question_sha256": "0" * 64,
    }
    folder = tmp_path / "case"
    folder.mkdir()
    (folder / "config.json").write_text(json.dumps(config))
    cmd, name, snapshot = build_command(
        config, folder, "fake", "probe", values, product, 9999999999
    )
    assert snapshot == expected_snapshot
    assert name.startswith("datapilot-v3-current-")
    assert cmd[cmd.index("--network") + 1] == "datapilot-p7-current-v1_default"
    assert "datapilot-current:local" in cmd
    mounts = [cmd[i + 1] for i, x in enumerate(cmd) if x == "-v"]
    assert any(str(snapshot / "src") + ":/app/src:ro" == m for m in mounts)
    assert any(
        str(snapshot / "scripts/p7_business_runtime.py") + ":/bench/p7_business_runtime.py:ro" == m
        for m in mounts
    )
    assert all("frozen-source-c2dd57f1294a" not in m for m in mounts)
    assert all("datapilot-p7-unified" not in m for m in mounts)
