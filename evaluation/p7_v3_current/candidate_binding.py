"""Explicit host-side preparation of a new candidate; no Permit or execution side effects."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

DIRECTORIES = (
    "src",
    "scripts",
    "evaluation",
    "migrations",
    "requirements",
    "tests",
    ".github/workflows",
)
SUFFIXES = {
    ".py",
    ".json",
    ".jsonl",
    ".md",
    ".csv",
    ".xlsx",
    ".txt",
    ".yaml",
    ".yml",
    ".lock",
    ".in",
}
SCORERS = {
    "legacy": "evaluation/p7_v3_current/scorer.py",
    "partial-facts-v1": "evaluation/p7_v3_current/partial_evidence_scorer.py",
    "host-source-goals-v1": "evaluation/p7_v3_current/source_goal_scoring.py",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def inventory(root):
    paths = [
        root / name
        for name in (
            "pyproject.toml",
            "README.md",
            "uv.lock",
            "alembic.ini",
            "Dockerfile",
            "docs/research/p7-intent-corpus-manifest.json",
        )
    ]
    paths += sorted(root.glob("compose*.yaml"))
    for directory in DIRECTORIES:
        paths.extend(
            path
            for path in (root / directory).rglob("*")
            if path.is_file() and path.suffix in SUFFIXES
        )
    result = {}
    for path in sorted(paths):
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Candidate input escaped the repository")
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def scoring_profiles(root):
    result = {}
    for policy, name in SCORERS.items():
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        version = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "SCORER_VERSION"
                for target in node.targets
            )
        )
        result[policy] = {"version": version, "file": name}
    return result


def prepare(root, output):
    files = inventory(root)
    profiles = scoring_profiles(root)
    for profile in profiles.values():
        profile["sha256"] = files[profile["file"]]
    manifest = {
        "schema": "p7-candidate-binding-1",
        "status": "PREPARED_NOT_AUTHORIZED",
        "byte_policy": "raw-sha256",
        "files": files,
        "tree_sha256": digest(files),
        "scoring_profiles": profiles,
        "live_allowed": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    for name in files:
        path = output / "snapshot" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((root / name).read_bytes())
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify(root, output, digest(manifest))
    return manifest


def verify(root, bundle, expected_sha256):
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if digest(manifest) != expected_sha256:
        raise ValueError("Candidate manifest identity changed")
    if manifest["files"] != inventory(root):
        raise ValueError("Candidate source closure drift")
    for name, expected in manifest["files"].items():
        path = bundle / "snapshot" / name
        if not path.resolve().is_relative_to((bundle / "snapshot").resolve()):
            raise ValueError("Candidate snapshot escaped the bundle")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Candidate snapshot drift: " + name)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
    if args.action == "prepare":
        manifest = prepare(args.root, args.bundle)
    else:
        if not args.manifest_sha256:
            parser.error("verify requires --manifest-sha256 from the trusted host record")
        manifest = verify(args.root, args.bundle, args.manifest_sha256)
    print(
        json.dumps(
            {
                "manifest_sha256": digest(manifest),
                "files": len(manifest["files"]),
                "live_allowed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
