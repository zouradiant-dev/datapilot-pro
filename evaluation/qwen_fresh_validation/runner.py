"""Reuse the frozen batch driver; only replace its read-only telemetry sampler."""

import json
import subprocess
from types import SimpleNamespace

from .common import OUT, ROOT, module, write_new

impl = module("runner")
impl.__package__ = __package__


def popen(args, **kwargs):
    if len(args) > 1 and str(args[1]).replace("\\", "/").endswith(
        "qwen_expanded_quality/resource_monitor.py"
    ):
        args = [args[0], str(ROOT / "evaluation/qwen_fresh_validation/monitor.py"), *args[2:]]
    return subprocess.Popen(args, **kwargs)


impl.subprocess = SimpleNamespace(
    Popen=popen, STDOUT=subprocess.STDOUT, TimeoutExpired=subprocess.TimeoutExpired
)

if __name__ == "__main__":
    if (OUT / "STOP").exists() or (OUT / "stopped.json").exists():
        raise ValueError("STOP: no new dispatch permitted")
    # The standalone one entry must obey the same stop/unknown guard as batch mode.
    for path in (OUT / "dispatch").glob("*.json"):
        score = OUT / "scores" / path.name
        row = json.loads(score.read_bytes()) if score.exists() else None
        if row is None or row.get("safety_violations") or row.get("infrastructure_failure"):
            write_new(
                OUT / "stopped.json",
                {
                    "reason": "Prior dispatch unresolved or unsafe; no automatic replay",
                    "intent": path.name,
                },
            )
            raise ValueError("Prior dispatch requires conservative stop")
    impl.main()
