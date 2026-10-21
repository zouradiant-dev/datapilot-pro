"""Domain external-call boundaries, not a graph replay engine. Unknown means stop."""

import json

from langchain_core.messages import messages_from_dict, messages_to_dict

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.contracts import EvidenceRef
from datapilot.persistence.backend import execute, json_value


class Journal:
    def __init__(self, backend, ledger, store):
        self.backend, self.ledger, self.store = backend, ledger, store

    def model_identity(self, account, messages, tools):
        fingerprint = digest({"messages": messages_to_dict(messages), "tools": tools})
        return "model:" + account + ":" + fingerprint, fingerprint

    def require_known_execution(self, conn):
        if execute(
            conn,
            "SELECT 1 FROM execution.calls WHERE run_id=:run AND status='uncertain' LIMIT 1",
            run=self.backend.run_id,
        ).first():
            raise AgentFailure("RECOVERY_UNCERTAIN", "Unconfirmed execution blocks new requests")

    def cached_model(self, account, messages, tools):
        key, _ = self.model_identity(account, messages, tools)
        with self.backend.transaction() as conn:
            self.require_known_execution(conn)
            row = self._row(conn, key)
            if row and row["status"] == "complete":
                return messages_from_dict([row["payload"]])[0]
        return None

    def _row(self, conn, key):
        row = (
            execute(
                conn,
                "SELECT * FROM execution.calls WHERE run_id=:run AND call_key=:key FOR UPDATE",
                run=self.backend.run_id,
                key=key,
            )
            .mappings()
            .one_or_none()
        )
        if (
            row
            and row["status"] == "complete"
            and (row["payload"] is None or digest(row["payload"]) != row["payload_hash"])
        ):
            raise AgentFailure("RECOVERY_CORRUPT", "Persisted external result hash differs")
        return row

    def begin_model(
        self, account, messages, tools, text, output_tokens, reservation, *, identity=None
    ):
        self.backend.assert_lease()
        key, fingerprint = identity or self.model_identity(account, messages, tools)
        with self.backend.transaction() as conn:
            self.require_known_execution(conn)
            row = self._row(conn, key)
            if row:
                if row["fingerprint"] != fingerprint or row["status"] != "complete":
                    raise AgentFailure("RECOVERY_UNCERTAIN", "External model result is uncertain")
                if reservation:
                    self.ledger.mutate(
                        lambda: self.ledger.record_settlement(reservation, None, released=True),
                        conn,
                    )
                return key, None, messages_from_dict([row["payload"]])[0]

            def reserve():
                if reservation:
                    BudgetLedger.check_ticket(
                        self.ledger, reservation, account, len(text.encode()) + 128 + output_tokens
                    )
                    return reservation
                return BudgetLedger.reserve_batch(
                    self.ledger, account, [(len(text.encode()) + 128, output_tokens)]
                )[0]

            ticket = self.ledger.mutate(reserve, conn)
            execute(
                conn,
                """INSERT INTO execution.calls
                (run_id,call_key,fingerprint,kind,account,status,ticket)
                VALUES (:run,:key,:fingerprint,'model',:account,'issued',:ticket)""",
                run=self.backend.run_id,
                key=key,
                fingerprint=fingerprint,
                account=account,
                ticket=ticket,
            )
        self.backend.hit("model_issued")
        return key, ticket, None

    def finish_model(self, key, ticket, response, actual, elapsed_ms):
        self.backend.assert_lease()
        error = None
        with self.backend.transaction() as conn:
            row = self._row(conn, key)
            if row["status"] == "complete":
                return

            def settle():
                self.ledger.record_settlement(ticket, actual)

            # An overage must remain charged even though it raises a budget error.
            _, error = self.ledger._apply(settle, conn)
            payload = messages_to_dict([response])[0] if response is not None else None
            execute(
                conn,
                """UPDATE execution.calls SET status=:status,
                payload=CAST(:payload AS jsonb),payload_hash=:hash,
                usage=CAST(:usage AS jsonb),elapsed_ms=:ms WHERE run_id=:run AND call_key=:key""",
                run=self.backend.run_id,
                key=key,
                status="complete" if response is not None else "uncertain",
                payload=json_value(payload),
                hash=digest(payload) if payload else None,
                usage=json_value(response.usage_metadata if response else None),
                ms=elapsed_ms,
            )
        if error:
            raise error
        self.backend.hit("model_committed")

    def begin_tool(self, envelope, name, arguments, call_id):
        self.backend.assert_lease()
        account = f"{envelope.plan_version}:{envelope.task.task_id}"
        key = "tool:" + account + ":" + (call_id or "bootstrap-" + name)
        fingerprint = digest({"name": name, "arguments": arguments})
        with self.backend.transaction() as conn:
            self.require_known_execution(conn)
            row = self._row(conn, key)
            if row:
                if row["fingerprint"] != fingerprint:
                    raise AgentFailure(
                        "RECOVERY_CONFLICT", "Tool call ID was rebound to other arguments"
                    )
                if row["status"] != "complete":
                    raise AgentFailure("RECOVERY_UNCERTAIN", "External tool result is uncertain")
                cached = (
                    json.loads(row["payload"]["ordered_json"])
                    if "ordered_json" in row["payload"]
                    else row["payload"]
                )
            else:
                cached = None
                execute(
                    conn,
                    """INSERT INTO execution.calls
                    (run_id,call_key,fingerprint,kind,account,status,tool_name)
                    VALUES (:run,:key,:fingerprint,'tool',:account,'issued',:name)""",
                    run=self.backend.run_id,
                    key=key,
                    fingerprint=fingerprint,
                    account=account,
                    name=name,
                )
        if cached is not None:
            self._validate_payload(cached)
            return key, cached
        self.backend.hit("tool_issued")
        return key, None

    def _validate_payload(self, payload):
        for raw in payload.get("artifact_refs", []) + payload.get("context_refs", []):
            self.store.get(EvidenceRef.model_validate(raw))

    def finish_tool(self, key, payload, elapsed_ms, *, uncertain=False):
        self.backend.assert_lease()
        if not uncertain:
            self._validate_payload(payload)
        # JSONB reorders object keys. Preserve the exact original feedback rendering
        # so graph replay cannot create a new model request merely from key order.
        persisted = {"ordered_json": json.dumps(payload, ensure_ascii=False)}
        with self.backend.transaction() as conn:
            execute(
                conn,
                """UPDATE execution.calls SET status=:status,
                payload=CAST(:payload AS jsonb),payload_hash=:hash,
                elapsed_ms=:ms WHERE run_id=:run AND call_key=:key AND status='issued'""",
                run=self.backend.run_id,
                key=key,
                status="uncertain" if uncertain else "complete",
                payload=json_value(persisted),
                hash=digest(persisted),
                ms=elapsed_ms,
            )
        self.backend.hit("tool_committed")

    def hydrate_tools(self, registry):
        for id_, item in self.store.export().items():
            if (item.task_id, item.plan_version) != (
                registry.envelope.task.task_id,
                registry.envelope.plan_version,
            ):
                continue
            ref = EvidenceRef(artifact_id=id_, sha256=id_, kind=item.kind)
            if item.kind in {"schema", "context"}:
                registry.context_refs.append(ref)
        with self.backend.transaction() as conn:
            rows = execute(
                conn,
                "SELECT tool_name FROM execution.calls "
                "WHERE run_id=:run AND kind='tool' AND account=:account",
                run=self.backend.run_id,
                account=f"{registry.envelope.plan_version}:{registry.envelope.task.task_id}",
            ).all()
        # Attempts are durable call IDs, including known compiler failures.
        registry.sql_attempts = sum(name == "query_database" for (name,) in rows)
        registry.search_attempts = sum(name == "search_documents" for (name,) in rows)

    def adopt_payload(self, registry, payload):
        for raw in payload.get("artifact_refs", []) + payload.get("context_refs", []):
            ref = EvidenceRef.model_validate(raw)
            item = self.store.get(ref)
            if (item.task_id, item.plan_version) != (
                registry.envelope.task.task_id,
                registry.envelope.plan_version,
            ):
                raise AgentFailure("RECOVERY_FORBIDDEN", "Tool result belongs to another worker")
            target = registry.context_refs if item.kind in {"schema", "context"} else registry.refs
            if ref not in target:
                target.append(ref)

    def align_tools(self, registry, messages):
        # Only observations present at THIS child checkpoint are active evidence.
        # A later committed call may exist ahead of the graph checkpoint after a crash.
        registry.refs = []
        for message in messages:
            if message.type == "tool":
                self.adopt_payload(registry, json.loads(message.content))

    def recover(self):
        uncertain = False
        with self.backend.transaction() as conn:
            rows = (
                execute(
                    conn,
                    "SELECT * FROM execution.calls WHERE run_id=:run FOR UPDATE",
                    run=self.backend.run_id,
                )
                .mappings()
                .all()
            )
            issued = {r["ticket"] for r in rows if r["ticket"]}

            def reconcile():
                nonlocal uncertain
                for row in rows:
                    self._row(conn, row["call_key"])
                    if row["kind"] == "model" and row["status"] == "complete":
                        receipt = self.ledger.receipts.get(row["ticket"])
                        actual = (row["usage"] or {}).get("total_tokens")
                        actual = actual if type(actual) is int and actual >= 0 else None
                        if not receipt or receipt[:2] != ["settled", actual]:
                            raise AgentFailure(
                                "BUDGET_INVALID", "Call settlement differs from ledger"
                            )
                    if row["status"] in {"issued", "uncertain"}:
                        uncertain = True
                        if row["ticket"] in self.ledger.pending:
                            self.ledger.record_settlement(row["ticket"], None)
                for ticket in list(self.ledger.pending):
                    if ticket not in issued:
                        self.ledger.record_settlement(ticket, None, released=True)
                models = [row for row in rows if row["kind"] == "model"]
                for account, item in self.ledger.accounts.items():
                    relevant = []
                    for row in models:
                        at = row["account"]
                        while at is not None:
                            if at not in self.ledger.accounts:
                                raise AgentFailure("BUDGET_INVALID", "Missing call budget account")
                            if at == account:
                                relevant.append(row)
                                break
                            at = self.ledger.accounts[at].parent
                    known = sum(
                        (row["usage"] or {}).get("total_tokens", 0)
                        for row in relevant
                        if type((row["usage"] or {}).get("total_tokens")) is int
                        and (row["usage"] or {})["total_tokens"] >= 0
                    )
                    if item.usage.calls != len(relevant) or item.usage.reported_tokens != known:
                        raise AgentFailure(
                            "BUDGET_INVALID", "Call count or known usage differs from ledger"
                        )
                    receipts = [self.ledger.receipts.get(row["ticket"]) for row in relevant]
                    if all(r and len(r) == 3 for r in receipts):
                        charged = sum(r[1] if r[1] is not None else r[2] for r in receipts)
                        if item.usage.total_tokens != charged:
                            raise AgentFailure(
                                "BUDGET_INVALID", "Conservative charge differs from calls"
                            )
                    if (
                        item.usage.calls > item.limits.calls
                        or item.usage.total_tokens > item.limits.tokens
                    ):
                        raise AgentFailure(
                            "BUDGET_EXCEEDED", "Persisted provider usage exceeded policy"
                        )

            self.ledger.mutate(reconcile, conn)
            execute(
                conn,
                "UPDATE execution.calls SET status='uncertain' "
                "WHERE run_id=:run AND status='issued'",
                run=self.backend.run_id,
            )
        if uncertain:
            raise AgentFailure(
                "RECOVERY_UNCERTAIN",
                "Unconfirmed external execution retained; automatic retry denied",
            )
