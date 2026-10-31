"""Fixed capability registry; no shell, filesystem, management or model-created tools."""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Protocol

from pydantic import Field

from datapilot.contracts import AgentFailure, Contract, QueryResult
from datapilot.ingestion.common import digest
from datapilot.orchestration.context import tool_view
from datapilot.orchestration.contracts import (
    Artifact,
    Digest,
    RagCompletionReceipt,
    RagSubmission,
    SearchResult,
)
from datapilot.orchestration.rag_completion import (
    PROTOCOL,
    SUBMIT,
    enabled,
    goal_hash,
    relevant_ids,
    retrieval_goal,
    validate_submission,
)
from datapilot.orchestration.runtime import Cancellation, text_hash


class Empty(Contract):
    pass


class SQLArguments(Contract):
    sql: str = Field(min_length=1, max_length=12000)


class SearchArguments(Contract):
    query: str = Field(min_length=1, max_length=512)
    top_k: int = Field(default=3, ge=1, le=5)


class ContextReadArguments(Contract):
    artifact_id: Digest
    start: int = Field(default=0, ge=0, le=16 * 1024**2)
    max_chars: int = Field(default=512, ge=64, le=2048)
    document_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description=(
            "Required for document artifacts: use an actual documents[].document_id "
            "from search_documents; omit only for context/schema artifacts."
        ),
    )


class RetrievalTools(Protocol):
    async def search(self, query: str, top_k: int) -> SearchResult: ...


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    arguments: type[Contract]
    description: str

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments.model_json_schema(),
            },
        }


DEFINITIONS = {
    SUBMIT: ToolDefinition(
        SUBMIT,
        RagSubmission,
        "Request host-verified RAG completion using actual artifact_refs IDs, "
        "never document_id/chunk_id. Call alone; no sibling or invented references. "
        "complete needs verified retrieval relevance/requirements; empty retrieval is "
        "unavailable; nonempty inadequate passages are insufficient.",
    ),
    "database_schema": ToolDefinition(
        "database_schema", Empty, "Read approved SaaS schema metadata"
    ),
    "query_database": ToolDefinition(
        "query_database", SQLArguments, "Read-only PostgreSQL SaaS SELECT; no write or file tools"
    ),
    "search_documents": ToolDefinition(
        "search_documents",
        SearchArguments,
        "Retrieve permitted documents and immutable source/version citations",
    ),
    "read_context": ToolDefinition(
        "read_context",
        ContextReadArguments,
        "Read bounded task-owned context/schema/documents. For documents pass BOTH "
        "artifact_id and the actual documents[].document_id from search_documents. "
        "Never infer document_id from artifact/chunk IDs. No paths, SQL rows or siblings",
    ),
}
CAPABILITIES = {
    "sql": frozenset({"database_schema", "query_database", "read_context"}),
    "rag": frozenset({"search_documents", "read_context"}),
    "analysis": frozenset(),
    "report": frozenset(),
}


def delegated_tools(worker, retrieval=None):
    names = CAPABILITIES[worker]
    return names | {SUBMIT} if worker == "rag" and enabled(retrieval) else names


