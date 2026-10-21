"""Async LangChain tool protocol with a single budget/cancellation boundary."""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from datapilot.agents.sql import SYSTEM as SQL_SYSTEM
from datapilot.contracts import AgentFailure, SQLProposal
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
    return NativeTransport(
        ChatOpenAI(
            model=settings.model,
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            temperature=0,
            max_tokens=settings.max_output_tokens,
            timeout=settings.model_timeout_seconds,
            max_retries=0,
            stream_usage=False,
        )
    )


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

    async def invoke(self, messages, tools, account):
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
        ticket = self.ledger.reserve(account, text, self.settings.max_output_tokens)
        try:
            response = await self.cancel.wait_for(
                self.transport.respond(messages, tools),
                self.settings.model_timeout_seconds,
                timeout_code="MODEL_TIMEOUT",
            )
        except BaseException as exc:
            self.ledger.settle(ticket, None)
            if isinstance(exc, (asyncio.CancelledError, AgentFailure)):
                raise
            raise AgentFailure("MODEL_ERROR", "Async model provider failed") from exc
        usage = (
            (response.usage_metadata or {}).get("total_tokens")
            if isinstance(response, AIMessage)
            else None
        )
        self.ledger.settle(ticket, usage)
        if not isinstance(response, AIMessage) or response.invalid_tool_calls:
            raise AgentFailure("MODEL_OUTPUT_INVALID", "Invalid assistant/tool protocol response")
        if (
            not isinstance(response.content, str)
            or len(response.content) > self.settings.max_output_tokens * 16
            or len(response.tool_calls) > 4
        ):
            raise AgentFailure("MODEL_OUTPUT_INVALID", "Model output exceeds protocol limits")
        ids = [c.get("id") for c in response.tool_calls]
        if len(
            json.dumps(response.tool_calls, ensure_ascii=False)
        ) > self.settings.max_output_tokens * 16 or any(
            len(c.get("name", "")) > 64 for c in response.tool_calls
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

    async def respond(self, messages, tools):
        await asyncio.sleep(0)  # Real cooperative scheduling; no blocking provider call.
        system = messages[0].content
        question = next(m.content for m in messages if isinstance(m, HumanMessage))
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
            if payload.get("artifact_refs"):
                return AIMessage(
                    content=json.dumps(
                        {
                            "artifact_ids": [r["artifact_id"] for r in payload["artifact_refs"]],
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
            name, args = "search_documents", {"query": question[:512], "top_k": 3}
        return AIMessage(
            content="",
            tool_calls=[{"id": call_id, "name": name, "args": args}],
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
