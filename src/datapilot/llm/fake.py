"""Offline fixture router/SQL generator. Never returns simulated database rows."""

import re
from collections import deque

from datapilot.config import Settings
from datapilot.contracts import AgentFailure, RouteDecision, SQLProposal
from datapilot.harness.budget import RunBudget
from datapilot.harness.context import check_context


class FakeModelClient:
    def __init__(
        self, settings: Settings, budget: RunBudget, *, scripted_sql: list[str] | None = None
    ):
        self.settings = settings
        self.budget = budget
        self.scripted_sql = deque(scripted_sql or [])
        self.contexts: list[tuple[str, str]] = []

    def generate(self, schema, *, system: str, user: str):
        check_context(system, user, self.settings.max_input_chars)
        reservation = self.budget.reserve(system + user, self.settings.max_output_tokens)
        self.budget.settle(reservation, 0)  # Zero real tokens: this is not a model invocation.
        self.contexts.append((system, user))
        if schema is RouteDecision:
            route = (
                "unsupported"
                if any(x in user.lower() for x in ("天气", "weather", "文档", "报告"))
                else "sql"
            )
            return RouteDecision(route=route)
        if schema is not SQLProposal:
            raise AgentFailure("MODEL_OUTPUT_INVALID", "Fake does not implement this contract")
        if self.scripted_sql:
            return SQLProposal(sql=self.scripted_sql.popleft())
        question = user.split("\nSCHEMA:\n", 1)[0]
        if "客户总数" in question or "customer count" in question.lower():
            sql = "SELECT COUNT(*) AS customer_count FROM customers"
        elif "收入" in question:
            month = re.search(r"(2025)-(0[1-9]|1[0-2])", question)
            if not month:
                raise AgentFailure("FAKE_UNSUPPORTED", "Fake revenue fixture requires YYYY-MM")
            year, number = map(int, month.groups())
            start = f"{year:04d}-{number:02d}-01"
            end = f"{year + (number == 12):04d}-{1 if number == 12 else number + 1:02d}-01"
            sql = (
                "SELECT COALESCE(SUM(amount_cents), 0) AS revenue_cents FROM invoices "
                f"WHERE status='paid' AND invoice_date >= '{start}' AND invoice_date < '{end}'"
            )
        elif "新增订阅" in question:
            dates = re.findall(r"202[56]-\d{2}-\d{2}", question)
            if len(dates) != 2:
                raise AgentFailure(
                    "FAKE_UNSUPPORTED", "Fake interval fixture requires two ISO dates"
                )
            sql = (
                "SELECT COUNT(*) AS new_subscriptions FROM subscriptions "
                f"WHERE start_date >= '{dates[0]}' AND start_date < '{dates[1]}'"
            )
        elif "分群" in question or "join" in question.lower():
            sql = (
                "SELECT c.segment, COUNT(s.subscription_id) AS active_subscriptions "
                "FROM customers c JOIN subscriptions s ON c.customer_id=s.customer_id "
                "WHERE s.status='active' GROUP BY c.segment ORDER BY c.segment"
            )
        else:
            raise AgentFailure(
                "FAKE_UNSUPPORTED", "Question outside the documented offline fixtures"
            )
        return SQLProposal(sql=sql)
