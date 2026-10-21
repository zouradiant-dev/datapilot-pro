"""Atomic, in-process parent/child reservations. No persistence/resume claim in D9-D10."""

import threading
from dataclasses import dataclass, field
from uuid import uuid4

from datapilot.contracts import AgentFailure
from datapilot.orchestration.contracts import BudgetLimits, Usage


@dataclass
class _Account:
    limits: BudgetLimits
    parent: str | None
    usage: Usage = field(default_factory=Usage)


class BudgetLedger:
    def __init__(self, limits: BudgetLimits):
        self._lock = threading.RLock()
        self.accounts = {"root": _Account(limits, None)}
        self.pending = {}

    def fork(self, name: str, limits: BudgetLimits, parent="root") -> str:
        with self._lock:
            if name in self.accounts or parent not in self.accounts:
                raise AgentFailure("BUDGET_INVALID", "Invalid/repeated child budget")
            upper = self.accounts[parent].limits
            if limits.calls > upper.calls or limits.tokens > upper.tokens:
                raise AgentFailure("BUDGET_INVALID", "Child budget cannot exceed parent limits")
            self.accounts[name] = _Account(limits, parent)
            return name

    def reserve(self, account: str, text: str, output_tokens: int) -> str:
        amount = len(text.encode("utf-8")) + 128 + output_tokens
        with self._lock:
            chain, key = [], account
            while key is not None:
                item = self.accounts[key]
                if (
                    item.usage.calls >= item.limits.calls
                    or item.usage.total_tokens + amount > item.limits.tokens
                ):
                    raise AgentFailure("BUDGET_EXCEEDED", "Parent or child model budget exhausted")
                chain.append(key)
                key = item.parent
            ticket = str(uuid4())
            self.pending[ticket] = (chain, amount)
            for key in chain:
                self.accounts[key].usage.calls += 1
                self.accounts[key].usage.total_tokens += amount
            return ticket

    def settle(self, ticket: str, actual: int | None):
        with self._lock:
            if ticket not in self.pending:
                raise AgentFailure("BUDGET_INVALID", "Unknown/already settled reservation")
            chain, amount = self.pending.pop(ticket)
            valid = type(actual) is int and actual >= 0
            exceeded = False
            for key in chain:
                item = self.accounts[key]
                if not valid:
                    item.usage.usage_complete = False
                else:
                    item.usage.total_tokens += actual - amount
                    item.usage.reported_tokens += actual
                    exceeded |= item.usage.total_tokens > item.limits.tokens
            if exceeded:
                raise AgentFailure(
                    "BUDGET_EXCEEDED", "Provider usage exceeded a parent/child budget"
                )

    def snapshot(self, account="root") -> Usage:
        with self._lock:
            return self.accounts[account].usage.model_copy(deep=True)
