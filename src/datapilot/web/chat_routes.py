"""Small versioned interaction routes under the existing Host/CSRF middleware."""

from uuid import UUID

from fastapi import Header, Query

from datapilot.persistence.session import run_async
from datapilot.web.chat import ChatService
from datapilot.web.chat_contracts import (
    ChatLaunch,
    ConversationCreate,
    ConversationsView,
    ConversationView,
    MessageCreate,
    MessagesView,
    MessageView,
    ReviewView,
)
from datapilot.web.contracts import Acknowledgement, CreateTask
from datapilot.web.service import public_schema


def register_chat_routes(app, product):
    chat = ChatService(product)
    app.state.chat = chat

    @app.post("/api/v1/conversations", response_model=ConversationView)
    def create_conversation(request: ConversationCreate, idempotency_key: str = Header(...)):
        row = chat.create(idempotency_key, request)
        return {k: row[k] for k in ("conversation_id", "created_at", "expires_at")}

    @app.get("/api/v1/conversations", response_model=ConversationsView)
    def conversations():
        return {"conversations": chat.conversations()}

    @app.get("/api/v1/conversations/{id_}/messages", response_model=MessagesView)
    def messages(id_: UUID, before: int = Query(201, ge=1, le=201)):
        return run_async(chat.messages(str(id_), before))

    @app.post("/api/v1/conversations/{id_}/messages", response_model=MessageView)
    def append_message(id_: UUID, request: MessageCreate, idempotency_key: str = Header(...)):
        return run_async(chat.append(str(id_), idempotency_key, request))

    @app.post(
        "/api/v1/conversations/{id_}/messages/{message_id}/launch", response_model=Acknowledgement
    )
    def launch(id_: UUID, message_id: UUID, request: ChatLaunch):
        # Message identity itself is the persistent creation idempotency key.
        return run_async(chat.launch(str(id_), str(message_id), request.confirmed))

    @app.get("/api/v1/tasks/{id_}/review", response_model=ReviewView)
    def review(id_: UUID):
        row = run_async(product.authorize_run(str(id_)))
        p = row["payload"]
        rs = p["report_scope"]
        docs = rs.get("document_goal")
        request = CreateTask.model_validate_json(
            __import__("json").dumps(
                {
                    "question": p["question"],
                    "metrics": rs["metrics"],
                    "require_review": p["require_review"],
                    "causal_requested": rs["causal_requested"],
                    "documents": {
                        "question": docs["question"],
                        "metric_goals": docs["metric_goals"],
                        "corpus_ids": [c["corpus_id"] for c in p["rag_scope"]["corpora"]],
                    }
                    if docs
                    else None,
                }
            )
        )
        definitions, dataset_names = [], []
        for m in request.metrics:
            ds = product.store.dataset(m.dataset_id, m.dataset_version)
            dataset_names.append(public_schema(ds)["schema"]["name"])
            definitions.append(
                next(
                    d
                    for d in ds["metrics"]
                    if d["metric_id"] == m.metric_id
                    and d["metric_version"] == m.metric_version
                    and d["semantic_version"] == m.semantic_version
                )
            )
        return ReviewView(
            request=request,
            definitions=definitions,
            dataset_names=dataset_names,
            document_scope=[
                {
                    "corpus_id": c["corpus_id"],
                    "index_version": c["index_version"],
                    "dataset_id": grant["dataset_id"],
                    "dataset_version": grant["dataset_version"],
                    "source_sha256": p["sources"][grant["dataset_id"]],
                }
                for c in (p.get("rag_scope") or {}).get("corpora", [])
                for grant in product.store.corpora(corpus_id=c["corpus_id"])
                if grant["index_version"] == c["index_version"]
            ],
            model_mode=product.settings.llm_mode,
            max_model_calls=product.settings.max_model_calls,
            max_tokens=product.settings.max_total_tokens,
        )
