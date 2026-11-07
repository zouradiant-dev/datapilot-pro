"""Read-only affordability check for one concrete, already prepared model view."""

import hashlib
from dataclasses import dataclass

from datapilot.orchestration.context import ContextManager, closed_batches, measure_context


@dataclass(frozen=True)
class ModelViewAdmission:
    model_view_sha256: str
    estimated_input_tokens: int
    output_reserved_tokens: int
    required_tokens: int
    available_calls: int
    available_tokens: int
    context_fits: bool
    budget_fits: bool

    @property
    def admitted(self) -> bool:
        return self.context_fits and self.budget_fits


def check_model_view(manager: ContextManager, ledger, account, messages, tools):
    """Measure the exact view/schema and current ancestry, including pending calls.

    This is not a reservation, an authority check, or a prediction of future
    model choices. The original atomic Gateway reservation remains mandatory.
    The supplied view must already have passed its host authority preparation.
    """
    closed_batches(messages)
    text, usage = measure_context(messages, tools, manager.limits.output_tokens)
    calls, tokens = ledger.remaining(account)
    required = usage.estimated_input_tokens + usage.output_reserved_tokens
    return ModelViewAdmission(
        model_view_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        estimated_input_tokens=usage.estimated_input_tokens,
        output_reserved_tokens=usage.output_reserved_tokens,
        required_tokens=required,
        available_calls=calls,
        available_tokens=tokens,
        context_fits=manager.fits(messages, tools),
        budget_fits=calls > 0 and required <= tokens,
    )
