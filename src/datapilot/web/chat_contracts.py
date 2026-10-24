"""Bounded interaction DTOs. Candidates never grant execution authority."""

import json
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from datapilot.datasets.contracts import DatasetId, Version
from datapilot.ingestion.contracts import DTO, Digest
from datapilot.semantics.contracts import MetricId, MetricVersion, MetricWindow
from datapilot.web.contracts import CreateTask, DatabaseText


class ConversationCreate(DTO):
    schema_version: Literal["chat-v1"] = "chat-v1"


class ConversationView(DTO):
    schema_version: Literal["chat-v1"] = "chat-v1"
    conversation_id: DatasetId
    created_at: datetime
    expires_at: datetime


class ConversationsView(DTO):
    schema_version: Literal["chat-v1"] = "chat-v1"
    conversations: list[ConversationView] = Field(max_length=30)


class ChatSelection(DTO):
    dataset_id: DatasetId | None = None
    dataset_version: Version | None = None
    metric_id: MetricId | None = None
    metric_version: Version | None = None
    window: MetricWindow | None = None
    corpus_ids: list[DatasetId] = Field(default_factory=list, max_length=8)

    @field_validator("window", mode="before")
    @classmethod
    def dates(cls, value):
        return (
            MetricWindow.model_validate_json(json.dumps(value))
            if isinstance(value, dict)
            else value
        )

    @model_validator(mode="after")
    def paired(self):
        if (self.dataset_id is None) != (self.dataset_version is None):
            raise ValueError("Select an exact Dataset version")
        if self.metric_version is not None and self.metric_id is None:
            raise ValueError("Select a metric before its version")
        if len(set(self.corpus_ids)) != len(self.corpus_ids):
            raise ValueError("Duplicate document selection")
        return self


class MessageCreate(DTO):
    schema_version: Literal["chat-v1"] = "chat-v1"
    text: DatabaseText = Field(default="", max_length=2000)
    upload_id: DatasetId | None = None
    selection: ChatSelection = Field(default_factory=ChatSelection)

    @model_validator(mode="after")
    def content(self):
        if bool(self.text.strip()) == bool(self.upload_id):
            raise ValueError("Use one question or one upload reference")
        return self


class ChatDraft(DTO):
    schema_version: Literal["chat-v1"] = "chat-v1"
    request: CreateTask | None = None
    authorization_sha256: Digest | None = None
    missing: list[str] = Field(default_factory=list, max_length=12)
    notes: list[str] = Field(default_factory=list, max_length=8)


class MessageView(DTO):
    schema_version: Literal["chat-v1"] = "chat-v1"
    message_id: DatasetId
    sequence: int = Field(ge=1, le=200)
    created_at: datetime
    text: str = Field(default="", max_length=2000)
    upload_id: DatasetId | None = None
    draft: ChatDraft | None = None
    run_id: DatasetId | None = None
    unavailable: bool = False


class MessagesView(DTO):
    schema_version: Literal["chat-v1"] = "chat-v1"
    messages: list[MessageView] = Field(max_length=20)
    next_before: int | None = Field(default=None, ge=1, le=200)


class ChatLaunch(DTO):
    confirmed: bool


class ReviewDocument(DTO):
    corpus_id: DatasetId
    index_version: Digest
    dataset_id: DatasetId | None = None
    dataset_version: Version | None = None
    source_sha256: Digest | None = None


class ReviewView(DTO):
    schema_version: Literal["api-v1"] = "api-v1"
    request: CreateTask
    definitions: list[MetricVersion] = Field(max_length=6)
    dataset_names: list[str] = Field(max_length=6)
    document_scope: list[ReviewDocument] = Field(max_length=8)
    model_mode: Literal["fake", "live"]
    max_model_calls: int = Field(ge=1, le=20)
    max_tokens: int = Field(ge=100, le=100000)
    cost: str = "未知；Live 按供应商实际用量计费，Fake 不调用付费模型"
