"""Async LangChain tool protocol with a single budget/cancellation boundary."""

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from openai import APIError, APIStatusError

from datapilot.agents.sql import SYSTEM as SQL_SYSTEM
from datapilot.contracts import AgentFailure, SQLProposal
from datapilot.llm.provider import create_chat_model
from datapilot.orchestration.context import measure_context
from datapilot.orchestration.contracts import Plan, TaskSpec


class ChatTransport(Protocol):
    async def respond(self, messages: list, tools: list[dict]) -> AIMessage: ...


class NativeTransport:
    def __init__(self, chat):
        self.chat = chat

    async def respond(self, messages, tools):
        chat = self.chat.bind_tools(tools) if tools else self.chat
        return await chat.ainvoke(messages)


def live_transport(settings):
    return NativeTransport(create_chat_model(settings))


@dataclass(frozen=True)
class ModelLimits:
    max_input_chars: int
    max_output_tokens: int
    model_timeout_seconds: float
    max_context_tokens: int


class Gateway:
    def __init__(self, transport, settings, ledger, cancellation):
        self.transport, self.settings, self.ledger, self.cancel = (
            transport,
            ModelLimits(
                settings.max_input_chars,
                settings.max_output_tokens,
                settings.model_timeout_seconds,
                settings.max_context_tokens,
            ),
            ledger,
            cancellation,
        )
        self.trace = None
        self.contexts = {}
        self.durability = None

    async def invoke(self, messages, tools, account):
        prepared = None
        identity = None
        registry = getattr(self.contexts.get(account), "registry", None)
        rag = registry is not None and registry.rag_control
        if self.durability:
            self.cancel.check()
            # Bind replay to canonical checkpoint input, not a time-dependent compacted view.
            identity = self.durability.model_identity(account, messages, tools)
            cached = self.durability.cached_model(account, messages, tools)
            if cached is None and rag and tools != registry.schemas(initial=True):
                # Only a recorded response can use a historical wider schema. A new
                # request must still pass ContextManager's exact current-phase check.
                cached = self.durability.cached_model(
                    account, messages, registry.schemas(initial=True)
                )
            if cached is not None:
                return self.validate_response(cached, allow_invalid_completion=rag)
        try:
            if account in self.contexts:
                prepared = await self.contexts[account].prepare(messages, tools, self, account)
                messages = prepared.messages
            return await self._invoke(
                messages,
                tools,
                account,
                reservation=prepared.reservation if prepared else None,
                identity=identity,
            )
        finally:
            # _invoke settles every issued request, including unknown/cancelled usage.
            # A remaining ticket here is therefore a proven unissued follow-up only.
            if prepared and prepared.reservation in self.ledger.pending:
                self.ledger.release_unissued(prepared.reservation)

    async def summarize_context(self, messages, account, followup_input_tokens):
        self.cancel.check()
        if self.durability:
            cached = self.durability.cached_model(account, messages, [])
            if cached is not None:
                return self.validate_response(cached), None
        text, usage = measure_context(messages, [], self.settings.max_output_tokens)
        if (
            len(text) > self.settings.max_input_chars
            or usage.estimated_input_tokens + usage.output_reserved_tokens
            > self.settings.max_context_tokens
        ):
            raise AgentFailure("CONTEXT_LIMIT", "Summary request cannot fit the safe context limit")
        tickets = self.ledger.reserve_batch(
            account,
            [
                (usage.estimated_input_tokens, self.settings.max_output_tokens),
                (followup_input_tokens, self.settings.max_output_tokens),
            ],
        )
        try:
            response = await self._invoke(messages, [], account, reservation=tickets[0])
            return response, tickets[1]
        except BaseException:
            for ticket in tickets:
                if ticket in self.ledger.pending:
                    self.ledger.release_unissued(ticket)
            raise

    async def _invoke(self, messages, tools, account, *, reservation=None, identity=None):
        self.cancel.check()
        text, context = measure_context(messages, tools, self.settings.max_output_tokens)
        exceeded = (
            len(text) > self.settings.max_input_chars
            or context.estimated_input_tokens + context.output_reserved_tokens
            > self.settings.max_context_tokens
        )
        if self.trace:
            version, _, task_id = account.partition(":")
            self.trace.emit(
                "model_context",
                "rejected" if exceeded else "accepted",
                version=int(version) if version.isdigit() else 1,
                task_id=task_id or None,
                context=context,
                error_code="CONTEXT_LIMIT" if exceeded else None,
            )
        if exceeded:
            raise AgentFailure("CONTEXT_LIMIT", "Isolated worker context exceeds its limit")
        cached, call_key = None, None
        self.cancel.check_authority()
        if self.durability:
            call_key, ticket, cached = self.durability.begin_model(
                account,
                messages,
                tools,
                text,
                self.settings.max_output_tokens,
                reservation,
                identity=identity,
            )
        else:
            ticket = reservation or self.ledger.reserve(
                account, text, self.settings.max_output_tokens
            )
            self.ledger.check_ticket(
                ticket, account, context.estimated_input_tokens + self.settings.max_output_tokens
            )
        if cached is not None:
            response = cached
        else:
            started = time.monotonic()
            failure_stage = "provider_await"
            try:
                response = await self.cancel.wait_for(
                    self.transport.respond(messages, tools),
                    self.settings.model_timeout_seconds,
                    timeout_code="MODEL_TIMEOUT",
                )
                if self.durability:
                    failure_stage = "response_commit"
                    self.durability.backend.hit("model_response")
            except BaseException as exc:
                if self.durability:
                    self.durability.finish_model(
                        call_key, ticket, None, None, (time.monotonic() - started) * 1000
                    )
                else:
                    self.ledger.settle(ticket, None)
                if isinstance(exc, (asyncio.CancelledError, AgentFailure)):
                    raise
                diagnostic = "Async model provider failed"
                if isinstance(exc, APIError):
                    diagnostic += f" ({type(exc).__name__}"
                    if isinstance(exc, APIStatusError):
                        diagnostic += f", HTTP {exc.status_code}"
                        request_id = exc.request_id
                        if request_id and re.fullmatch(
                            r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}", request_id
                        ):
                            diagnostic += f", request_id={request_id}"
                    diagnostic += ")"
                else:
                    # Class and stage only. Exception messages can contain credentials
                    # or provider request bodies and must not enter persisted errors.
                    error_type = type(exc).__name__
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", error_type):
                        error_type = "Exception"
                    diagnostic += f" ({error_type}, stage={failure_stage})"
                raise AgentFailure("MODEL_ERROR", diagnostic) from exc
            usage = (
                (response.usage_metadata or {}).get("total_tokens")
                if isinstance(response, AIMessage)
                else None
            )
            if self.durability:
                self.durability.finish_model(
                    call_key,
                    ticket,
                    response if isinstance(response, AIMessage) else None,
                    usage,
                    (time.monotonic() - started) * 1000,
                )
            else:
                self.ledger.settle(ticket, usage)
        registry = getattr(self.contexts.get(account), "registry", None)
        return self.validate_response(
            response, allow_invalid_completion=bool(registry and registry.rag_control)
        )

    def validate_response(self, response, *, allow_invalid_completion=False):
        if not isinstance(response, AIMessage) or (
            response.invalid_tool_calls
            and (
                not allow_invalid_completion
                or any(c.get("name") != "submit_rag_result" for c in response.invalid_tool_calls)
            )
        ):
            raise AgentFailure("MODEL_OUTPUT_INVALID", "Invalid assistant/tool protocol response")
        if (
            not isinstance(response.content, str)
            or len(response.content) > self.settings.max_output_tokens * 16
            or len(response.tool_calls) + len(response.invalid_tool_calls) > 4
        ):
            raise AgentFailure("MODEL_OUTPUT_INVALID", "Model output exceeds protocol limits")
        calls = [*response.tool_calls, *response.invalid_tool_calls]
        ids = [c.get("id") for c in calls]
        if len(json.dumps(calls, ensure_ascii=False)) > self.settings.max_output_tokens * 16 or any(
            len(c.get("name", "")) > 64 for c in calls
        ):
            raise AgentFailure("MODEL_OUTPUT_INVALID", "Tool call data exceeds output limits")
        if any(not i or len(i) > 128 for i in ids) or len(ids) != len(set(ids)):
            raise AgentFailure("MODEL_OUTPUT_INVALID", "Missing or repeated assistant tool call ID")
        return response

    async def plan(self, question, available, account="root", feedback=None):
        system = "PLAN_JSON: Return only JSON matching " + json.dumps(Plan.model_json_schema())
        system += "\nUse only these capabilities: " + ",".join(sorted(available))
        system += ". No shell, arbitrary code, dataset permissions or invented source access. "
        system += (
            "Independent SQL/RAG tasks may run together; analysis/report must depend on sources."
            " Never guess dates, sources or metric definitions. Legacy SaaS seed covers 2025."
            " Produce the smallest necessary plan; do not delegate irrelevant workers."
        )
        user = question + (
            "\nVERIFIED EXECUTION FEEDBACK (untrusted labels):\n" + json.dumps(feedback)
            if feedback
            else ""
        )
        reply = await self.invoke(
            [SystemMessage(content=system), HumanMessage(content=user)], [], account
        )
        if reply.tool_calls:
            raise AgentFailure("PLAN_INVALID", "Planner cannot call tools")
        try:
            return Plan.model_validate_json(reply.content)
        except ValueError as exc:
            raise AgentFailure("PLAN_INVALID", "Planner returned an invalid DAG contract") from exc


