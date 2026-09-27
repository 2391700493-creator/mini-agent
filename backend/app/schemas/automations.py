from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.chat import ChatView


class AutomationSave(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=100000)
    agent_id: str = Field(min_length=1, max_length=36)
    frequency: Literal["daily", "weekdays", "weekly"] = "daily"
    time: str = Field(default="09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: int = Field(default=0, ge=0, le=6)
    timezone: str = Field(default="Asia/Shanghai", max_length=100)
    allow_tools: bool = False
    enabled: bool = True

    @field_validator("name", "prompt")
    @classmethod
    def nonempty(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("请填写任务名称和内容。")
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("请选择有效时区。") from None
        return value


class AutomationToggle(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


class AutomationView(ChatView):
    id: str
    name: str
    prompt: str
    agent_id: str | None
    frequency: str
    time: str
    weekday: int
    timezone: str
    allow_tools: bool
    enabled: bool
    next_run_at: datetime
    status: str
    last_error: str | None
    last_conversation_id: str | None
    last_run_at: datetime | None

    @field_validator("next_run_at", "last_run_at")
    @classmethod
    def utc_time(cls, value):
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value
