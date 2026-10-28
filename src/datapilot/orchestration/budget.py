"""Atomic, in-process parent/child reservations. No persistence/resume claim in D9-D10."""

import json
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
        return self.reserve_batch(account, [(len(text.encode("utf-8")) + 128, output_tokens)])[0]

    def remaining(self, account: str) -> tuple[int, int]:
        """Advisory headroom across the same ancestry; pending reservations already count.

        This does not reserve or authorize a call. reserve_batch remains the final atomic gate.
        """
        with self._lock:
            calls, tokens, seen = [], [], set()
            key = account
            while key is not None:
                if key not in self.accounts or key in seen:
                    raise AgentFailure("BUDGET_INVALID", "Invalid budget ancestry")
                seen.add(key)
                item = self.accounts[key]
                calls.append(max(0, item.limits.calls - item.usage.calls))
                tokens.append(max(0, item.limits.tokens - item.usage.total_tokens))
                key = item.parent
            if not calls:
                raise AgentFailure("BUDGET_INVALID", "Missing budget account")
            return min(calls), min(tokens)

    def reserve_batch(self, account: str, requests: list[tuple[int, int]]) -> list[str]:
        """Atomic summary + worst-case follow-up, on the original parent/child ledger."""
        if not requests or any(
            type(i) is not int or type(o) is not int or min(i, o) < 0 for i, o in requests
        ):
            raise AgentFailure("BUDGET_INVALID", "Invalid bounded reservation batch")
        amounts = [i + o for i, o in requests]
        amount = sum(amounts)
        with self._lock:
            chain, key = [], account
            while key is not None:
                item = self.accounts[key]
                if (
                    item.usage.calls + len(requests) > item.limits.calls
                    or item.usage.total_tokens + amount > item.limits.tokens
                ):
                    raise AgentFailure("BUDGET_EXCEEDED", "Parent or child model budget exhausted")
                chain.append(key)
                key = item.parent
            tickets = []
            for charge in amounts:
                ticket = str(uuid4())
                self.pending[ticket] = (chain, charge)
                tickets.append(ticket)
            for key in chain:
                self.accounts[key].usage.calls += len(requests)
                self.accounts[key].usage.total_tokens += amount
            return tickets

    def check_ticket(self, ticket: str, account: str, amount: int) -> None:
        with self._lock:
            held = self.pending.get(ticket)
            if held is None or held[0][0] != account or held[1] < amount:
                raise AgentFailure(
                    "BUDGET_INVALID", "Reservation does not cover this model request"
                )

    def release_unissued(self, ticket: str) -> None:
        """Host only: release a proven unissued follow-up, NEVER an uncertain HTTP request."""
        with self._lock:
            if ticket not in self.pending:
                raise AgentFailure("BUDGET_INVALID", "Unknown/already settled reservation")
            chain, amount = self.pending.pop(ticket)
            for key in chain:
                self.accounts[key].usage.calls -= 1
                self.accounts[key].usage.total_tokens -= amount

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

    def dump_state(self) -> dict:
        """Explicit durable representation; no locks, clients, credentials or executable types."""
        with self._lock:
            return {
                "accounts": {
                    key: {
                        "limits": a.limits.model_dump(),
                        "parent": a.parent,
                        "usage": a.usage.model_dump(),
                    }
                    for key, a in self.accounts.items()
                },
                "pending": {
                    k: [list(chain), amount] for k, (chain, amount) in self.pending.items()
                },
            }

    def load_state(self, state: dict) -> None:
        with self._lock:
            accounts = {
                key: _Account(
                    BudgetLimits.model_validate_json(json.dumps(a["limits"])),
                    a["parent"],
                    Usage.model_validate_json(json.dumps(a["usage"])),
                )
                for key, a in state["accounts"].items()
            }
            if "root" not in accounts or accounts["root"].parent is not None:
                raise AgentFailure("BUDGET_INVALID", "Missing durable root budget")
            for key in accounts:
                child = accounts[key]
                if child.parent in accounts:
                    parent = accounts[child.parent]
                    if (
                        child.limits.calls > parent.limits.calls
                        or child.limits.tokens > parent.limits.tokens
                    ):
                        raise AgentFailure("BUDGET_INVALID", "Durable child exceeds parent limits")
                seen, at = set(), key
                while at is not None:
                    if at not in accounts or at in seen:
                        raise AgentFailure("BUDGET_INVALID", "Invalid durable budget ancestry")
                    seen.add(at)
                    at = accounts[at].parent
            pending = {}
            for ticket, (chain, amount) in state["pending"].items():
                if type(amount) is not int or amount < 0 or not chain or chain[-1] != "root":
                    raise AgentFailure("BUDGET_INVALID", "Invalid durable reservation")
                expected, at = [], chain[0]
                while at is not None:
                    if at not in accounts:
                        raise AgentFailure("BUDGET_INVALID", "Unknown reservation account")
                    expected.append(at)
                    at = accounts[at].parent
                if expected != chain:
                    raise AgentFailure("BUDGET_INVALID", "Reservation ancestry differs")
                pending[ticket] = (chain, amount)
            for key, a in accounts.items():
                held = [v for v in pending.values() if key in v[0]]
                if a.usage.calls < len(held) or a.usage.total_tokens < sum(v[1] for v in held):
                    raise AgentFailure("BUDGET_INVALID", "Budget is smaller than live reservations")
            self.accounts, self.pending = accounts, pending