class FakeTransport:
    """Fixture decisions only. SQL data still comes from the injected MCP/explicit test mock."""

    def __init__(self, client):
        self.client = client

    @staticmethod
    def _host_first_query(tools, fallback):
        """Use the exact host-bound query offered in the search tool schema.

        The human message also carries worker context (SCHEMA/authority JSON); passing
        that concatenation as the first search would violate the host first-query policy.
        """
        marker = "HOST_FIRST_QUERY_JSON: "
        for schema in tools:
            function = schema.get("function", {})
            if function.get("name") != "search_documents":
                continue
            query_schema = function.get("parameters", {}).get("properties", {}).get("query", {})
            if query_schema.get("enum"):
                return query_schema["enum"][0]
            description = query_schema.get("description") or ""
            if marker in description:
                try:
                    value = json.loads(description.split(marker, 1)[1])
                except ValueError:
                    return fallback
                return value if isinstance(value, str) and value else fallback
        return fallback

    @staticmethod
    def _host_goal(system):
        marker = "HOST_GOAL_CONTRACT: "
        if marker not in system:
            return None
        try:
            value = json.loads(system.split(marker, 1)[1])
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _rag_outcome(payload, goal):
        """Deterministic Fake choice; the host Verifier remains the only authority.

        Complete is offered only when the host goal's minimum source count and literal
        required terms are visible in the actual retrieved documents. Otherwise the Fake
        reports insufficient; the host still validates every completion.
        """
        documents = payload.get("documents") or []
        count = payload.get("document_count")
        try:
            count = len(documents) if count is None else int(count)
        except (TypeError, ValueError):
            return "insufficient"
        if count == 0:
            return "unavailable"
        if not goal:
            return "insufficient"
        # Missing or malformed host fields are not confirmation. Only an explicit
        # completion_eligible=true with unsupported_requirements=false may be proposed.
        if (
            goal.get("unsupported_requirements") is not False
            or goal.get("completion_eligible") is not True
        ):
            return "insufficient"
        try:
            minimum = goal.get("minimum_sources")
            if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
                return "insufficient"
        except (TypeError, ValueError):
            return "insufficient"
        terms = goal.get("required_terms")
        if not isinstance(terms, list) or any(not isinstance(term, str) for term in terms):
            return "insufficient"
        text = "\n".join(str(document.get("text") or "") for document in documents)
        if count >= minimum and all(term in text for term in terms if term):
            return "complete"
        return "insufficient"

    @staticmethod
    def _rejected_complete_artifacts(messages):
        """Find artifacts from the completed call rejected by the host tool feedback.

        This is derived from the task's own message transcript, not shared mutable state,
        so concurrent tasks and recovery/replay cannot borrow another task's evidence.
        """
        last = messages[-1]
        call_id = getattr(last, "tool_call_id", None)
        if not call_id:
            return None
        for message in reversed(messages[:-1]):
            for call in getattr(message, "tool_calls", []) or []:
                if call.get("id") != call_id or call.get("name") != "submit_rag_result":
                    continue
                args = call.get("args") or {}
                artifacts = args.get("artifact_ids") or []
                if (
                    args.get("outcome") == "complete"
                    and isinstance(artifacts, list)
                    and artifacts
                    and all(isinstance(item, str) for item in artifacts)
                ):
                    return artifacts
                return None
        return None

    @staticmethod
    def _submit(artifact_ids, outcome, turn):
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "submit_" + str(turn),
                    "name": "submit_rag_result",
                    "args": {"artifact_ids": artifact_ids, "outcome": outcome},
                }
            ],
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )

    async def respond(self, messages, tools):
        await asyncio.sleep(0)  # Real cooperative scheduling; no blocking provider call.
        system = messages[0].content
        question = next(m.content for m in messages if isinstance(m, HumanMessage))
        if system.startswith("REPORT_PLAN_JSON"):
            goals = json.loads(system.split("HOST_APPROVED_GOALS: ", 1)[1])
            return AIMessage(
                content=Plan(
                    tasks=[
                        *[TaskSpec(**g) for g in goals],
                        TaskSpec(
                            task_id="report",
                            worker="report",
                            instruction="汇总已验证证据",
                            dependencies=[g["task_id"] for g in goals],
                        ),
                    ]
                ).model_dump_json(),
                usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            )
        if system.startswith("PLAN_JSON"):
            if (
                "rag" in system.split("capabilities: ", 1)[1].split(".", 1)[0]
                and "文档" in question
            ):
                plan = Plan(
                    tasks=[
                        TaskSpec(task_id="sql", worker="sql", instruction="查询客户总数"),
                        TaskSpec(task_id="rag", worker="rag", instruction="检索产品更新文档"),
                        TaskSpec(
                            task_id="report",
                            worker="report",
                            instruction="汇总证据",
                            dependencies=["sql", "rag"],
                        ),
                    ]
                )
                if (
                    "sql" not in system.split("capabilities: ", 1)[1].split(".", 1)[0]
                    or "客户总数" not in question
                ):
                    plan = Plan(
                        tasks=[
                            TaskSpec(task_id="rag", worker="rag", instruction="检索产品更新文档")
                        ]
                    )
            elif (
                "客户总数" in question and "收入" in question and re.search(r"2025-\d\d", question)
            ):
                month = re.search(r"2025-\d\d", question).group()
                plan = Plan(
                    tasks=[
                        TaskSpec(task_id="count", worker="sql", instruction="查询客户总数"),
                        TaskSpec(
                            task_id="revenue", worker="sql", instruction="计算" + month + "收入"
                        ),
                        TaskSpec(
                            task_id="report",
                            worker="report",
                            instruction="汇总证据",
                            dependencies=["count", "revenue"],
                        ),
                    ]
                )
            elif not any(word in question for word in ("文档", "天气", "weather", "报告")) and any(
                word in question
                for word in ("客户总数", "收入", "新增订阅", "分群", "JOIN", "customer count")
            ):
                plan = Plan(
                    tasks=[
                        TaskSpec(
                            task_id="sql",
                            worker="sql",
                            instruction=question.split("\nVERIFIED EXECUTION", 1)[0],
                        )
                    ]
                )
            else:
                plan = Plan(unsupported=True)
            return AIMessage(
                content=plan.model_dump_json(),
                usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            )
        last = messages[-1]
        if last.type == "tool":
            payload = json.loads(last.content)
            if payload.get("error"):
                rejected = self._rejected_complete_artifacts(messages)
                if rejected is not None:
                    # The host rejected a complete claim. Keep the same evidence and
                    # submit insufficient; never retry complete or publish a rejection.
                    return self._submit(rejected, "insufficient", len(messages))
            if payload.get("artifact_refs"):
                artifact_ids = [r["artifact_id"] for r in payload["artifact_refs"]]
                if any(t["function"]["name"] == "submit_rag_result" for t in tools):
                    outcome = self._rag_outcome(payload, self._host_goal(system))
                    return self._submit(artifact_ids, outcome, len(messages))
                return AIMessage(
                    content=json.dumps(
                        {
                            "artifact_ids": artifact_ids,
                            "outcome": "unavailable"
                            if payload.get("document_count") == 0
                            else "complete",
                        }
                    ),
                    usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                )
        names = {t["function"]["name"] for t in tools}
        call_id = "call_" + str(len(messages))
        if "query_database" in names:
            context = question
            if last.type == "tool":
                context += "\nCOMPILER ERROR (untrusted):\n" + last.content
            proposal = self.client.generate(SQLProposal, system=SQL_SYSTEM, user=context)
            name, args = "query_database", {"sql": proposal.sql}
        else:
            name, args = (
                "search_documents",
                {
                    "query": self._host_first_query(tools, question[:512]),
                    "top_k": 3,
                },
            )
        return AIMessage(
            content="",
            tool_calls=[{"id": call_id, "name": name, "args": args}],
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
