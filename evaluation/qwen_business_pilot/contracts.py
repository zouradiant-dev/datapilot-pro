"""Closed pre-registration contracts; the worker never receives Gold or scorer keys."""

import csv
import io
from collections import Counter
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^qc\d{2}$")
    category: str
    query: str = Field(min_length=1, max_length=512)
    doc_query: str | None = Field(default=None, max_length=512)
    documents: dict[str, str]
    required: list[str]
    relevant: list[str]
    facts: list[list[str | None]]
    supplementary: list[list[str | None]] = Field(default_factory=list)
    expected_facts: list[str]
    expected_status: str = Field(pattern=r"^(completed|partial|unavailable|blocked)$")
    metric: bool = False
    causal: bool = False
    foreign_owner: bool = False
    safety: str | None = None

    @model_validator(mode="after")
    def consistent(self):
        if not self.required or not set(self.required) <= set(self.documents):
            raise ValueError("Required identities must name actual predeclared sources")
        if not set(self.relevant) <= set(self.documents):
            raise ValueError("Unknown relevance Gold")
        ids = []
        for fact in self.facts + self.supplementary:
            if len(fact) != 3:
                raise ValueError("Facts need identity, source and literal quote")
            id_, source, quote = fact
            ids.append(id_)
            if (source is None) != (quote is None):
                raise ValueError("Missing evidence must stay explicitly missing")
            if source and (source not in self.documents or quote not in self.documents[source]):
                raise ValueError("Gold quote absent from its own declared source")
        if len(set(ids)) != len(ids) or not set(self.expected_facts) <= {
            f[0] for f in self.facts if f[1] is not None
        }:
            raise ValueError("Ambiguous fact identities")
        if self.expected_status == "completed" and set(self.expected_facts) != {
            f[0] for f in self.facts
        }:
            raise ValueError("Complete needs every declared fact")
        if self.metric != bool(self.doc_query):
            raise ValueError("Only combined cases may bind a distinct host document subgoal")
        return self


class Pilot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: str
    seed: int
    owner: str
    dataset_name: str
    csv: str
    metric_gold: dict[str, str]
    noise: dict[str, str]
    cases: list[Case] = Field(min_length=16, max_length=16)

    @model_validator(mode="after")
    def independent_shape(self):
        if len({c.id for c in self.cases}) != 16 or set(
            Counter(c.category for c in self.cases).values()
        ) != {2}:
            raise ValueError("Exactly eight categories, two independent cases each")
        if any(set(c.documents) & set(self.noise) for c in self.cases):
            raise ValueError("Noise cannot overwrite an authoritative source")
        if invoice_gold(self) != Decimal(self.metric_gold["value"]):
            raise ValueError("Independent numeric Gold differs from immutable CSV rows")
        return self


def invoice_gold(pilot):
    rows = csv.DictReader(io.StringIO(pilot.csv))
    return sum(
        (
            Decimal(r["amount_cents"]) / Decimal(100)
            for r in rows
            if r["payment_status"] == "paid"
            and r["currency"] == pilot.metric_gold["unit"]
            and pilot.metric_gold["start"] <= r["invoice_date"] < pilot.metric_gold["end_exclusive"]
        ),
        Decimal(0),
    )
