import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(".")
BASE = Path("artifacts/p7/final-evaluation-v1")
MAN = json.loads((BASE / "current-evaluation-manifest.json").read_text(encoding="utf-8"))


def verify_manifest(root, snapshot, manifest):
    for rel, rec in manifest["files"].items():
        p = root / rel
        sp = snapshot / rel
        if not p.is_file() or not sp.is_file():
            raise ValueError("missing source: " + rel)
        if hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != rec["lf_sha256"]:
            raise ValueError("current source LF drift: " + rel)
        if hashlib.sha256(sp.read_bytes()).hexdigest() != rec["lf_sha256"]:
            raise ValueError("snapshot drift: " + rel)
    for rel, h in manifest["evaluation_files"].items():
        if hashlib.sha256((root / rel).read_bytes()).hexdigest() != h:
            raise ValueError("evaluation drift: " + rel)
    return True


def verify_current():
    return verify_manifest(ROOT, ROOT / MAN["source_snapshot"], MAN)


def run():
    verify_current()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "evaluation/p7_v3"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import scorer as current_scorer
    import v3_common
    import v3_probe
    import v3_score
    from container_adapter import run as current_container_action

    v3_score.call_integrity = current_scorer.current_call_integrity
    old = json.loads(Path("artifacts/p7/dev-smoke-v1/implementation-freeze-v1.json").read_bytes())
    product = {
        **old,
        "source_snapshot": str(BASE / "current-source-snapshot"),
        "docker": {**old["docker"], "image_id": "datapilot-current:local"},
    }
    v3_probe.BASE = BASE
    v3_common.BASE = BASE
    v3_probe.parent_freeze = lambda: (
        {
            "freeze_id": "p7-current-evaluation-binding",
            "manifest_sha256": MAN["source_manifest_lf"],
        },
        product,
    )
    v3_probe.container_action = current_container_action
    values = json.loads(
        (ROOT / "artifacts/p7/current-pg/private/environment.json").read_text(encoding="utf-8")
    )
    v3_probe.infrastructure = lambda _: values
    v3_probe.main()
    print("CONTROL_OK", BASE / "private/probe")


if __name__ == "__main__":
    if sys.argv[1:] == ["run"]:
        run()
    else:
        print("usage: current_binding.py run")
