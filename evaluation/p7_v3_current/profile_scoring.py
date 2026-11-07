"""Authenticated, namespace-independent budget profiles over frozen v3 scores.

The explicit budget enters at the frozen baseline boundary. Existing higher
level policies then run unchanged, including the partial-receipt rule that
depends on budget. Profiles describe runtime window/character limits too;
those limits still require runtime context/ledger evidence.
"""

from collections import Counter
from collections.abc import Callable
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Literal
from unittest.mock import patch

from pydantic import ConfigDict, Field, model_validator

from datapilot.contracts import Contract
from datapilot.ingestion.common import digest
from evaluation.p7_v3.v3_gate import ordinary_failure_may_continue

from .holdout_scoring import p7_business_scoring
from .holdout_scoring import scorer as legacy

SCORER_VERSION = "p7-profile-budget-scoring-1"


class BudgetProfile(Contract):
    """A frozen execution/scoring identity, never authority to issue a call."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: Literal["p7-evaluation-budget-profile-1"] = "p7-evaluation-budget-profile-1"
    root_calls: int = Field(default=8, ge=1, le=8)
    root_tokens: int = Field(default=18000, ge=100, le=100000)
    worker_calls: int = Field(default=4, ge=1, le=4)
    worker_tokens: int = Field(default=18000, ge=100, le=100000)
    output_tokens: int = Field(default=1200, ge=16, le=4096)
    context_tokens: int = Field(default=18000, ge=256, le=100000)
    input_chars: int = Field(default=16000, ge=100, le=64000)

    @model_validator(mode="after")
    def coherent(self):
        if self.worker_calls > self.root_calls or self.worker_tokens > self.root_tokens:
            raise ValueError("Worker budget cannot exceed the root budget")
        if self.output_tokens > min(self.root_tokens, self.worker_tokens, self.context_tokens):
            raise ValueError("Output reservation must fit root, worker and context limits")
        return self

    @property
    def sha256(self):
        return digest(self.model_dump(mode="json"))


class ProfileScoringError(ValueError):
    """An evaluator/profile contract is invalid, not a business failure."""


class ProfileCompatibilityError(ProfileScoringError):
    """The supplied scorer does not use the known frozen baseline boundary."""


@dataclass(slots=True)
class _Evaluation:
    record_sha256: str
    audit: dict
    baseline_hits: int = 0


_CURRENT: ContextVar[_Evaluation | None] = ContextVar("p7_budget_profile_score", default=None)
_LOCK = RLock()


def _units(value):
    if not isinstance(value, dict):
        return None
    names = ("input_tokens", "output_tokens", "total_tokens")
    if not all(type(value.get(name)) is int and value[name] >= 0 for name in names):
        return None
    if value["input_tokens"] + value["output_tokens"] != value["total_tokens"]:
        return None
    return {name: value[name] for name in names}


def audit_budget(payload, profile: BudgetProfile):
    """Reconcile settled model units and inclusive root/per-worker ceilings."""
    if not isinstance(profile, BudgetProfile):
        raise TypeError("A validated BudgetProfile is required")
    calls = payload.get("calls")
    snapshot = payload.get("snapshot")
    usage = snapshot.get("usage") if isinstance(snapshot, dict) else None
    errors = []
    if not isinstance(snapshot, dict):
        return {"valid": False, "errors": ["RUNTIME_SNAPSHOT_INVALID"], "model_calls": None}
    if not isinstance(calls, list) or not all(isinstance(call, dict) for call in calls):
        return {"valid": False, "errors": ["CALL_RECORDS_INVALID"], "model_calls": None}
    models = [call for call in calls if call.get("kind") == "model"]
    units = [_units(call.get("usage")) for call in models]
    if any(call.get("status") != "complete" for call in calls):
        errors.append("UNSETTLED_CALL")
    if not isinstance(usage, dict) or usage.get("usage_complete") is not True:
        errors.append("SNAPSHOT_USAGE_INCOMPLETE")
    if any(value is None for value in units):
        errors.append("MODEL_USAGE_INVALID")
    if any(not isinstance(call.get("account"), str) or not call["account"] for call in models):
        errors.append("MODEL_ACCOUNT_INVALID")
    if snapshot.get("unknown") is not False:
        errors.append("UNKNOWN_OUTCOME")
    if errors:
        return {"valid": False, "errors": errors, "model_calls": len(models)}
    total = sum(value["total_tokens"] for value in units)
    counts = Counter()
    tokens = Counter()
    for call, value in zip(models, units, strict=True):
        if call["account"] != "root":
            counts[call["account"]] += 1
            tokens[call["account"]] += value["total_tokens"]
        if value["output_tokens"] > profile.output_tokens:
            errors.append("OUTPUT_TOKEN_LIMIT")
        if value["total_tokens"] > profile.context_tokens:
            errors.append("CONTEXT_TOKEN_LIMIT")
    if (
        type(usage.get("calls")) is not int
        or usage["calls"] != len(models)
        or type(usage.get("total_tokens")) is not int
        or usage["total_tokens"] != total
    ):
        errors.append("SNAPSHOT_USAGE_MISMATCH")
    if len(models) > profile.root_calls or total > profile.root_tokens:
        errors.append("ROOT_BUDGET_LIMIT")
    if any(count > profile.worker_calls for count in counts.values()) or any(
        value > profile.worker_tokens for value in tokens.values()
    ):
        errors.append("WORKER_BUDGET_LIMIT")
    return {
        "valid": not errors,
        "errors": sorted(set(errors)),
        "model_calls": len(models),
        "reported_tokens": total,
        "worker_call_counts": dict(counts),
        "worker_token_totals": dict(tokens),
        "context_and_input_authority": "Runtime context/ledger evidence is still required",
    }


def _apply_baseline_budget(result, audit):
    dimensions = result.get("dimensions")
    if not dimensions:
        return result
    if not isinstance(dimensions, dict) or "budget" not in dimensions:
        raise ProfileCompatibilityError("FROZEN_SCORE_BUDGET_DIMENSION_REQUIRED")
    updated = dimensions | {"budget": audit["valid"]}
    correct = all(value is not False for value in updated.values())
    return result | {
        "dimensions": updated,
        "strict_correct": correct,
        "failure_class": None if correct else result.get("failure_class") or "budget_exceeded",
    }


def _derived_changes(original, result):
    old = original["dimensions"]
    new = result.get("dimensions")
    if not isinstance(new, dict) or set(old) != set(new):
        raise ProfileScoringError("NON_BUDGET_SCORING_DRIFT")
    changed = {name for name in old if name != "budget" and old[name] != new[name]}
    before = original.get("partial_evidence_scoring") or {}
    after = result.get("partial_evidence_scoring") or {}
    independent = {
        name: value
        for name, value in original.items()
        if name
        not in {
            "dimensions",
            "strict_correct",
            "failure_class",
            "legacy_strict_correct",
            "v2_strict_correct",
            "partial_evidence_scoring",
        }
    }
    if set(original) != set(result) or any(
        result[name] != value for name, value in independent.items()
    ):
        raise ProfileScoringError("NON_BUDGET_SCORING_DRIFT")
    if {k: v for k, v in before.items() if k != "insufficient_compatible_with_partial"} != {
        k: v for k, v in after.items() if k != "insufficient_compatible_with_partial"
    }:
        raise ProfileScoringError("NON_BUDGET_SCORING_DRIFT")
    if not changed and before == after:
        return {}
    dependent = (
        changed == {"retrieval_contract"}
        and old["budget"] is not new["budget"]
        and before.get("policy") == after.get("policy") == "partial-facts-v1"
        and before.get("original_retrieval_expected")
        == after.get("original_retrieval_expected")
        == "complete"
        and before.get("actual_retrieval_outcome")
        == after.get("actual_retrieval_outcome")
        == "insufficient"
        and before.get("insufficient_compatible_with_partial") is old["budget"]
        and after.get("insufficient_compatible_with_partial") is new["budget"]
        and old["retrieval_contract"] is old["budget"]
        and new["retrieval_contract"] is new["budget"]
    )
    if not dependent:
        raise ProfileScoringError("NON_BUDGET_SCORING_DRIFT")
    return {
        "retrieval_contract": {
            "original": old["retrieval_contract"],
            "profile": new["retrieval_contract"],
            "basis": "Unchanged frozen partial_receipt budget conjunction",
        }
    }


def score_with_profile(
    task,
    gold,
    record,
    key,
    pins,
    *,
    profile: BudgetProfile,
    score_original: Callable,
    host_refusal: bool = False,
):
    """Apply explicit limits to one signed frozen-v3 result, preserving all diagnostics.

    ``score_original`` is a pure, serial v3/current namespace adapter. It retains
    Scope/Gold validation. The full original18k diagnostic is computed first.
    Only the baseline budget return is replaced for the second pure evaluation;
    the current citation/partial/source-goal policies themselves are unchanged.
    A host rejection is explicit and must have no runtime or model/tool calls.
    """
    if not isinstance(profile, BudgetProfile):
        raise TypeError("A validated BudgetProfile is required")
    if type(host_refusal) is not bool:
        raise TypeError("host_refusal must be explicit bool")
    payload = p7_business_scoring.authenticated(record, key)
    if host_refusal and (
        "snapshot" in payload
        or any(
            type(payload.get(name)) is not int or payload[name] != 0
            for name in ("model_calls", "business_queries", "retrieval_queries")
        )
    ):
        raise ProfileScoringError("HOST_REFUSAL_MUST_HAVE_ZERO_RUNTIME_CALLS")
    audit = None if host_refusal else audit_budget(payload, profile)
    with _LOCK:
        if _CURRENT.get() is not None:
            raise ProfileCompatibilityError("NESTED_PROFILE_SCORING_UNSUPPORTED")
        original = deepcopy(score_original(task, gold, record, key, pins))
        dimensions = original.get("dimensions")
        if dimensions is not None and not isinstance(dimensions, dict):
            raise ProfileCompatibilityError("FROZEN_SCORE_DIMENSIONS_INVALID")
        early = not host_refusal and not dimensions
        result = deepcopy(original)
        derived = {}
        context = _Evaluation(record["sha256"], audit)
        if not host_refusal and dimensions:
            base_score = legacy.original.score

            def profiled_baseline(case, answer, observation, signing_key, source_pins):
                baseline = base_score(case, answer, observation, signing_key, source_pins)
                current = _CURRENT.get()
                # A direct/unprofiled call in another context still sees the
                # exact original result while this temporary hook is installed.
                if current is None:
                    return baseline
                if observation["sha256"] != current.record_sha256:
                    raise ProfileCompatibilityError("PROFILE_SCORE_RECORD_CHANGED")
                current.baseline_hits += 1
                return _apply_baseline_budget(baseline, current.audit)

            token = _CURRENT.set(context)
            try:
                with patch.object(legacy.original, "score", profiled_baseline):
                    result = deepcopy(score_original(task, gold, record, key, pins))
            finally:
                _CURRENT.reset(token)
            if context.baseline_hits != 1:
                raise ProfileCompatibilityError("FROZEN_V3_BASELINE_NOT_REACHED_EXACTLY_ONCE")
            derived = _derived_changes(original, result)
    return result | {
        "profile_scorer_version": SCORER_VERSION,
        "budget_profile": profile.model_dump(mode="json"),
        "budget_profile_sha256": profile.sha256,
        "authenticated_collection_sha256": record["sha256"],
        "authenticated_payload_sha256": digest(payload),
        "original_18000_score": original,
        "original_18000_score_purpose": "diagnostic_on_same_run_not_an_independent_rerun",
        "original_18000_cap_execution_demonstrated": False,
        "budget_profile_audit": audit,
        "budget_audit_requires_stop": not host_refusal and not audit["valid"],
        "host_refusal_budget_not_applicable": host_refusal,
        "frozen_early_failure_preserved": early,
        "frozen_baseline_hook_invocations": context.baseline_hits,
        "budget_derived_dimension_changes": derived,
        "non_budget_dimensions_unchanged": not derived,
        "non_budget_rules_unchanged": True,
        "upstream_diagnostics_recomputed_with_profile": not host_refusal and not early,
    }


def ordinary_failure_may_continue_profiled(result, record, key, *, expected_profile: BudgetProfile):
    """Bind the score to a reauthenticated record and the intended budget profile.

    Host refusals are handled outside Runtime dispatch. Historical batch-specific
    isolation permissions are absent. Current usage is reconciled again before
    delegating to the unchanged Runtime STOP policy.
    """
    if result.get("budget_audit_requires_stop") is not False:
        return False
    if not isinstance(expected_profile, BudgetProfile):
        raise TypeError("A validated expected BudgetProfile is required")
    if (
        result.get("profile_scorer_version") != SCORER_VERSION
        or result.get("budget_profile") != expected_profile.model_dump(mode="json")
        or result.get("budget_profile_sha256") != expected_profile.sha256
        or digest(result["budget_profile"]) != expected_profile.sha256
        or result.get("host_refusal_budget_not_applicable") is not False
        or not isinstance(result.get("budget_profile_audit"), dict)
        or result["budget_profile_audit"].get("valid") is not True
        or not isinstance(result.get("dimensions", {}), dict)
    ):
        return False
    payload = p7_business_scoring.authenticated(record, key)
    if result.get("authenticated_collection_sha256") != record["sha256"] or result.get(
        "authenticated_payload_sha256"
    ) != digest(payload):
        return False
    current_audit = audit_budget(payload, expected_profile)
    if not current_audit["valid"] or result["budget_profile_audit"] != current_audit:
        return False
    return ordinary_failure_may_continue(result, payload)
