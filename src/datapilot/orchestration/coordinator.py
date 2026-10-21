"""A compiled outer graph schedules a validated data DAG; workers receive only envelopes."""

import asyncio
import time
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send

from datapilot.agents.supervisor import Planner
from datapilot.contracts import AgentError, AgentFailure, SQLAgentResult, SQLTask
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.completion import completion_gate
from datapilot.orchestration.context import ContextManager
from datapilot.orchestration.context_contracts import AuthoritySnapshot
from datapilot.orchestration.contracts import (
    Artifact,
    BudgetLimits,
    EvidenceRef,
    Plan,
    TaskEnvelope,
    TaskResult,
    TaskSpec,
    VerificationResult,
)
from datapilot.orchestration.loop import (
    WorkerContext,
    WorkerLimits,
    build_worker_loop,
    initial_messages,
)
from datapilot.orchestration.model import Gateway
from datapilot.orchestration.runtime import (
    ArtifactStore,
    Cancellation,
    Trace,
    execution_error,
    text_hash,
)
from datapilot.orchestration.tools import CAPABILITIES, ToolRegistry
from datapilot.semantics.recipes import scalar
from datapilot.state import RunState


def key(version, task_id):
    return f"{version}:{task_id}"


def cell(value):
    if value is None:
        return "NULL"
    text = str(value)
    for a, b in (
        ("&", "&amp;"),
        ("<", "&lt;"),
        (">", "&gt;"),
        ("|", "&#124;"),
        ("[", "&#91;"),
        ("]", "&#93;"),
        ("`", "&#96;"),
        ("\n", " "),
        ("\r", " "),
    ):
        text = text.replace(a, b)
    return text