class ToolRegistry:
    def __init__(
        self,
        envelope,
        store,
        *,
        database=None,
        retrieval=None,
        cancellation=None,
        trace=None,
        timeout=10,
        max_sql_attempts=2,
        max_view_chars=4096,
        durability=None,
        rag_goal=None,
        original_query=None,
    ):
        self.envelope, self.store = envelope, store
        self.database = database if envelope.task.worker == "sql" else None
        self.retrieval = retrieval if envelope.task.worker == "rag" else None
        approved = delegated_tools(envelope.task.worker, retrieval)
        if not set(envelope.allowed_tools) <= approved:
            raise AgentFailure("TOOL_FORBIDDEN", "Child permissions exceed its worker capability")
        self.allowed = frozenset(envelope.allowed_tools)
        self.refs = []
        self.context_refs = []
        self.sql_attempts = 0
        self.search_attempts = 0
        self.cancel = cancellation or Cancellation()
        self.trace, self.timeout = trace, timeout
        self.max_sql_attempts, self.max_view_chars = max_sql_attempts, max_view_chars
        self.durability = durability
        self.rag_control = envelope.task.worker == "rag" and enabled(retrieval)
        self.rag_goal = json.loads(json.dumps(rag_goal)) if rag_goal is not None else None
        self.original_query = original_query
        if original_query is not None:
            if not self.rag_control:
                raise AgentFailure("TOOL_FORBIDDEN", "Original query needs host-bound RAG tools")
            try:
                original = SearchArguments(query=original_query)
                expected = retrieval_goal(original.query, retrieval)
                # The parent verified the trusted ReportScope proof; this check binds
                # the original query and fixed retrieval semantics, not a model claim.
                semantic_keys = expected.keys() - {"scope_attestation", "completion_eligible"}
                if (
                    not original.query.strip()
                    or self.rag_goal is None
                    or any(expected[k] != self.rag_goal.get(k) for k in semantic_keys)
                    or getattr(retrieval, "goal_sha256", text_hash(original.query))
                    != text_hash(original.query)
                ):
                    raise ValueError("Host retrieval goal differs")
            except ValueError:
                raise AgentFailure(
                    "RAG_QUERY_POLICY", "Use the exact bounded, host-bound document goal"
                ) from None
        self.accepted = None
        self._correction = None
        self._submission_calls = {}
        self.model_response_sha256 = None
        if durability:
            durability.hydrate_tools(self)

    def active_tools(self):
        names = self.allowed
        if self.rag_control and self.accepted is not None:
            return names & {SUBMIT}
        if self.rag_control and self.search_attempts >= self.retrieval.max_search_attempts:
            names = names - {"search_documents"}
        return names

    def schemas(self, *, initial=False):
        names = self.allowed if initial else self.active_tools()
        schemas = [DEFINITIONS[name].schema() for name in sorted(names)]
        if self.original_query is not None:
            for schema in schemas:
                if schema["function"]["name"] == "search_documents":
                    # Stable for the whole task: replay must use the original schema even
                    # if a committed search is ahead of the graph's current checkpoint.
                    schema["function"]["parameters"]["properties"]["query"]["description"] = (
                        "For the FIRST search use this exact host document goal, without "
                        "translation or truncation. Later searches may choose a query within "
                        "the same goal and existing quota. HOST_FIRST_QUERY_JSON: "
                        + json.dumps(self.original_query, ensure_ascii=False)
                    )
        return schemas

    def validate_phase(self, names, authority):
        if set(authority) != set(self.allowed) or set(names) != set(self.active_tools()):
            raise AgentFailure(
                "TOOL_FORBIDDEN", "Model view differs from host-enforced phase tools"
            )

    def correct_completion(self, reason, trigger):
        if not self.rag_control:
            raise AgentFailure("TOOL_FORBIDDEN", "Completion correction is only for scoped RAG")
        notice = {"protocol": PROTOCOL, "reason": reason, "trigger": trigger, "attempt": 1}
        if self.durability:
            notice = self.durability.rag_correction(self.envelope, notice)
        elif self._correction is not None and self._correction != notice:
            raise AgentFailure(
                "RAG_COMPLETION_REPAIR_EXHAUSTED", "One completion correction was already used"
            )
        self._correction = notice
        return notice

    def adopt_completion(self, raw):
        receipt = RagCompletionReceipt.model_validate(raw)
        verdict = validate_submission(
            self.envelope, self.store, self.refs, receipt.submission, self.retrieval, self.rag_goal
        )
        if verdict != receipt.verdict or receipt.goal_sha256 != goal_hash(self.rag_goal):
            raise AgentFailure("RECOVERY_IDENTITY", "Completion goal/verdict differs from host")
        if receipt.submission.outcome == "complete" and receipt.relevant_chunk_ids != relevant_ids(
            self.store,
            [r for r in self.refs if r.artifact_id in receipt.submission.artifact_ids],
            self.retrieval,
            self.rag_goal,
        ):
            raise AgentFailure("RECOVERY_CONFLICT", "Relevant passage set changed")
        if self.accepted is not None and self.accepted != receipt:
            raise AgentFailure("RECOVERY_CONFLICT", "Conflicting completion receipts")
        self.accepted = receipt

    async def invoke(self, name, arguments, *, call_id=None):
        """Sealed host lifecycle; there are no user callbacks that can override denial.

        Contract → delegated capability/bound MCP handle → cancellation/attempt budget/
        timeout → call → validated full artifact → bounded model view → redacted trace.
        DatasetScope/DB grants stay enforced inside the already-bound MCP session.
        """
        started, error = time.monotonic(), None
        before = len(self.refs)
        call_key, replayed = None, False
        try:
            if name not in DEFINITIONS:
                raise AgentFailure("TOOL_FORBIDDEN", "Tool is outside delegated capability")
            try:
                if len(json.dumps(arguments, ensure_ascii=False)) > 13000:
                    raise ValueError("Arguments too large")
                args = DEFINITIONS[name].arguments.model_validate(arguments)
            except (ValueError, TypeError) as exc:
                raise AgentFailure("INPUT_INVALID", "Tool arguments failed their contract") from exc
            if name not in self.allowed:
                raise AgentFailure("TOOL_FORBIDDEN", "Tool is outside delegated capability")
            if name == SUBMIT and not call_id:
                raise AgentFailure("INPUT_INVALID", "Submission needs an actual tool call ID")
            if (name in {"database_schema", "query_database"} and self.database is None) or (
                name == "search_documents" and self.retrieval is None
            ):
                raise AgentFailure("TOOL_FORBIDDEN", "No host-bound tool session was delegated")
            self.cancel.check()
            if self.durability:
                call_key, cached = self.durability.begin_tool(
                    self.envelope, name, arguments, call_id
                )
                if cached is not None:
                    replayed = True
                    self.durability.adopt_payload(self, cached)
                    if cached.get("error"):
                        item = cached["error"]
                        raise AgentFailure(
                            item["code"], item["message"], retryable=item["retryable"]
                        )
                    return cached
            if self.accepted is not None and name != SUBMIT:
                raise AgentFailure("TOOL_FORBIDDEN", "No data tools after accepted completion")
            if name == "query_database" and self.sql_attempts >= self.max_sql_attempts:
                raise AgentFailure("SQL_ATTEMPTS_EXHAUSTED", "SQL attempt limit reached")
            search_limit = getattr(self.retrieval, "max_search_attempts", None)
            if (
                name == "search_documents"
                and search_limit is not None
                and self.search_attempts >= search_limit
            ):
                raise AgentFailure("RAG_ATTEMPTS_EXHAUSTED", "At most two searches per worker task")
            if name == "search_documents":
                if (
                    self.original_query is not None
                    and self.search_attempts == 0
                    and args.query != self.original_query
                ):
                    raise AgentFailure(
                        "RAG_QUERY_POLICY", "First search must use the exact host document goal"
                    )
                self.search_attempts += 1
            if name == "query_database":
                # No await before reservation: simultaneous calls cannot both take the last slot.
                self.sql_attempts += 1
            payload = await self.cancel.wait_for(self._dispatch(name, args), self.timeout)
            if name == SUBMIT:
                # A receipt only becomes accepted after the existing Journal commits it.
                prior = self._submission_calls.get(call_id)
                if prior is not None and prior != digest(arguments):
                    raise AgentFailure("RECOVERY_CONFLICT", "Submission call ID was rebound")
                receipt = self.accepted or RagCompletionReceipt(
                    call_id=call_id,
                    submission=args,
                    verdict=payload.pop("verdict"),
                    goal_sha256=goal_hash(self.rag_goal),
                    model_response_sha256=self.model_response_sha256,
                    relevant_chunk_ids=(
                        relevant_ids(
                            self.store,
                            [r for r in self.refs if r.artifact_id in args.artifact_ids],
                            self.retrieval,
                            self.rag_goal,
                        )
                        if args.outcome == "complete"
                        else []
                    ),
                )
                if receipt.submission != args:
                    raise AgentFailure("RECOVERY_CONFLICT", "Accepted completion cannot change")
                payload = {"rag_completion": receipt.model_dump(mode="json")}
                if self.durability:
                    self.durability.backend.hit("rag_submission_validated")
            if self.durability:
                self.durability.backend.hit("tool_artifact")
                self.durability.finish_tool(call_key, payload, (time.monotonic() - started) * 1000)
            if name == SUBMIT:
                self.adopt_completion(payload["rag_completion"])
                self._submission_calls[call_id] = digest(arguments)
                if self.durability:
                    self.durability.backend.hit("rag_submission_committed")
            return payload
        except asyncio.CancelledError:
            error = AgentFailure("CANCELLED", "Tool coroutine was cancelled")
            raise
        except AgentFailure as exc:
            error = exc
            raise
        except Exception as exc:
            error = AgentFailure("TOOL_OUTPUT_INVALID", "Tool failed its validated output contract")
            raise error from exc
        finally:
            if self.durability and call_key and error and not replayed:
                self.durability.finish_tool(
                    call_key,
                    {"error": error.error.model_dump()},
                    (time.monotonic() - started) * 1000,
                    uncertain=error.error.code
                    in {"CANCELLED", "TOOL_TIMEOUT", "TOOL_ERROR", "TOOL_OUTPUT_INVALID"},
                )
            if self.trace:
                self.trace.emit(
                    "tool",
                    "failed" if error else "succeeded",
                    version=self.envelope.plan_version,
                    task_id=self.envelope.task.task_id,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                    error_code=error.error.code if error else None,
                    tool_name=name if name in DEFINITIONS else "undeclared",
                    tool_call_id=call_id,
                    refs=self.refs[before:] if not error else (),
                )

    async def _dispatch(self, name, args):
        if name == SUBMIT:
            if not self.rag_control:
                raise AgentFailure("TOOL_FORBIDDEN", "No RAG completion capability")
            return {
                "verdict": validate_submission(
                    self.envelope, self.store, self.refs, args, self.retrieval, self.rag_goal
                )
            }
        if name == "database_schema":
            value = await self.database.schema()
            if not isinstance(value, str) or not 1 <= len(value) <= 12000:
                raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid schema response")
            # Schema is authoritative input: store it whole, never silently crop it.
            ref = self.store.put(
                Artifact(
                    run_id=self.envelope.run_id,
                    task_id=self.envelope.task.task_id,
                    plan_version=self.envelope.plan_version,
                    kind="schema",
                    source="host-bound/MCP",
                    values={"schema": value},
                )
            )
            self.context_refs.append(ref)
            return {"schema": value, "context_refs": [ref.model_dump()]}
        if name == "read_context":
            ref = next(
                (r for r in [*self.context_refs, *self.refs] if r.artifact_id == args.artifact_id),
                None,
            )
            if ref is None:
                raise AgentFailure(
                    "TOOL_FORBIDDEN", "Context reference was not delegated to this task"
                )
            item = self.store.get(ref)
            if (item.run_id, item.task_id, item.plan_version) != (
                self.envelope.run_id,
                self.envelope.task.task_id,
                self.envelope.plan_version,
            ) or item.kind not in {"context", "schema", "documents"}:
                raise AgentFailure("TOOL_FORBIDDEN", "Context reference belongs to another task")
            if item.kind == "documents":
                if self.envelope.task.worker != "rag":
                    raise AgentFailure(
                        "TOOL_FORBIDDEN", "Only its RAG worker can read document text"
                    )
                doc = next(
                    (d for d in item.documents.documents if d.document_id == args.document_id), None
                )
                if doc is None:
                    raise AgentFailure("INPUT_INVALID", "Choose an actual retrieved document ID")
                text = doc.text
            else:
                if args.document_id is not None:
                    raise AgentFailure(
                        "INPUT_INVALID", "Document selection does not apply to this artifact"
                    )
                text = item.values["messages" if item.kind == "context" else "schema"]
            if args.start > len(text):
                raise AgentFailure("INPUT_INVALID", "Page offset is beyond the artifact")
            size = min(args.max_chars, max(64, self.max_view_chars - 512))
            payload = {
                "context_refs": [ref.model_dump()],
                "text": text[args.start : args.start + size],
                "start": args.start,
                "untrusted_data": True,
            }
            if item.kind == "documents" and doc.citation is not None:
                payload["citation_ref"] = doc.citation.model_dump(
                    include={"chunk_id", "index_version"}, mode="json"
                )
            while True:
                end = args.start + len(payload["text"])
                payload["next_offset"] = end if end < len(text) else None
                if len(json.dumps(payload, ensure_ascii=False)) <= self.max_view_chars:
                    return payload
                payload["text"] = payload["text"][: len(payload["text"]) // 2]
        if name == "query_database":
            value = await self.database.execute(args.sql)
            value = QueryResult.model_validate_json(value.model_dump_json())
            artifact = Artifact(
                run_id=self.envelope.run_id,
                task_id=self.envelope.task.task_id,
                plan_version=self.envelope.plan_version,
                kind="query",
                source="saas/PostgreSQL",
                sql=args.sql,
                query=value,
            )
        else:
            value = await self.retrieval.search(args.query, args.top_k)
            value = SearchResult.model_validate_json(value.model_dump_json())
            if not value.fixture:
                if not hasattr(self.retrieval, "validate_result"):
                    raise AgentFailure(
                        "TOOL_OUTPUT_INVALID", "Real retrieval requires a host source verifier"
                    )
                self.retrieval.validate_result(value)
            if len(value.documents) > args.top_k or any(
                text_hash(d.text) != d.sha256 for d in value.documents
            ):
                raise AgentFailure("TOOL_OUTPUT_INVALID", "Invalid document source/hash contract")
            artifact = Artifact(
                run_id=self.envelope.run_id,
                task_id=self.envelope.task.task_id,
                plan_version=self.envelope.plan_version,
                kind="documents",
                source="retrieval-fixture" if value.fixture else "retrieval",
                documents=value,
            )
        ref = self.store.put(artifact)
        self.refs.append(ref)
        return tool_view(artifact, ref, self.max_view_chars)
