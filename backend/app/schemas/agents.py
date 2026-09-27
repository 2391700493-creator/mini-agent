from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.skills import ScanIssue

ResourceId = Annotated[str, Field(min_length=1, max_length=100)]


class AgentSave(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    system_prompt: str = Field(default="", max_length=100_000)
    model_id: str = Field(min_length=1, max_length=36)
    max_rounds: int = Field(default=10, ge=1, le=100)
    max_runtime_seconds: int = Field(default=300, ge=1, le=3600)
    max_tool_calls: int = Field(default=30, ge=0, le=10_000)
    max_total_tokens: int | None = Field(default=None, ge=1, le=100_000_000)
    auto_compress: bool = True
    compression_trigger_ratio: float = Field(default=0.8, ge=0.5, le=0.95)
    compression_keep_recent_turns: int = Field(default=4, ge=1, le=50)
    compression_summary_target_tokens: int = Field(default=1000, ge=128, le=32768)
    tool_ids: list[ResourceId] = Field(default_factory=list, max_length=3)
    skill_ids: list[ResourceId] = Field(default_factory=list, max_length=1000)
    mcp_server_ids: list[ResourceId] = Field(default_factory=list, max_length=1000)

    @field_validator("name", "model_id")
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("请填写有效名称或模型，不得包含控制字符。")
        return value.strip()

    @field_validator("name", "description", "system_prompt")
    @classmethod
    def valid_text(cls, value):
        if "\x00" in value:
            raise ValueError("内容不能包含空字节。")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("内容必须是有效的 UTF-8 文本。") from None
        return value

    @field_validator("tool_ids", "skill_ids", "mcp_server_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("不能重复选择同一项能力。")
        return value


class DeleteAgent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    replacement_id: str | None = Field(default=None, min_length=1, max_length=36)


class Capability(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool
    unavailable_reason: str | None = None


class ModelOption(BaseModel):
    id: str
    name: str
    model_id: str
    is_default: bool
    context_length: int
    max_output_tokens: int


class AgentOptions(BaseModel):
    models: list[ModelOption]
    tools: list[Capability]
    skills: list[Capability]
    mcp_servers: list[Capability]
    skill_issues: list[ScanIssue]


class AgentSummary(BaseModel):
    id: str
    name: str
    description: str
    model_id: str
    model_name: str
    model_identifier: str
    max_rounds: int
    max_runtime_seconds: int
    max_tool_calls: int
    max_total_tokens: int | None
    auto_compress: bool
    compression_trigger_ratio: float
    compression_keep_recent_turns: int
    compression_summary_target_tokens: int
    is_default: bool
    updated_at: datetime
    tool_count: int
    skill_count: int
    mcp_server_count: int
    is_ready: bool
    unavailable_reason: str | None = None


class AgentDetail(AgentSummary):
    system_prompt: str
    prompt_version: int
    tools: list[Capability]
    skills: list[Capability]
    mcp_servers: list[Capability]
