"""Private interaction index on the existing Web store, not an execution engine."""

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.persistence.backend import execute, json_value
from datapilot.web.chat_contracts import ChatDraft, MessageView
from datapilot.web.contracts import CreateTask
from datapilot.web.intent import resolve
from datapilot.web.store import deny


class ChatService:
    def __init__(self, product):
        self.product = product
        self.store = product.store

    def _lock(self, conn):
        # Same owner lock/order as WebStore.command; quotas and Run linking are atomic.
        execute(
            conn,
            "SELECT pg_advisory_xact_lock(hashtextextended(:o,6153))",
            o=self.store.policy.owner,
        )

    def _key(self, key):
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
            deny("WEB_IDEMPOTENCY", "Use a stable bounded request key")

    def _conversation(self, conn, id_):
        row = (
            execute(
                conn,
                "SELECT * FROM execution.web_conversations WHERE conversation_id=:id "
                "AND owner=:o AND expires_at>now()",
                id=id_,
                o=self.store.policy.owner,
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            deny("CHAT_UNAVAILABLE", "Conversation is unavailable or expired")
        return row

    def _payload(self, row):
        if digest(row["payload"]) != row["payload_hash"]:
            deny("CHAT_CORRUPT", "Message hash differs")
        return row["payload"]

    def create(self, key, body):
        self._key(key)
        hashed = digest(body.model_dump(mode="json"))
        with self.store.transaction() as conn:
            self._lock(conn)
            old = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_conversations WHERE owner=:o AND create_key=:k",
                    o=self.store.policy.owner,
                    k=key,
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_hash"] != hashed:
                    deny("WEB_IDEMPOTENCY_CONFLICT")
                return dict(self._conversation(conn, old["conversation_id"]))
            count = execute(
                conn,
                "SELECT count(*) FROM execution.web_conversations "
                "WHERE owner=:o AND expires_at>now()",
                o=self.store.policy.owner,
            ).scalar_one()
            if count >= 30:
                deny("CHAT_QUOTA", "At most 30 active conversations")
            return dict(
                execute(
                    conn,
                    "INSERT INTO execution.web_conversations "
                    "(conversation_id,owner,create_key,request_hash,expires_at) "
                    "VALUES(:id,:o,:k,:h,:e) RETURNING *",
                    id=str(uuid4()),
                    o=self.store.policy.owner,
                    k=key,
                    h=hashed,
                    e=datetime.now(UTC) + timedelta(seconds=self.store.policy.ttl_seconds),
                )
                .mappings()
                .one()
            )

    def conversations(self):
        with self.store.transaction() as conn:
            return (
                execute(
                    conn,
                    "SELECT conversation_id,created_at,expires_at FROM execution.web_conversations "
                    "WHERE owner=:o AND expires_at>now() "
                    "ORDER BY created_at DESC,conversation_id LIMIT 30",
                    o=self.store.policy.owner,
                )
                .mappings()
                .all()
            )

    async def _view(self, row):
        p = self._payload(row)
        view = MessageView(
            message_id=row["message_id"],
            sequence=row["sequence"],
            created_at=row["created_at"],
            text=p["text"],
            upload_id=p.get("upload_id"),
            draft=ChatDraft.model_validate(p["draft"]) if p.get("draft") else None,
            run_id=row["run_id"],
        )
        try:
            if view.upload_id:
                self.store.upload(view.upload_id)
            if view.run_id:
                await self.product.authorize_run(view.run_id)
            elif view.draft and view.draft.request:
                # Current trusted policy, grants and real MCP versions, never history authority.
                fresh = await self.product.task_payload(view.draft.request)
                if digest(fresh) != view.draft.authorization_sha256:
                    deny("RECOVERY_VERSION", "Candidate policy or source changed")
        except AgentFailure:
            return MessageView(
                message_id=view.message_id,
                sequence=view.sequence,
                created_at=view.created_at,
                unavailable=True,
            )
        return view

    async def messages(self, id_, before=201):
        with self.store.transaction() as conn:
            self._conversation(conn, id_)
            rows = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_messages "
                    "WHERE conversation_id=:id AND sequence<:b "
                    "ORDER BY sequence DESC LIMIT 21",
                    id=id_,
                    b=before,
                )
                .mappings()
                .all()
            )
        selected = rows[:20]
        return {
            "messages": [await self._view(r) for r in reversed(selected)],
            "next_before": selected[-1]["sequence"] if len(rows) > 20 else None,
        }

    def _existing(self, conn, id_, key, hashed):
        row = (
            execute(
                conn,
                "SELECT * FROM execution.web_messages WHERE conversation_id=:id AND request_key=:k",
                id=id_,
                k=key,
            )
            .mappings()
            .one_or_none()
        )
        if row and row["request_hash"] != hashed:
            deny("WEB_IDEMPOTENCY_CONFLICT")
        return row

    async def append(self, id_, key, request):
        self._key(key)
        hashed = digest(request.model_dump(mode="json"))
        with self.store.transaction() as conn:
            self._conversation(conn, id_)
            old = self._existing(conn, id_, key, hashed)
            previous = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_messages "
                    "WHERE conversation_id=:id AND run_id IS NOT NULL "
                    "ORDER BY sequence DESC LIMIT 1",
                    id=id_,
                )
                .mappings()
                .one_or_none()
            )
        if old:
            return await self._view(old)
        # Never hold an owner/advisory/row lock across MCP or network I/O.
        draft, prior_request = None, None
        if request.upload_id:
            self.store.upload(request.upload_id)
        else:
            if previous:
                self._payload(previous)
                try:
                    p = await self.product.authorize_run(previous["run_id"])
                    prior_request = {"metrics": p["payload"]["report_scope"]["metrics"]}
                except AgentFailure:
                    pass  # Revoked history cannot supply even candidate scope.
            selection = request.selection
            if selection.dataset_id:
                datasets = [
                    await self.product.dataset(selection.dataset_id, selection.dataset_version)
                ]
            elif (
                prior_request
                and prior_request["metrics"]
                and re.search(r"那|继续|同样|对比|比较|比呢", request.text)
            ):
                m = prior_request["metrics"][0]
                datasets = [await self.product.dataset(m["dataset_id"], m["dataset_version"])]
            else:
                datasets = self.store.datasets()
            draft = resolve(
                request.text,
                selection,
                datasets,
                today=datetime.now(ZoneInfo("Asia/Shanghai")).date(),
                previous=prior_request,
            )
            if draft.request and draft.request.documents:
                if selection.document_purpose is None:
                    draft = ChatDraft(
                        missing=["请确认文档用途：定位、总结、事实提取或结论。"], notes=draft.notes
                    )
                elif selection.document_purpose == "facts" and not selection.required_facts:
                    draft = ChatDraft(missing=["请列出需要核验的事实；描述本身不是证明。"])
                else:
                    body = draft.request.model_dump(mode="json")
                    body["documents"].update(
                        purpose=selection.document_purpose,
                        required_facts=[f.model_dump() for f in selection.required_facts],
                    )
                    draft.request = CreateTask.model_validate_json(json_value(body))
            if draft.request:
                fresh = await self.product.task_payload(draft.request)
                if (
                    selection.dataset_id
                    and not draft.request.metrics
                    and any(
                        (b["dataset_id"], b["version"])
                        != (selection.dataset_id, selection.dataset_version)
                        for b in fresh["report_scope"]["datasets"]["bindings"]
                    )
                ):
                    deny("WEB_SCOPE", "Selected document source differs from the chosen snapshot")
                draft = draft.model_copy(update={"authorization_sha256": digest(fresh)})
        payload = {
            "schema_version": "chat-v1",
            "text": request.text,
            "upload_id": request.upload_id,
            "draft": draft.model_dump(mode="json") if draft else None,
        }
        with self.store.transaction() as conn:
            self._lock(conn)
            self._conversation(conn, id_)
            row = self._existing(conn, id_, key, hashed)
            if not row:
                count = execute(
                    conn,
                    "SELECT count(*) FROM execution.web_messages WHERE conversation_id=:id",
                    id=id_,
                ).scalar_one()
                if count >= 200:
                    deny("CHAT_QUOTA", "At most 200 messages per conversation")
                row = (
                    execute(
                        conn,
                        "INSERT INTO execution.web_messages "
                        "(message_id,conversation_id,sequence,request_key,request_hash,"
                        "payload,payload_hash) "
                        "VALUES(:m,:c,:s,:k,:h,CAST(:p AS jsonb),:ph) RETURNING *",
                        m=str(uuid4()),
                        c=id_,
                        s=count + 1,
                        k=key,
                        h=hashed,
                        p=json_value(payload),
                        ph=digest(payload),
                    )
                    .mappings()
                    .one()
                )
        return await self._view(row)

    async def launch(self, conversation_id, message_id, confirmed):
        if not confirmed:
            deny("CHAT_CONFIRMATION_REQUIRED", "Review the candidate before submitting")
        with self.store.transaction() as conn:
            self._conversation(conn, conversation_id)
            row = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_messages "
                    "WHERE conversation_id=:c AND message_id=:m",
                    c=conversation_id,
                    m=message_id,
                )
                .mappings()
                .one_or_none()
            )
            if not row:
                deny()
            p = self._payload(row)
        if row["run_id"]:
            await self.product.authorize_run(row["run_id"])
            return {"schema_version": "api-v1", "run_id": row["run_id"], "accepted": True}
        if not p.get("draft") or not p["draft"].get("request"):
            deny("CHAT_CLARIFICATION_REQUIRED", "Resolve missing definitions first")
        request = CreateTask.model_validate_json(json_value(p["draft"]["request"]))
        if request.question != p["text"] or not request.require_review:
            deny("CHAT_CORRUPT")
        payload = await self.product.task_payload(request)
        if digest(payload) != p["draft"].get("authorization_sha256"):
            deny("RECOVERY_VERSION", "Reconfirm changed host policy or source")
        with self.store.transaction() as conn:
            self._lock(conn)
            self._conversation(conn, conversation_id)
            current = (
                execute(
                    conn,
                    "SELECT * FROM execution.web_messages "
                    "WHERE conversation_id=:c AND message_id=:m FOR UPDATE",
                    c=conversation_id,
                    m=message_id,
                )
                .mappings()
                .one()
            )
            if self._payload(current) != p:
                deny("CHAT_CORRUPT")
            if current["run_id"]:
                original = self.store.run(current["run_id"], conn)
                if original["payload_hash"] != digest(payload):
                    deny("RECOVERY_VERSION")
                return {"schema_version": "api-v1", "run_id": current["run_id"], "accepted": True}
            ack = self.store.command(
                "chat-run-" + message_id, "create", payload, payload=payload, conn=conn
            )
            execute(
                conn,
                "UPDATE execution.web_messages SET run_id=:r "
                "WHERE message_id=:m AND run_id IS NULL",
                r=ack["run_id"],
                m=message_id,
            )
            return ack
