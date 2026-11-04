"""Public controls for new candidate identity and independent scorer profiles."""

import json

import pytest

from evaluation.p7_v3_current import candidate_binding as binding


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    for name in ("pyproject.toml", "README.md", "uv.lock", "alembic.ini", "Dockerfile"):
        (root / name).write_text("public fixture\n", encoding="utf-8")
    manifest = root / "docs/research/p7-intent-corpus-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    cases = root / "tests/fixtures/public.jsonl"
    cases.parent.mkdir(parents=True)
    cases.write_text('{"public":true}\n', encoding="utf-8")
    for policy, name in binding.SCORERS.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'SCORER_VERSION = "public-{policy}"\n', encoding="utf-8")
    source = root / "src/public.py"
    source.parent.mkdir()
    source.write_bytes(b"public = True\r\n")
    return root


def test_new_candidate_binds_raw_bytes_and_both_scorers(repository, tmp_path):
    bundle = tmp_path / "candidate"
    manifest = binding.prepare(repository, bundle)
    assert binding.verify(repository, bundle, binding.digest(manifest)) == manifest
    assert manifest["scoring_profiles"]["partial-facts-v1"]["version"] == "public-partial-facts-v1"
    assert manifest["live_allowed"] is False
    assert (bundle / "snapshot/src/public.py").read_bytes() == b"public = True\r\n"
    assert (bundle / "snapshot/README.md").is_file()
    assert (bundle / "snapshot/tests/fixtures/public.jsonl").is_file()
    assert (bundle / "snapshot/docs/research/p7-intent-corpus-manifest.json").is_file()
    with pytest.raises(FileExistsError):
        binding.prepare(repository, bundle)


@pytest.mark.parametrize("change", ["source", "snapshot", "manifest", "new-file", "scorer"])
def test_candidate_rejects_drift(repository, tmp_path, change):
    bundle = tmp_path / "candidate"
    manifest = binding.prepare(repository, bundle)
    if change == "manifest":
        (bundle / "manifest.json").write_text(json.dumps(manifest | {"live_allowed": True}))
    else:
        path = {
            "source": repository / "src/public.py",
            "snapshot": bundle / "snapshot/src/public.py",
            "new-file": repository / "tests/fixtures/new.jsonl",
            "scorer": repository / binding.SCORERS["partial-facts-v1"],
        }[change]
        path.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="identity changed|closure drift|snapshot drift"):
        binding.verify(repository, bundle, binding.digest(manifest))
