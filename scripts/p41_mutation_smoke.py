"""One P4.1 reference-check mutation, confined to a child process; never edits source."""

import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    repo = Path(__file__).resolve().parents[1]
    path = repo / "src/datapilot/orchestration/coordinator.py"
    source = path.read_bytes()
    target = 'if task.worker in {"analysis", "report"} and ('
    if source.decode("utf-8").count(target) != 1:
        raise RuntimeError("Expected exactly one reference guard; review mutation for changed code")
    mutated = source.decode("utf-8").replace(target, "if False and (", 1)
    folder = repo / "artifacts/p41"
    folder.mkdir(parents=True, exist_ok=True)
    test = (
        "tests/test_orchestration_hardening.py::"
        "test_derived_report_cannot_drop_dependency_references"
    )
    args = [
        test,
        "-q",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        "--basetemp=artifacts/p41/mutation-temp",
        "--junitxml=artifacts/p41/mutation.xml",
    ]
    # In-memory replacement exists only in this child interpreter. Its module disappears
    # on process exit; original repository bytes and installed modules are never patched.
    runner = folder / "mutation-runner.py"
    runner.write_text(
        "import pytest\nimport datapilot.orchestration.coordinator as module\n"
        f"exec(compile({mutated!r}, module.__file__, 'exec'), module.__dict__)\n"
        f"raise SystemExit(pytest.main({args!r}))\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-B", str(runner)],
        cwd=repo,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    (folder / "mutation.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    suite = next(ET.parse(folder / "mutation.xml").getroot().iter("testsuite"))
    summary = {
        "mutation": "remove derived artifact dependency reference check in subprocess memory",
        "exit_code": result.returncode,
        "tests": int(suite.attrib["tests"]),
        "failures": int(suite.attrib["failures"]),
        "errors": int(suite.attrib["errors"]),
        "source_unchanged": path.read_bytes() == source,
        "source_sha256": hashlib.sha256(source).hexdigest(),
    }
    (folder / "mutation-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    if (
        summary["exit_code"],
        summary["tests"],
        summary["failures"],
        summary["errors"],
        summary["source_unchanged"],
    ) != (1, 1, 1, 0, True):
        raise RuntimeError("Mutation smoke did not produce the required single test failure")


if __name__ == "__main__":
    main()
