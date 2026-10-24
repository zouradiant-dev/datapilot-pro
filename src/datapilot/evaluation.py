"""Small P7 measurement contracts. Test doubles never become Live quality evidence."""

import math
from typing import Literal

from pydantic import Field, model_validator

from datapilot.ingestion.contracts import DTO


class IntentGold(DTO):
    action: Literal["candidate", "clarify"]
    metrics: list[dict] = Field(default_factory=list, max_length=6)
    documents: bool = False

    @model_validator(mode="after")
    def coherent(self):
        if self.action == "clarify" and (self.metrics or self.documents):
            raise ValueError("Clarification gold cannot contain a runnable goal")
        return self


class IntentObservation(DTO):
    case_id: str = Field(min_length=1, max_length=80)
    strategy: Literal["rule_only", "llm_only", "hybrid"]
    transport: Literal["none", "mock", "live"]
    expected: IntentGold
    actual: IntentGold | None = None
    error_code: str | None = None
    elapsed_ms: float = Field(ge=0)
    model_calls: int = Field(default=0, ge=0)
    reported_tokens: int | None = Field(default=None, ge=0)
    provider_cache_read_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: str | None = None
    billed_cost_usd: str | None = None


def signature(draft):
    """Compare exact semantic slots, not generated goal IDs or explanatory prose."""
    if not draft.request:
        return IntentGold(action="clarify")
    return IntentGold(
        action="candidate",
        metrics=[
            m.model_dump(mode="json", exclude={"goal_id", "intent"}) for m in draft.request.metrics
        ],
        documents=bool(draft.request.documents),
    )


def rate(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def wilson(successes, total):
    """95% Wilson interval; no observation means no confidence interval."""
    if not total:
        return None
    z = 1.959963984540054
    p, q = successes / total, z * z / total
    centre = (p + q / 2) / (1 + q)
    delta = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + q)
    return [max(0, centre - delta), min(1, centre + delta)]


def percentile(values, percentile_):
    """Pre-registered nearest-rank percentile; not an SLA guarantee."""
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * percentile_) - 1)]


def intent_summary(observations):
    rows = list(observations)
    if len({r.case_id for r in rows}) != len(rows):
        raise ValueError("Repeated task ID cannot inflate the denominator")
    if len({(r.strategy, r.transport) for r in rows}) > 1:
        raise ValueError("Report strategies and transports separately")
    accepted = [r for r in rows if r.actual and r.actual.action == "candidate"]
    answerable = [r for r in rows if r.expected.action == "candidate"]
    clarification = [r for r in rows if r.expected.action == "clarify"]
    correct = sum(r.actual == r.expected and r.error_code is None for r in rows)
    wrong = sum(r.actual != r.expected for r in accepted)
    errors = [r for r in rows if r.error_code]
    return {
        "tasks": len(rows),
        "strategy": rows[0].strategy if rows else None,
        "transport": rows[0].transport if rows else None,
        "intent_exact_match": rate(correct, len(rows)),
        "intent_95pct_wilson": wilson(correct, len(rows)),
        "wrong_goal_acceptance": rate(wrong, len(accepted)),
        "necessary_clarification": rate(
            sum(r.actual == r.expected for r in clarification), len(clarification)
        ),
        "wrong_rejection": rate(
            sum(r.actual is not None and r.actual.action == "clarify" for r in answerable),
            len(answerable),
        ),
        "intent_execution_errors": rate(len(errors), len(rows)),
        "latency_ms": {
            "definition": "intent resolution only; nearest-rank",
            "p50": percentile([r.elapsed_ms for r in rows], 0.5),
            "p95": percentile([r.elapsed_ms for r in rows], 0.95),
        },
        "model_calls": sum(r.model_calls for r in rows),
        "reported_tokens": sum(r.reported_tokens for r in rows)
        if all(r.reported_tokens is not None for r in rows)
        else None,
        "provider_cache_read_tokens": sum(r.provider_cache_read_tokens for r in rows)
        if all(r.provider_cache_read_tokens is not None for r in rows)
        else None,
        "agent_execution": "not_run",
        "evidence_verification": "not_run",
        "live_quality_evidence": bool(rows) and all(r.transport == "live" for r in rows),
        "bad_cases": [r.case_id for r in rows if r.actual != r.expected or r.error_code],
    }


def retrieval_scores(ranked, relevant):
    """Use separately for chunk and source IDs; duplicate chunks do not create sources."""
    if len(ranked) != len(set(ranked)) or len(relevant) != len(set(relevant)):
        raise ValueError("Rankings and gold relevance IDs must be unique at the chosen level")
    hits = [i + 1 for i, item in enumerate(ranked) if item in relevant]
    return {
        "recall": len(hits) / len(relevant) if relevant else None,
        "precision": len(hits) / len(ranked) if ranked else None,
        "reciprocal_rank": 1 / hits[0] if hits else 0,
        "relevant_total": len(relevant),
        "returned_total": len(ranked),
    }
