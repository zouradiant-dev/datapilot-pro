"""Reject overlong context rather than silently dropping safety or schema text."""

from datapilot.contracts import AgentFailure


def check_context(system: str, user: str, max_chars: int) -> None:
    if len(system) + len(user) > max_chars:
        raise AgentFailure("CONTEXT_LIMIT", "Model context exceeds the configured character limit")
