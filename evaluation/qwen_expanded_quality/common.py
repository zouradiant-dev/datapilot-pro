"""Fixed evaluation bindings; reuse prior helpers in private module instances, no file edits."""

import importlib.util
import json
from collections import Counter
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from evaluation.qwen_business_pilot import common as prior
from evaluation.qwen_business_pilot.contracts import Case as PriorCase
from evaluation.qwen_business_pilot.contracts import invoice_gold

ROOT, ARMS, sha, write_new = prior.ROOT, prior.ARMS, prior.sha, prior.write_new
HERE = ROOT / "evaluation/qwen_expanded_quality"
OUT = ROOT / "artifacts/p7/qwen-expanded-v1"


class Case(PriorCase):
    id: str = Field(pattern=r"^ex\d{3}$")
    split: str = Field(pattern=r"^(dev|validation)$")
    scenario: str
    goal_unsupported: bool | None
    classification: str
    preflight: str | None
    metric_input: dict[str, str] | None
    wrong_sources: list[str]

    @model_validator(mode="after")
    def numeric_gold(self):
        if self.metric:
            x = SimpleNamespace(csv=self.metric_input["csv"], metric_gold=self.metric_input)
            if str(invoice_gold(x)) != self.metric_input["value"]:
                from decimal import Decimal

                if invoice_gold(x) != Decimal(self.metric_input["value"]):
                    raise ValueError("Independent Decimal differs from numeric Gold")
        return self


def cases():
    raw = json.loads((HERE / "cases.json").read_bytes())
    result = [Case.model_validate(c) for c in raw["cases"]]
    assert len(result) == 100 and len({c.id for c in result}) == 100
    assert set(Counter(c.category for c in result).values()) == {10}
    assert all(
        sum(c.split == "dev" for c in result if c.category == k) == 2
        for k in {c.category for c in result}
    )
    return result


def borrowed(name):
    # Fixed local frozen evaluation code, not a model-selected module or code path.
    spec = importlib.util.spec_from_file_location(
        "evaluation.qwen_business_pilot._expanded_" + name,
        ROOT / "evaluation/qwen_business_pilot" / (name + ".py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = borrowed("common")
BASE.OUT = OUT
BASE.corpus_id = lambda c: str(uuid5(NAMESPACE_URL, "datapilot:expanded-v1:" + c.id))
BASE.run_id = lambda c, a: str(uuid5(NAMESPACE_URL, "datapilot:expanded-v1:" + a + ":" + c.id))
run_id = BASE.run_id


def select(case):
    BASE.load = lambda: SimpleNamespace(
        owner="expanded-public-v1",
        dataset_name="expanded-v1-" + case.id,
        metric_gold=case.metric_input,
        noise={},
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
        next(
            c
            for c in rows
            if c.category == cat and c.id == sorted(x.id for x in rows if x.category == cat)[i]
        )
        for i in range(2 if split == "dev" else 8)
        for cat in cats
    ]


def verify():
    reg = json.loads((OUT / "registration-r2.json").read_bytes())
    if sha(OUT / "registration.json") != reg["parent_registration_sha256"]:
        raise ValueError("Original Gold registration changed")
    for name, expected in reg["files"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("Evaluation/product freeze changed: " + name)
    return reg
