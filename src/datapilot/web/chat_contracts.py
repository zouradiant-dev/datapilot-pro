"""Bounded interaction DTOs. Candidates never grant execution authority."""

import json
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_serializer, model_validator

from datapilot.datasets.contracts import DatasetBinding, DatasetId, Version
from datapilot.ingestion.contracts import DTO, Digest
from datapilot.reporting.contracts import CitationSource
from datapilot.semantics.contracts import MetricId, MetricVersion, MetricWindow
from datapilot.web.contracts import CreateTask, DatabaseText, FactRequirement


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
    document_purpose: Literal["locate", "summary", "facts", "conclusion"] | None = None
    required_facts: list[FactRequirement] = Field(default_factory=list, max_length=8)
    required_source_ids: list[Digest] = Field(default_factory=list, max_length=8)

    @model_serializer(mode="wrap")
    def legacy_projection(self, handler):
        value = handler(self)
        if self.document_purpose is None:
            value.pop("document_purpose", None)
        if not self.required_facts:
            value.pop("required_facts", None)
        if not self.required_source_ids:
            value.pop("required_source_ids", None)
        return value

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
        if (self.required_source_ids or self.document_purpose) and not self.corpus_ids:
            raise ValueError("Select authorized corpora before document requirements")
        if len(set(self.required_source_ids)) != len(self.required_source_ids):
            raise ValueError("Duplicate required source")
        if self.required_facts and self.document_purpose not in {"facts", "conclusion"}:
            raise ValueError("Choose a fact/conclusion purpose before specifying facts")
        if len({f.fact_id for f in self.required_facts}) != len(self.required_facts):
            raise ValueError("Duplicate fact requirement")
        return self


class MessageCreate(DTO):
    schema_version: Literal["chat-v1"] = "chat-v1"
    text: DatabaseText = Field(default="", max_length=2000)
    upload_id: DatasetId | None = None
    selection: ChatSelection = Field(default_factory=ChatSelection)
    supersedes: DatasetId | None = None

    @model_serializer(mode="wrap")
    def legacy_projection(self, handler):
        value = handler(self)
        if self.supersedes is None:
            value.pop("supersedes", None)
        return value

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
    goal_contract: "GoalContractView | None" = None
    goal_event: Literal["confirmed", "rejected"] | None = None


class MessagesView(DTO):
    schema_version: Literal["chat-v1"] = "chat-v1"
    messages: list[MessageView] = Field(max_length=20)
    next_before: int | None = Field(default=None, ge=1, le=200)


class ChatLaunch(DTO):
    confirmed: bool
    expected_version: int | None = Field(default=None, ge=1, le=200)
    expected_contract_sha256: Digest | None = None
    reviewed_contract: bool = False
    covers_original_goal: bool = False
    prerequisites_resolved: bool = False


class GoalReject(DTO):
    expected_version: int = Field(ge=1, le=200)
    expected_contract_sha256: Digest


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


class GoalSource(CitationSource):
    name: str = Field(min_length=1, max_length=128)
    required: bool = True


class GoalDataset(DatasetBinding):
    name: str = Field(min_length=1, max_length=128)
    source_sha256: Digest


class GoalContractView(DTO):
    schema_version: Literal["web-goal-contract-v1"] = "web-goal-contract-v1"
    contract_id: DatasetId
    version: int = Field(ge=1, le=200)
    contract_sha256: Digest
    original_question: str = Field(min_length=1, max_length=2000)
    status: Literal["pending_confirmation", "confirmed", "rejected", "superseded", "expired"]
    expires_at: datetime
    review: ReviewView
    datasets: list[GoalDataset] = Field(max_length=8)
    sources: list[GoalSource] = Field(min_length=1, max_length=8)
    unresolved: list[str] = Field(max_length=8)
    limitations: list[str] = Field(max_length=8)
    can_confirm: bool


MessageView.model_rebuild()
