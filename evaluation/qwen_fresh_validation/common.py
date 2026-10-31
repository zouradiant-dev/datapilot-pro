"""New identities and inputs; private instances of existing evaluation helpers."""

import importlib.util
import json
from collections import Counter
from types import SimpleNamespace
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field

from evaluation.qwen_business_pilot import common as prior
from evaluation.qwen_expanded_quality.common import Case as ExpandedCase

ROOT, ARMS, sha, write_new = prior.ROOT, prior.ARMS, prior.sha, prior.write_new
HERE = ROOT / "evaluation/qwen_fresh_validation"
OUT = ROOT / "artifacts/p7/fresh-validation-v3-r2"
OWNER = "expanded-public-v1"  # Same logical test host; isolated DB and new object IDs.


class Case(ExpandedCase):
    id: str = Field(pattern=r"^fr\d{3}$")
    expected_goal_class: Literal["bounded_facts", "exhaustive_collection", "ambiguous_unresolved"]
    relationship: str
    fact_pattern: str
    intent: str


def cases():
    rows = [
        Case.model_validate(c) for c in json.loads((HERE / "cases-r2.json").read_bytes())["cases"]
    ]
    assert len(rows) == len({c.id for c in rows}) == 100
    assert set(Counter(c.category for c in rows).values()) == {10}
    assert all(
        sum(c.split == "dev" for c in rows if c.category == k) == 2
        for k in {c.category for c in rows}
    )
    return rows


def module(name, package="evaluation.qwen_expanded_quality"):
    spec = importlib.util.spec_from_file_location(
        (package if package == "evaluation.qwen_business_pilot" else __package__)
        + "._fresh_"
        + name,
        ROOT / package.replace(".", "/") / (name + ".py"),
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


BASE = module("common", "evaluation.qwen_business_pilot")
BASE.OUT = OUT
BASE.corpus_id = lambda c: str(uuid5(NAMESPACE_URL, "datapilot:fresh-v3r2:" + c.id))
BASE.run_id = lambda c, a: str(uuid5(NAMESPACE_URL, "datapilot:fresh-v3r2:" + a + ":" + c.id))
run_id = BASE.run_id


def select(case):
    BASE.load = lambda: SimpleNamespace(
        owner=OWNER, dataset_name="expanded-v1-" + case.id, metric_gold=case.metric_input, noise={}
    )


def manifest(case, arm):
    select(case)
    return BASE.manifest(case, arm)


def scopes(case, arm, bindings):
    select(case)
    b = {**bindings, "metric": bindings[case.id].get("metric")} if case.metric else bindings
    rag, report = BASE.scopes(case, arm, b)
    if case.preflight == "version":
        rag.corpora[0].index_version = "0" * 64
    elif case.preflight == "profile":
        rag.embedding_profile = "qwen3-cpu-v1" if arm == "qwen" else "qwen3-cuda-fp16-v1"
    return rag, report


def order(split):
    rows = [c for c in cases() if c.split == split]
    cats = list(dict.fromkeys(c.category for c in rows))
    return [
        sorted((c for c in rows if c.category == cat), key=lambda c: c.id)[i]
        for i in range(2 if split == "dev" else 8)
        for cat in cats
    ]


def verify():
    reg = json.loads((OUT / "registration.json").read_bytes())
    implementation = json.loads((OUT / "registration-r2.json").read_bytes())
    assert implementation["parent_data_registration_sha256"] == sha(OUT / "registration.json")
    for name, expected in implementation["files"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("Frozen source/input/evaluator changed: " + name)
    return reg
