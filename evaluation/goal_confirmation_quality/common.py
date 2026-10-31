"""Frozen public contract probes, not a model/harness implementation."""

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
OUT = ROOT / "artifacts/p7/goal-confirmation-quality-v1"


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^gc7-\d{3}$")
    category: str
    query: str = Field(min_length=1, max_length=512)
    source_names: list[str] = Field(max_length=3)
    metric: str | None
    window: dict[str, str] | None
    purpose: str | None
    facts: list[dict[str, str]] = Field(max_length=8)
    foreign_dataset: bool


def cases():
    rows = [Case.model_validate(x) for x in json.loads((HERE / "cases.json").read_bytes())]
    assert len(rows) == 24 and len({c.id for c in rows}) == 24
    return rows


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def verify():
    seal = json.loads((OUT / "registration.json").read_bytes())
    assert all(sha(ROOT / p) == h for p, h in seal["files"].items()), "Freeze mismatch"
    assert not (OUT / "STOP").exists(), "STOP is monotonic; no replay"
    return seal


def normalized(text, numeric=False):
    text = re.sub(r"[\W_]+", "", text.casefold())
    return re.sub(r"\d+", "#", text) if numeric else text
