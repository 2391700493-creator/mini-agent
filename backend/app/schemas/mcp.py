"""MCP 配置的显式输入输出；None 表示保留已有环境变量。"""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class McpSave(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    command: str = Field(min_length=1, max_length=2048)
    args: list[str] = Field(default_factory=list, max_length=100)
    env: dict[str, SecretStr | None] = Field(default_factory=dict, max_length=100)

    @field_validator("name", "command")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("请填写有效的单行名称或可执行文件。")
        return value.strip()

    @field_validator("command")
    @classmethod
    def local_command(cls, value: str) -> str:
        if "://" in value:
            raise ValueError("本阶段只支持本机可执行文件，不支持远程地址。")
        return value

    @field_validator("args")
    @classmethod
    def valid_args(cls, values: list[str]) -> list[str]:
        if any("\x00" in value or len(value) > 8192 for value in values):
            raise ValueError("参数不能包含空字符，且每项最多 8192 字符。")
        return values

    @field_validator("env")
    @classmethod
    def valid_env(cls, values: dict[str, SecretStr | None]):
        for key, value in values.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key):
                raise ValueError("环境变量名称只能包含字母、数字和下划线，不能以数字开头。")
            if value is not None:
                raw = value.get_secret_value()
                if "\x00" in raw or len(raw) > 8192 or raw in {"********", "••••••••"}:
                    raise ValueError("请输入实际环境变量值；保留原值请使用保留选项。")
        return values


class McpToggle(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


class McpJsonImport(BaseModel):
    """从常见 mcpServers JSON 读取一个本机 stdio 配置。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    configuration: str = Field(min_length=2, max_length=1_048_576)
    server_name: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("configuration")
    @classmethod
    def configuration_text(cls, value):
        if "\x00" in value:
            raise ValueError("配置内容无效。")
        return value


class McpImportPreview(BaseModel):
    name: str
    description: str
    command: str
    args: list[str]
    env_keys: list[str]


class McpTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class McpView(BaseModel):
    id: str
    name: str
    description: str
    command: str
    args: list[str]
    env: dict[str, str]
    enabled: bool
    testing: bool
    status: Literal["untested", "success", "error", "stale"]
    message: str
    diagnostic: str | None
    tested_at: str | None
    last_success_at: str | None
    tool_count: int | None
    tools: list[McpTool]
