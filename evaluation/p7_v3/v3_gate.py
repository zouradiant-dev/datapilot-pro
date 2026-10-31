"""One future exact campaign permit; no credentials, models, Gold or filesystem access."""

from datetime import UTC, datetime


def permit_valid(permit, binding, *, now=None):
    now = now or datetime.now(UTC)
    if (
        permit.get("kind") != "p7-business-v3-one-campaign-permit-1"
        or permit.get("authorized") is not True
        or permit.get("approved_by_role") != "project_owner"
        or not permit.get("source_user_authorization_ref")
        or permit.get("approve_bound_runs") is not True
    ):
        raise ValueError("New separately explicit paid authorization required")
    if any(permit.get(k) != value for k, value in binding.items()):
        raise ValueError("Permit differs from exact frozen campaign identity")
    for key, value in {
        "cases": 60,
        "runtime_runs": 54,
        "model_attempts": 432,
        "token_units": 972000,
        "root_calls": 8,
        "root_tokens": 18000,
        "child_calls": 4,
        "child_tokens": 18000,
        "output_tokens": 1200,
        "concurrency": 1,
        "automatic_retries": 0,
        "task_timeout_seconds": 180,
        "campaign_timeout_seconds": 10800,
    }.items():
        if type(permit.get(key)) is not int or permit[key] != value:
            raise ValueError("Permit budget drift")
    if (
        permit.get("provider"),
        permit.get("model"),
        permit.get("thinking"),
        permit.get("base_url"),
    ) != ("deepseek", "deepseek-flash", "disabled", "https://api.deepseek.com"):
        raise ValueError("Permit provider drift")
    if permit.get("estimated_usd_cap") != "1.1664":
        raise ValueError("Permit cost estimate differs")
    expiry = datetime.fromisoformat(permit["expires_at"])
    if expiry.tzinfo is None or expiry <= now:
        raise ValueError("Permit expired")


def ordinary_failure_may_continue(score, payload):
    """Protocol B; pure business errors never authorize uncertain/safety execution."""
    if (
        score.get("safety_violation")
        or payload.get("snapshot", {}).get("unknown")
        or payload.get("unresolved_dispatch")
    ):
        return False
    hard = {
        "BUDGET_EXCEEDED",
        "CONTEXT_LIMIT",
        "MODEL_ERROR",
        "MODEL_TIMEOUT",
        "RECOVERY_UNCERTAIN",
        "RECOVERY_IDENTITY",
        "RECOVERY_CORRUPT",
        "REGISTRY_INTEGRITY",
        "DOCUMENT_CORRUPT",
        "EVIDENCE_INVALID",
        "REPORT_EVIDENCE_INVALID",
        "TOOL_OUTPUT_INVALID",
    }
    codes = {
        r["error"]["code"]
        for r in payload.get("snapshot", {}).get("state", {}).get("results", {}).values()
        if r.get("error")
    }
    root_error = payload.get("snapshot", {}).get("state", {}).get("error")
    if root_error:
        codes.add(root_error["code"])
    integrity = score.get("dimensions", {})
    return (
        not any(
            integrity.get(k) is False
            for k in ["evidence", "authorization", "protocol", "chart_units", "budget", "durable"]
        )
        and not codes & hard
        and all(c["status"] == "complete" for c in payload.get("calls", []))
        and score.get("failure_class")
        not in {
            "p3_evidence_integrity",
            "unknown_outcome",
            "evaluator_integrity",
            "authorization_violation",
        }
    )
