"""Per-run model budget. Reserves worst-case output before every request."""

from dataclasses import dataclass

from datapilot.contracts import AgentFailure


@dataclass
class RunBudget:
    max_calls: int
    max_total_tokens: int
    calls: int = 0
    total_tokens: int = 0
    reported_tokens: int = 0
    usage_complete: bool = True

    def reserve(self, input_text: str, max_output_tokens: int) -> int:
        # UTF-8 bytes upper-bound normal BPE tokenization; add chat framing margin.
        reservation = len(input_text.encode("utf-8")) + 128 + max_output_tokens
        if self.calls >= self.max_calls or self.total_tokens + reservation > self.max_total_tokens:
            raise AgentFailure("BUDGET_EXCEEDED", "Model call or token budget exhausted")
        self.calls += 1
        self.total_tokens += reservation
        return reservation

    def settle(self, reservation: int, actual: int | None) -> None:
        if actual is None:
            self.usage_complete = False  # Keep conservative charge for unknown/failed usage.
            return
        self.reported_tokens += actual
        self.total_tokens += actual - reservation
        if self.total_tokens > self.max_total_tokens:
            raise AgentFailure("BUDGET_EXCEEDED", "Provider-reported token usage exceeded budget")
