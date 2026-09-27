from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Status = Literal["generating", "completed", "failed", "cancelled"]


class AttachmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    mime_type: Literal[
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
    ]
    data: str = Field(min_length=1, max_length=6_990_508, repr=False)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if any(ord(c) < 32 for c in value) or "/" in value or "\\" in value or not value.strip():
            raise ValueError("附件名称无效。")
        return value


class AttachmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    mime_type: str
    size: int
    width: int | None = None
    height: int | None = None


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=36, max_length=36)
    content: str = Field(default="", max_length=100_000)
    attachments: list[AttachmentInput] = Field(default_factory=list, max_length=4)

    @field_validator("request_id")
    @classmethod
    def valid_id(cls, value):
        return str(UUID(value))

    @field_validator("content")
    @classmethod
    def valid_content(cls, value):
        if "\x00" in value:
            raise ValueError("请输入有效消息。")
        value.encode("utf-8")
        return value

    @model_validator(mode="after")
    def valid_message(self):
        if not self.content.strip() and not self.attachments:
            raise ValueError("请输入消息或添加附件。")
        return self


class SelectAgent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    agent_id: str = Field(min_length=1, max_length=36)


class ChatView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at", check_fields=False)
    @classmethod
    def utc_timestamp(cls, value: datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    project_id: str | None = Field(default=None, max_length=36)
    folder: str | None = Field(default=None, max_length=1024)


class ConversationView(ChatView):
    project_id: str | None = None
    folder: str | None = None
    archive_error: str | None = None
    pinned: bool
    id: str
    title: str
    agent_id: str | None
    created_at: datetime
    updated_at: datetime


class MessageView(ChatView):
    id: str
    conversation_id: str
    sequence: int
    role: Literal["user", "assistant"]
    content: str
    status: Status
    created_at: datetime
    agent_id: str | None
    agent_name: str | None
    attachments: list[AttachmentView] = Field(default_factory=list)
    feedback_rating: Literal["helpful", "unhelpful"] | None = None


class MessageFeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rating: Literal["helpful", "unhelpful"] | None


class GenerationView(ChatView):
    id: str
    conversation_id: str
    status: Status | Literal["limit_reached"]
    error: str | None
    message: MessageView | None = None
    saved: bool = True


class ConversationDetail(ConversationView):
    messages: list[MessageView]
    generation: GenerationView | None
    runtime_events: list[dict] = Field(default_factory=list)


class ChatAgent(BaseModel):
    id: str
    name: str
    is_default: bool
    description: str = ""
    is_ready: bool = True
    unavailable_reason: str | None = None
    tool_count: int = 0
    skill_count: int = 0
    mcp_server_count: int = 0


class ConversationUpdate(BaseModel):
    project_id: str | None = Field(default=None, max_length=36)
    folder: str | None = Field(default=None, max_length=1024)
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, value):
        if value is None or not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("请输入有效的会话名称。")
        value.encode("utf-8")
        return value.strip()

    @field_validator("pinned")
    @classmethod
    def valid_pinned(cls, value):
        if value is None:
            raise ValueError("置顶状态必须为布尔值。")
        return value


class RegenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=36, max_length=36)

    @field_validator("request_id")
    @classmethod
    def valid_id(cls, value):
        return str(UUID(value))