class Coordinator:
    def __init__(
        self,
        settings,
        transport,
        *,
        database=None,
        retrieval=None,
        events=None,
        cancellation=None,
        run_id="run",
        context_metadata=None,
        memory_store=None,
        memory_source_versions=None,
    ):
        self.settings, self.run_id = settings, run_id
        self.question = None
        self.context_metadata = context_metadata or {}
        self.memory_store = memory_store
        self.memory_source_versions = memory_source_versions or {}
        self.database, self.retrieval = database, retrieval
        self.available = {"analysis", "report"}
        if database is not None:
            self.available.add("sql")
        if retrieval is not None:
            self.available.add("rag")
        self.cancel = cancellation or Cancellation()
        self.ledger = BudgetLedger(
            BudgetLimits(calls=settings.max_model_calls, tokens=settings.max_total_tokens)
        )
        self.gateway = Gateway(transport, settings, self.ledger, self.cancel)
        self.planner = Planner(self.gateway, self.available)
        self.store = ArtifactStore(run_id)
        self.events = events if events is not None else []
        self.trace = Trace(run_id, self.events)
        self.gateway.trace = self.trace
        self.contexts = self.gateway.contexts
        self.loop = build_worker_loop()
        self.plans = {}
        # Host debug/test only; never public trace or sibling input.
        self.transcripts = {}
        self.reused = {}
        self.graph = self._compile()

    def validate_plan(self, plan: Plan) -> Plan:
        plan = Plan.model_validate_json(plan.model_dump_json())
        if len(plan.tasks) > self.settings.max_tasks:
            raise AgentFailure("PLAN_INVALID", "Plan exceeds the host task quota")
        if any(t.worker not in self.available for t in plan.tasks):
            raise AgentFailure(
                "CAPABILITY_UNAVAILABLE", "Plan requires a capability the host did not grant"
            )
        for task in plan.tasks:
            if task.worker == "analysis":
                parent = next(t for t in plan.tasks if t.task_id == task.dependencies[0])
                if parent.worker != "sql":
                    raise AgentFailure(
                        "PLAN_INVALID", "Numeric analysis requires one SQL result source"
                    )
        return plan

    def fast_plan(self, question):
        return self.planner.fast_plan(question)

    def envelope(self, state: RunState, task: TaskSpec) -> TaskEnvelope:
        refs = []
        for dependency in task.dependencies:
            parent = state["results"][key(state["plan_version"], dependency)]
            refs.extend(parent.evidence_refs)
        refs = list({r.artifact_id: r for r in refs}.values())
        root = self.ledger.accounts["root"].limits
        return TaskEnvelope(
            run_id=state["run_id"],
            plan_version=state["plan_version"],
            task=task,
            allowed_tools=sorted(CAPABILITIES[task.worker]),
            input_refs=refs,
            budget=BudgetLimits(
                calls=min(root.calls, self.settings.max_worker_turns), tokens=root.tokens
            ),
            parent_id=state["run_id"],
        )

    async def execute(self, envelope: TaskEnvelope) -> TaskResult:
        if envelope.parent_id != self.run_id or envelope.run_id != self.run_id:
            raise AgentFailure("TOOL_FORBIDDEN", "Subagent must belong to the parent run")
        task = envelope.task
        account = self.ledger.fork(key(envelope.plan_version, task.task_id), envelope.budget)
        started = time.monotonic()
        tools = ToolRegistry(
            envelope,
            self.store,
            database=self.database,
            retrieval=self.retrieval,
            cancellation=self.cancel,
            trace=self.trace,
            timeout=self.settings.mcp_timeout_seconds,
            max_sql_attempts=self.settings.max_sql_attempts,
            max_view_chars=self.settings.max_tool_view_chars,
        )
        status, error, refs = "succeeded", None, []
        self.trace.emit("worker", "started", version=envelope.plan_version, task_id=task.task_id)
        try:
            self.cancel.check()
            if task.worker in {"analysis", "report"}:
                ref = self.deterministic(envelope)
                refs = [ref]
            else:
                schema = ""
                if task.worker == "sql":
                    boot_started = time.monotonic()
                    boot_error = None
                    try:
                        schema = (await tools.invoke("database_schema", {}))["schema"]
                    except AgentFailure as exc:
                        boot_error = exc.error.code
                        raise
                    finally:
                        self.trace.emit(
                            "worker_bootstrap",
                            "failed" if boot_error else "succeeded",
                            version=envelope.plan_version,
                            task_id=task.task_id,
                            elapsed_ms=(time.monotonic() - boot_started) * 1000,
                            error_code=boot_error,
                            tool_name="database_schema",
                        )
                transcript = []
                self.transcripts[key(envelope.plan_version, task.task_id)] = transcript
                seed = initial_messages(envelope, schema)
                authority = AuthoritySnapshot.for_worker(
                    envelope,
                    self.question or task.instruction,
                    seed[0].content,
                    **self.context_metadata.get(task.task_id, {}),
                )

                def recall_memory():
                    return (
                        self.memory_store.recall(
                            authority.scope,
                            task.worker,
                            now=datetime.now(UTC),
                            source_versions=self.memory_source_versions,
                        )
                        if self.memory_store
                        else ()
                    )

                self.contexts[account] = ContextManager(
                    authority, seed, tools, self.settings, memory_loader=recall_memory
                )
                context = WorkerContext(
                    envelope,
                    tools,
                    self.gateway,
                    account,
                    WorkerLimits(
                        self.settings.max_worker_turns,
                        self.settings.max_sql_attempts,
                        self.settings.mcp_timeout_seconds,
                    ),
                    self.cancel,
                    self.trace,
                    transcript,
                )
                output = await self.loop.ainvoke(
                    {"messages": seed, "turns": 0, "done": False},
                    context=context,
                    config={"recursion_limit": self.settings.max_worker_turns * 3 + 4},
                )
                self.transcripts[key(envelope.plan_version, task.task_id)] = transcript
                if output.get("error"):
                    error = output["error"]
                    status = "cancelled" if error.category == "cancelled" else "failed"
                    refs = list(tools.refs)
                else:
                    final = output["final"]
                    refs = [r for r in tools.refs if r.artifact_id in final.artifact_ids]
                    if final.outcome == "unavailable":
                        status = "unavailable"
                        error = execution_error(
                            AgentFailure(
                                "NO_RELEVANT_DOCUMENTS", "No retrieved evidence supports this task"
                            )
                        )
        except AgentFailure as exc:
            error = execution_error(exc)
            status = "cancelled" if error.category == "cancelled" else "failed"
            refs = list(tools.refs)
        except asyncio.CancelledError:
            self.cancel.cancel()
            self.trace.emit(
                "worker",
                "cancelled",
                version=envelope.plan_version,
                task_id=task.task_id,
                error_code="CANCELLED",
            )
            raise
        except Exception:
            error = execution_error(
                AgentFailure("WORKER_ERROR", "Worker failed without exposing internal details")
            )
            status = "failed"
        result = TaskResult(
            run_id=self.run_id,
            task_id=task.task_id,
            plan_version=envelope.plan_version,
            worker=task.worker,
            status=status,
            error=error,
            evidence_refs=refs,
            usage=self.ledger.snapshot(account),
            attempts=tools.sql_attempts,
        )
        self.trace.emit(
            "worker",
            status,
            version=envelope.plan_version,
            task_id=task.task_id,
            elapsed_ms=(time.monotonic() - started) * 1000,
            error_code=error.code if error else None,
            refs=refs,
        )
        return result

    def deterministic(self, envelope: TaskEnvelope) -> EvidenceRef:
        task = envelope.task
        if task.worker == "report":
            values = {"kind": "evidence_bundle"}
        else:
            sources = [self.store.get(r) for r in envelope.input_refs if r.kind == "query"]
            if len(sources) != 1 or sources[0].query.truncated:
                raise AgentFailure(
                    "VERIFICATION_ERROR", "Analysis needs exactly one complete query result"
                )
            query = sources[0].query
            if any(c not in query.columns for c in task.columns):
                raise AgentFailure(
                    "VERIFICATION_ERROR", "Analysis references a missing result column"
                )
            with localcontext() as arithmetic:
                arithmetic.prec = 60
                try:
                    if task.operation == "sum":
                        index = query.columns.index(task.columns[0])
                        value = sum((scalar(row[index]) for row in query.rows), Decimal(0))
                    else:
                        if query.row_count != 1:
                            raise ValueError("Ratio needs one row")
                        n, d = (scalar(query.rows[0][query.columns.index(c)]) for c in task.columns)
                        if not d:
                            raise ValueError("Ratio denominator is zero")
                        value = (n / d).quantize(
                            Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN
                        )
                    text = format(value, "f")
                    if len(text) > 80:
                        raise ValueError("Analysis output is too large")
                except (ValueError, ArithmeticError) as exc:
                    raise AgentFailure(
                        "VERIFICATION_ERROR", "Exact numeric inputs/valid denominator required"
                    ) from exc
            values = {"operation": task.operation, "value": text, "unit": "unconfirmed"}
        return self.store.put(
            Artifact(
                run_id=self.run_id,
                task_id=task.task_id,
                plan_version=envelope.plan_version,
                kind=task.worker,
                source="deterministic/P4",
                values=values,
                parents=envelope.input_refs,
            )
        )

    def verify(self, state: RunState, task: TaskSpec, result: TaskResult) -> VerificationResult:
        checks = ["identity", "capability", "evidence", "shape", "dependencies"]
        error = None
        try:
            result = TaskResult.model_validate_json(result.model_dump_json())
            if (result.run_id, result.task_id, result.plan_version, result.worker) != (
                self.run_id,
                task.task_id,
                state["plan_version"],
                task.worker,
            ):
                raise AgentFailure("VERIFICATION_ERROR", "Result identity differs from delegation")
            if task.worker not in self.available:
                raise AgentFailure("VERIFICATION_ERROR", "Result used an unavailable capability")
            for dep in task.dependencies:
                if (
                    state["verifications"].get(key(state["plan_version"], dep), None) is None
                    or state["verifications"][key(state["plan_version"], dep)].status != "passed"
                ):
                    raise AgentFailure("VERIFICATION_ERROR", "Dependency did not pass verification")
            envelope = self.envelope(state, task)
            allowed = {r.artifact_id for r in envelope.input_refs}
            expected_kind = {
                "sql": "query",
                "rag": "documents",
                "analysis": "analysis",
                "report": "report",
            }[task.worker]
            for ref in result.evidence_refs:
                artifact = self.store.get(ref)
                expected_version = state["plan_version"]
                if result.reused_from:
                    if (
                        self.reused.get(key(state["plan_version"], task.task_id))
                        != result.reused_from
                    ):
                        raise AgentFailure("VERIFICATION_ERROR", "Untrusted stale-result reuse")
                    expected_version = int(result.reused_from.split(":", 1)[0])
                if (artifact.run_id, artifact.task_id, artifact.plan_version, artifact.kind) != (
                    self.run_id,
                    task.task_id,
                    expected_version,
                    expected_kind,
                ):
                    raise AgentFailure(
                        "VERIFICATION_ERROR", "Evidence is outside delegated task/version"
                    )
                if artifact.query and artifact.query.row_count > self.settings.max_rows:
                    raise AgentFailure("VERIFICATION_ERROR", "Query result exceeds host row limit")
                if artifact.documents and any(
                    text_hash(d.text) != d.sha256 for d in artifact.documents.documents
                ):
                    raise AgentFailure("VERIFICATION_ERROR", "Document citation content changed")
                if not result.reused_from and any(
                    r.artifact_id not in allowed for r in artifact.parents
                ):
                    raise AgentFailure("VERIFICATION_ERROR", "Artifact cites an undelegated parent")
                if task.worker in {"analysis", "report"} and (
                    {r.model_dump_json() for r in artifact.parents}
                    != {r.model_dump_json() for r in envelope.input_refs}
                ):
                    raise AgentFailure(
                        "VERIFICATION_ERROR", "Derived artifact omitted dependency evidence"
                    )
        except (ValueError, AgentFailure) as exc:
            error = execution_error(
                exc
                if isinstance(exc, AgentFailure)
                else AgentFailure("VERIFICATION_ERROR", "Invalid result contract")
            )
        return VerificationResult(
            task_id=task.task_id,
            plan_version=state["plan_version"],
            status="failed"
            if error or result.status in {"failed", "blocked", "cancelled"}
            else "unavailable"
            if result.status == "unavailable"
            else "passed",
            checks=checks,
            error=error or result.error,
        )

    def _compile(self):
        def step(state):
            self.cancel.check()
            if state.get("steps", 0) >= self.settings.max_steps:
                raise AgentFailure("STEP_LIMIT", "Outer graph step budget exhausted")
            return state.get("steps", 0) + 1

        async def planner(state):
            started = time.monotonic()
            try:
                if not self.plans and state["run_id"] != self.run_id:
                    self.run_id = state["run_id"]
                    self.store = ArtifactStore(self.run_id)
                    self.trace = Trace(self.run_id, self.events)
                    self.gateway.trace = self.trace
                steps = step(state)
                self.question = state["question"]
                plan = self.fast_plan(state["question"]) or await self.planner.plan(
                    state["question"]
                )
                plan = self.validate_plan(plan)
                self.plans[1] = plan
                self.trace.emit(
                    "planner",
                    "unsupported" if plan.unsupported else "succeeded",
                    elapsed_ms=(time.monotonic() - started) * 1000,
                    usage=self.ledger.snapshot(),
                )
                return Command(
                    update={
                        "plan": plan,
                        "plan_version": 1,
                        "steps": steps,
                        "replans": 0,
                        "status": "unsupported" if plan.unsupported else "running",
                        "results": {},
                        "verifications": {},
                    },
                    goto="finish" if plan.unsupported else "scheduler",
                )
            except (AgentFailure, ValueError) as exc:
                return fail(exc, "planner", state)

        def fail(exc, node, state):
            error = (
                exc.error
                if isinstance(exc, AgentFailure)
                else AgentError(code="PLAN_INVALID", message="Invalid task plan")
            )
            self.trace.emit(
                node, "failed", version=state.get("plan_version", 1), error_code=error.code
            )
            return Command(
                update={
                    "status": "cancelled" if error.code == "CANCELLED" else "failed",
                    "error": error,
                },
                goto="finish",
            )

        def scheduler(state):
            try:
                steps = step(state)
                version = state["plan_version"]
                tasks = state["plan"].tasks
                pending = [t for t in tasks if key(version, t.task_id) not in state["results"]]
                ready = [
                    t
                    for t in pending
                    if all(
                        state["verifications"].get(key(version, d))
                        and state["verifications"][key(version, d)].status == "passed"
                        for d in t.dependencies
                    )
                ]
                self.trace.emit("scheduler", "dispatch", version=version)
                if ready:
                    return Command(
                        update={"steps": steps},
                        goto=[
                            Send("worker", {"envelope": self.envelope(state, t)})
                            for t in ready[: self.settings.max_parallel_workers]
                        ],
                    )
                # Terminal dependencies block descendants; do not run them on partial evidence.
                blocked = {
                    key(version, t.task_id): TaskResult(
                        run_id=self.run_id,
                        task_id=t.task_id,
                        plan_version=version,
                        worker=t.worker,
                        status="blocked",
                        error=execution_error(
                            AgentFailure("DEPENDENCY_FAILED", "Required dependency did not succeed")
                        ),
                    )
                    for t in pending
                }
                return Command(update={"steps": steps, "results": blocked}, goto="verifier")
            except AgentFailure as exc:
                return fail(exc, "scheduler", state)

        async def worker(dispatch):
            envelope = dispatch["envelope"]
            result = await self.execute(envelope)
            return {"results": {key(result.plan_version, result.task_id): result}}

        def verifier(state):
            try:
                steps = step(state)
                version = state["plan_version"]
                updates = {}
                # Dependencies were verified in earlier supersteps; never trust siblings early.
                for task in state["plan"].tasks:
                    k = key(version, task.task_id)
                    if k in state["results"] and k not in state["verifications"]:
                        updates[k] = self.verify(state, task, state["results"][k])
                self.trace.emit("verifier", "completed", version=version)
                combined = {**state["verifications"], **updates}
                pending = [
                    t
                    for t in state["plan"].tasks
                    if key(version, t.task_id) not in state["results"]
                ]
                if pending:
                    goto = "scheduler"
                else:
                    failed = [
                        state["results"][key(version, t.task_id)]
                        for t in state["plan"].tasks
                        if combined[key(version, t.task_id)].status == "failed"
                    ]
                    can_replan = (
                        failed
                        and all(
                            r.error and (r.error.retryable or r.status == "blocked") for r in failed
                        )
                        and state.get("replans", 0) < self.settings.max_replans
                    )
                    goto = "replan" if can_replan else "finish"
                return Command(update={"steps": steps, "verifications": updates}, goto=goto)
            except AgentFailure as exc:
                return fail(exc, "verifier", state)

        async def replan(state):
            started = time.monotonic()
            try:
                steps = step(state)
                version = state["plan_version"] + 1
                feedback = [
                    {
                        "task_id": r.task_id,
                        "status": r.status,
                        "error_code": r.error.code if r.error else None,
                    }
                    for r in state["results"].values()
                    if r.plan_version == state["plan_version"]
                ]
                plan = self.validate_plan(
                    await self.planner.plan(state["question"], feedback=feedback)
                )
                self.plans[version] = plan
                # Reuse only unchanged, verified task subtrees; source permissions never expand.
                old = {t.task_id: t for t in state["plan"].tasks}
                reused = {}
                for _ in plan.tasks:
                    for task in plan.tasks:
                        prior = key(state["plan_version"], task.task_id)
                        now = key(version, task.task_id)
                        if (
                            task.dependencies
                            or now in reused
                            or old.get(task.task_id) != task
                            or not state["verifications"].get(prior)
                            or state["verifications"][prior].status != "passed"
                        ):
                            continue
                        if not all(key(version, d) in reused for d in task.dependencies):
                            continue
                        original = state["results"][prior]
                        origin = original.reused_from or prior
                        self.reused[now] = origin
                        reused[now] = original.model_copy(
                            update={"plan_version": version, "reused_from": origin}
                        )
                self.trace.emit(
                    "replan",
                    "succeeded",
                    version=version,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                    usage=self.ledger.snapshot(),
                )
                return Command(
                    update={
                        "steps": steps,
                        "plan": plan,
                        "plan_version": version,
                        "replans": state.get("replans", 0) + 1,
                        "results": reused,
                        "status": "unsupported" if plan.unsupported else "running",
                    },
                    goto="finish" if plan.unsupported else "verifier",
                )
            except (AgentFailure, ValueError) as exc:
                return fail(exc, "replan", state)

        def finish(state):
            status = state.get("status", "failed")
            error = state.get("error")
            terminal_missing = {}
            if self.cancel.event.is_set():
                status = "cancelled"
                error = AgentError(code="CANCELLED", message="Parent run was cancelled")
            if status in {"cancelled", "failed"}:
                for task in state.get("plan", Plan(unsupported=True)).tasks:
                    k = key(state["plan_version"], task.task_id)
                    if k not in state.get("results", {}):
                        terminal_missing[k] = TaskResult(
                            run_id=self.run_id,
                            task_id=task.task_id,
                            plan_version=state["plan_version"],
                            worker=task.worker,
                            status="cancelled" if status == "cancelled" else "blocked",
                            error=execution_error(
                                AgentFailure(
                                    "CANCELLED" if status == "cancelled" else "DEPENDENCY_FAILED",
                                    "Parent run ended before this task could execute",
                                )
                            ),
                        )
            current = [
                r
                for r in state.get("results", {}).values()
                if r.plan_version == state.get("plan_version")
            ]
            if status == "running":
                rejected = [
                    v
                    for v in state["verifications"].values()
                    if v.plan_version == state["plan_version"] and v.status == "failed"
                ]
                unavailable = any(r.status == "unavailable" for r in current)
                if self.cancel.event.is_set():
                    status = "cancelled"
                    error = AgentError(code="CANCELLED", message="Parent run was cancelled")
                elif rejected:
                    status = "failed"
                    primary = next(
                        (r.error for r in current if r.error and r.status != "blocked"), None
                    )
                    error = AgentError(
                        **{
                            k: getattr(primary or rejected[0].error, k)
                            for k in AgentError.model_fields
                        }
                    )
                else:
                    status = "unavailable" if unavailable else "succeeded"
            completion = completion_gate(
                {
                    **state,
                    "status": status,
                    "error": error,
                    "results": {**state.get("results", {}), **terminal_missing},
                },
                self.store,
                self.verify,
                original_plan=self.plans.get(1),
            )
            if "FINAL_EVIDENCE_INVALID" in completion.reason_codes:
                status = "failed"
                error = AgentError(
                    code="EVIDENCE_INVALID", message="Final evidence validation failed"
                )
            legacy_task, legacy_result = None, None
            for task in state.get("plan", Plan(unsupported=True)).tasks:
                if task.worker != "sql":
                    continue
                result = state.get("results", {}).get(
                    key(state.get("plan_version", 1), task.task_id)
                )
                if result is None:
                    continue
                legacy_task = SQLTask(
                    task_id=self.run_id + ":" + task.task_id, question=task.instruction
                )
                artifact = (
                    next(
                        (
                            self.store.get(ref)
                            for ref in result.evidence_refs
                            if ref.kind == "query"
                        ),
                        None,
                    )
                    if "FINAL_EVIDENCE_INVALID" not in completion.reason_codes
                    else None
                )
                if result.status == "succeeded" and artifact:
                    legacy_result = SQLAgentResult(
                        task_id=legacy_task.task_id,
                        status="succeeded",
                        sql=artifact.sql,
                        result=artifact.query,
                        attempts=result.attempts,
                    )
                elif result.error:
                    legacy_result = SQLAgentResult(
                        task_id=legacy_task.task_id,
                        status="failed",
                        error=AgentError(
                            **{k: getattr(result.error, k) for k in AgentError.model_fields}
                        ),
                        attempts=result.attempts,
                    )
                break
            if status == "unsupported":
                answer = "当前可用能力无法回答该请求；真实文档检索尚未配置。"
            elif status in {"failed", "cancelled"}:
                answer = f"执行失败 [{cell(error.code)}]：{cell(error.message)}"
            else:
                lines = ["SaaS 任务工具结果；来源与证据逐项列出。任务验证不替代 P3 指标口径验证。"]
                if completion.status != "completed":
                    lines.append(
                        "完成判定："
                        + completion.status
                        + "；"
                        + ", ".join(completion.reason_codes)
                        + "。以下仅为受限工具结果，不能视为已验证业务指标或完整回答。"
                    )
                seen = set()

                def render(ref):
                    if ref.artifact_id in seen:
                        return
                    seen.add(ref.artifact_id)
                    artifact = self.store.get(ref)
                    lines.append(
                        "\n证据：`" + ref.artifact_id + "`；任务 " + cell(artifact.task_id)
                    )
                    if artifact.query:
                        q = artifact.query
                        lines.extend(
                            [
                                "| " + " | ".join(cell(c) for c in q.columns) + " |",
                                "| " + " | ".join("---" for _ in q.columns) + " |",
                            ]
                        )
                        lines.extend(
                            "| " + " | ".join(cell(c) for c in row) + " |" for row in q.rows
                        )
                        if q.truncated:
                            lines.append("结果已截断，不能作为完整明细或全量统计。")
                    elif artifact.documents:
                        lines.append(
                            "组件检索替身，非真实 RAG 验收。"
                            if artifact.documents.fixture
                            else "检索文档："
                        )
                        lines.extend(
                            cell(d.source) + " @ " + cell(d.version) + "：" + cell(d.text)
                            for d in artifact.documents.documents
                        )
                    elif artifact.kind == "analysis":
                        lines.append(
                            "确定性计算（业务单位未确认）：" + cell(artifact.values.get("value"))
                        )
                    for parent in artifact.parents:
                        render(parent)

                for result in current:
                    if (
                        result.status == "succeeded"
                        and state["verifications"][key(result.plan_version, result.task_id)].status
                        == "passed"
                    ):
                        for ref in result.evidence_refs:
                            render(ref)
                    elif result.status == "unavailable":
                        lines.append(cell(result.error.message))
                answer = "\n".join(lines)
            self.trace.emit(
                "completion",
                completion.status,
                version=state.get("plan_version", 1),
                error_code=completion.reason_codes[0] if completion.reason_codes else None,
            )
            self.trace.emit(
                "finish",
                status,
                version=state.get("plan_version", 1),
                error_code=error.code if error else None,
            )
            return {
                "status": status,
                "error": error,
                "answer": answer,
                "task": legacy_task,
                "result": legacy_result,
                "results": terminal_missing,
                "completion": completion,
            }

        builder = StateGraph(RunState)
        for name, fn in (
            ("planner", planner),
            ("scheduler", scheduler),
            ("worker", worker),
            ("verifier", verifier),
            ("replan", replan),
            ("finish", finish),
        ):
            builder.add_node(name, fn)
        builder.add_edge(START, "planner")
        builder.add_edge("worker", "verifier")
        builder.add_edge("finish", END)
        return builder.compile()
