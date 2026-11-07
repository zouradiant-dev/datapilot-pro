"""Private interaction index on the existing Web store, not an execution engine."""

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.persistence.backend import execute, json_value
from datapilot.web.chat_contracts import ChatDraft, GoalContractView, MessageView
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

    def _message(self, conn, cid, mid):
        self._conversation(conn, cid)
        row = (
            execute(
                conn,
                "SELECT * FROM execution.web_messages WHERE conversation_id=:c AND message_id=:m",
                c=cid,
                m=mid,
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            deny("CHAT_UNAVAILABLE")
        self._payload(row)
        return row

    def _goal_state(self, conn, row):
        p = self._payload(row)
        snapshot = p.get("goal_contract")
        if not snapshot:
            deny("GOAL_CONFIRMATION_REQUIRED", "请重新创建并审阅当前有限合同")
        if datetime.fromisoformat(snapshot["expires_at"]) <= datetime.now(UTC):
            return "expired", None
        newer = (
            execute(
                conn,
                "SELECT * FROM execution.web_messages WHERE conversation_id=:c "
                "AND payload->>'supersedes'=:m ORDER BY sequence DESC LIMIT 1",
                c=row["conversation_id"],
                m=row["message_id"],
            )
            .mappings()
            .one_or_none()
        )
        if newer:
            self._payload(newer)
            return "superseded", None
        event = (
            execute(
                conn,
                "SELECT * FROM execution.web_messages WHERE conversation_id=:c "
                "AND payload->'goal_event'->>'message_id'=:m ORDER BY sequence DESC LIMIT 1",
                c=row["conversation_id"],
                m=row["message_id"],
            )
            .mappings()
            .one_or_none()
        )
        if not event:
            return "pending_confirmation", None
        e = self._payload(event)["goal_event"]
        if (
            e["event_id"],
            e["conversation_id"],
            e["message_id"],
            e["version"],
            e["contract_sha256"],
        ) != (
            event["message_id"],
            row["conversation_id"],
            row["message_id"],
            row["sequence"],
            digest(snapshot),
        ):
            deny("CHAT_CORRUPT", "Confirmation identity differs")
        return e["action"], e

    def _goal_view(self, row, state):
        s = self._payload(row)["goal_contract"]
        return GoalContractView.model_validate_json(
            json_value(
                {
                    "contract_id": row["message_id"],
                    "version": row["sequence"],
                    "contract_sha256": digest(s),
                    "original_question": self._payload(row)["text"],
                    "status": state,
                    **{
                        k: s[k]
                        for k in (
                            "expires_at",
                            "review",
                            "datasets",
                            "sources",
                            "unresolved",
                            "limitations",
                        )
                    },
                    "can_confirm": s["can_confirm"] and state == "pending_confirmation",
                }
            )
        )

    async def goal(self, cid, mid):
        with self.store.transaction() as conn:
            row = self._message(conn, cid, mid)
            state, _ = self._goal_state(conn, row)
        from datapilot.web.goal_confirmation import base_payload

        request = CreateTask.model_validate_json(json_value(self._payload(row)["draft"]["request"]))
        fresh = await self.product.task_payload(request)
        if fresh != base_payload(self._payload(row)["goal_contract"]):
            deny("RECOVERY_VERSION", "合同的数据、定义或宿主配置已变化，请重新确认")
        return self._goal_view(row, state)

    def _actor(self, conn, actor):
        if (
            not actor
            or not execute(
                conn,
                "SELECT 1 FROM execution.web_sessions "
                "WHERE session_hash=:s AND owner=:o AND expires_at>now()",
                s=actor,
                o=self.store.policy.owner,
            ).first()
        ):
            deny("WEB_FORBIDDEN", "Confirmation requires a current authenticated session")

    def _event(self, conn, row, action, actor):
        self._actor(conn, actor)
        count = execute(
            conn,
            "SELECT count(*) FROM execution.web_messages WHERE conversation_id=:c",
            c=row["conversation_id"],
        ).scalar_one()
        if count >= 200:
            deny("CHAT_QUOTA", "Confirmation needs space in the bounded history")
        s = self._payload(row)["goal_contract"]
        e = {
            "action": action,
            "event_id": str(uuid4()),
            "conversation_id": row["conversation_id"],
            "message_id": row["message_id"],
            "version": row["sequence"],
            "contract_sha256": digest(s),
            "actor_session_hash": actor,
            "confirmed_at": datetime.now(UTC).isoformat(),
            "expires_at": s["expires_at"],
        }
        if action == "confirmed":
            e["reviewed_contract"] = True
            e["covers_original_goal"] = True
            e["prerequisites_resolved"] = True
        payload = {
            "text": "有限合同已确认" if action == "confirmed" else "有限合同已拒绝或撤回",
            "upload_id": None,
            "draft": None,
            "goal_event": e,
        }
        execute(
            conn,
            "INSERT INTO execution.web_messages(message_id,conversation_id,sequence,request_key,"
            "request_hash,payload,payload_hash) VALUES(:m,:c,:s,:k,:h,CAST(:p AS jsonb),:ph)",
            m=e["event_id"],
            c=row["conversation_id"],
            s=count + 1,
            k="goal-" + action + "-" + row["message_id"],
            h=digest({"action": action, "target": row["message_id"]}),
            p=json_value(payload),
            ph=digest(payload),
        )
        return e

    async def reject(self, cid, mid, decision, actor):
        with self.store.transaction() as conn:
            self._lock(conn)
            self._actor(conn, actor)
            row = self._message(conn, cid, mid)
            self._check_goal_version(row, decision)
            state, _ = self._goal_state(conn, row)
            if state not in {"rejected", "superseded", "expired"}:
                self._event(conn, row, "rejected", actor)
                if row["run_id"]:
                    self.store.command(
                        "goal-cancel-" + mid, "cancel", {}, run_id=row["run_id"], conn=conn
                    )
        if row["run_id"]:
            await self.product.cancel_runtime(row["run_id"])
        return await self._view(row)

    def _check_goal_version(self, row, decision):
        snapshot = self._payload(row).get("goal_contract")
        if not snapshot or (decision.expected_version, decision.expected_contract_sha256) != (
            row["sequence"],
            digest(snapshot),
        ):
            deny("GOAL_STALE", "请重新读取当前完整合同；旧确认不能复用")

    def confirmed_run_goal(self, payload, run_id):
        from datapilot.web.goal_confirmation import bind_payload

        ref = payload["goal_confirmation"]
        with self.store.transaction() as conn:
            row = self._message(conn, ref["conversation_id"], ref["message_id"])
            state, event = self._goal_state(conn, row)
            if row["run_id"] != run_id:
                deny("RECOVERY_IDENTITY", "确认仅绑定原业务Run")
        if state != "confirmed" or not event or event["event_id"] != ref["event_id"]:
            deny("GOAL_REVOKED", "确认已撤回、替换或过期")
        snapshot = self._payload(row)["goal_contract"]
        if bind_payload(snapshot, event) != payload:
            deny("RECOVERY_IDENTITY", "确认记录与运行载荷不一致")
        return snapshot

    async def authorized_goal_payload(self, payload, run_id):
        from datapilot.web.goal_confirmation import base_payload

        snapshot = self.confirmed_run_goal(payload, run_id)
        request = CreateTask.model_validate_json(json_value(snapshot["review"]["request"]))
        if await self.product.task_payload(request) != base_payload(snapshot):
            deny("RECOVERY_VERSION", "确认的数据、权限或定义已变化")
        return payload

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
        if p.get("goal_event"):
            return MessageView(
                message_id=row["message_id"],
                sequence=row["sequence"],
                created_at=row["created_at"],
                text=p["text"],
                goal_event=p["goal_event"]["action"],
            )
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
            if p.get("goal_contract"):
                view.goal_contract = await self.goal(row["conversation_id"], row["message_id"])
                if view.goal_contract.status in {"rejected", "superseded", "expired"}:
                    return view
            if view.upload_id:
                self.store.upload(view.upload_id)
            if view.run_id:
                await self.product.authorize_run(view.run_id)
            elif view.draft and view.draft.request and not p.get("goal_contract"):
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
            conversation = self._conversation(conn, id_)
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
            # An edit can commit before its cancellation acknowledgement is lost.
            # Reuse the old message AND the original cancellation, never a new Run.
            if request.supersedes:
                with self.store.transaction() as conn:
                    parent = self._message(conn, id_, request.supersedes)
                if parent["run_id"]:
                    await self.product.cancel_runtime(parent["run_id"])
            return await self._view(old)
        if request.supersedes:
            with self.store.transaction() as conn:
                parent = self._message(conn, id_, request.supersedes)
            if parent["run_id"]:
                self.product.ensure_no_unknown(parent["run_id"])
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
                    if selection.document_facts_independent:
                        descriptions = "；".join(
                            f.description.strip() for f in selection.required_facts
                        )
                        doc_question = "请依据授权文档核验以下事实：" + descriptions
                        if len(doc_question) > 512:
                            raise AgentFailure(
                                "WEB_SCOPE",
                                "独立文档事实过多，请拆分为更小的合同",
                            )
                        body["documents"]["question"] = doc_question
                        body["documents"]["independent_facts"] = True
                    draft.request = CreateTask.model_validate_json(json_value(body))
            if draft.request:
                try:
                    fresh = await self.product.task_payload(draft.request)
                except AgentFailure as exc:
                    if exc.error.code != "DOCUMENT_SCOPE_REQUIRED":
                        raise
                    draft = ChatDraft(missing=[exc.error.message], notes=draft.notes)
                else:
                    if (
                        selection.dataset_id
                        and not draft.request.metrics
                        and any(
                            (b["dataset_id"], b["version"])
                            != (selection.dataset_id, selection.dataset_version)
                            for b in fresh["report_scope"]["datasets"]["bindings"]
                        )
                    ):
                        deny(
                            "WEB_SCOPE", "Selected document source differs from the chosen snapshot"
                        )
                    draft = draft.model_copy(update={"authorization_sha256": digest(fresh)})
        payload = {
            "schema_version": "chat-v1",
            "text": request.text,
            "upload_id": request.upload_id,
            "draft": draft.model_dump(mode="json") if draft else None,
        }
        if request.supersedes:
            payload["supersedes"] = request.supersedes
        if draft and draft.request and draft.request.documents:
            from datapilot.web.goal_confirmation import proposal

            snapshot = await proposal(self.product, draft.request, fresh, request.selection)
            snapshot["expires_at"] = min(
                conversation["expires_at"],
                datetime.now(UTC) + timedelta(seconds=self.store.policy.ttl_seconds),
            ).isoformat()
            payload["goal_contract"] = snapshot
        if len(json_value(payload).encode()) > 24576:
            deny("GOAL_SIZE", "合同过大，请缩小数据与文档范围")
        with self.store.transaction() as conn:
            self._lock(conn)
            self._conversation(conn, id_)
            row = self._existing(conn, id_, key, hashed)
            if not row:
                if request.supersedes:
                    parent = self._message(conn, id_, request.supersedes)
                    if parent["run_id"]:
                        self.store.command(
                            "goal-edit-" + request.supersedes,
                            "cancel",
                            {},
                            run_id=parent["run_id"],
                            conn=conn,
                        )
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
        if request.supersedes and parent["run_id"]:
            await self.product.cancel_runtime(parent["run_id"])
        return await self._view(row)

    async def launch(self, conversation_id, message_id, confirmed, *, decision=None, actor=None):
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
        if p.get("supersedes"):
            with self.store.transaction() as conn:
                parent = self._message(conn, conversation_id, p["supersedes"])
            if parent["run_id"]:
                self.product.ensure_no_unknown(parent["run_id"])
        if p.get("goal_contract"):
            return await self._launch_goal(row, decision, actor)
        if row["run_id"]:
            await self.product.authorize_run(row["run_id"])
            return {"schema_version": "api-v1", "run_id": row["run_id"], "accepted": True}
        if not p.get("draft") or not p["draft"].get("request"):
            deny("CHAT_CLARIFICATION_REQUIRED", "Resolve missing definitions first")
        request = CreateTask.model_validate_json(json_value(p["draft"]["request"]))
        if request.documents:
            deny("GOAL_CONFIRMATION_REQUIRED", "旧候选须重新审阅当前有限合同")
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
            existing, case, _ = self.product.admission.reserve(conn, payload, message_id)
            if existing:
                return {"schema_version": "api-v1", "run_id": existing, "accepted": True}
            ack = self.store.command(
                "chat-run-" + message_id, "create", payload, payload=payload, conn=conn
            )
            if case is not None:
                self.product.admission.attach(conn, case["case_id"], ack["run_id"])
            execute(
                conn,
                "UPDATE execution.web_messages SET run_id=:r "
                "WHERE message_id=:m AND run_id IS NULL",
                r=ack["run_id"],
                m=message_id,
            )
            return ack

    async def _launch_goal(self, row, decision, actor):
        from datapilot.web.goal_confirmation import base_payload, bind_payload

        if decision is None or not (
            decision.reviewed_contract
            and decision.covers_original_goal
            and decision.prerequisites_resolved
        ):
            deny("GOAL_CONFIRMATION_REQUIRED", "请明确审阅完整目标、有限范围及所有前置条件")
        self._check_goal_version(row, decision)
        p = self._payload(row)
        s = p["goal_contract"]
        if not s["can_confirm"]:
            deny("GOAL_UNSUPPORTED", "当前前提或能力不支持此合同，请修改问题")
        request = CreateTask.model_validate_json(json_value(s["review"]["request"]))
        if request.question != p["text"] or not request.require_review:
            deny("CHAT_CORRUPT")
        fresh = await self.product.task_payload(request)
        if fresh != base_payload(s):
            deny("RECOVERY_VERSION", "合同范围或宿主策略发生变化")
        with self.store.transaction() as conn:
            self._lock(conn)
            current = self._message(conn, row["conversation_id"], row["message_id"])
            self._actor(conn, actor)
            if self._payload(current) != p:
                deny("CHAT_CORRUPT")
            state, event = self._goal_state(conn, current)
            if state == "confirmed" and current["run_id"]:
                saved = self.store.run(current["run_id"], conn)
                if saved["payload_hash"] != digest(bind_payload(s, event)):
                    deny("RECOVERY_IDENTITY")
                return {"schema_version": "api-v1", "run_id": current["run_id"], "accepted": True}
            if state != "pending_confirmation" or current["run_id"]:
                deny("GOAL_STALE", "合同已替换、拒绝或过期")
            event = self._event(conn, current, "confirmed", actor)
            bound = bind_payload(s, event)
            existing, case, _ = self.product.admission.reserve(
                conn, bound, current["message_id"], digest(s)
            )
            if existing:
                return {"schema_version": "api-v1", "run_id": existing, "accepted": True}
            ack = self.store.command(
                "chat-run-" + current["message_id"], "create", bound, payload=bound, conn=conn
            )
            if case is not None:
                self.product.admission.attach(conn, case["case_id"], ack["run_id"])
            execute(
                conn,
                "UPDATE execution.web_messages SET run_id=:r "
                "WHERE message_id=:m AND run_id IS NULL",
                r=ack["run_id"],
                m=current["message_id"],
            )
            return ack
