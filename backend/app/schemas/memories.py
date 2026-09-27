from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MemorySave(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    content: str = Field(min_length=1, max_length=10_000)
    source_conversation_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("content")
    @classmethod
    def valid_content(cls, value):
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("记忆内容无效。")
        return value


class MemoryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    content: str
    source_conversation_id: str | None
    created_at: datetime
    updated_at: datetime
