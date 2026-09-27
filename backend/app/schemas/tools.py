"""工具契约：严格输入，显式输出，不回显无效输入。"""

from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def validate_timezone(value: str) -> str:
    if value != "UTC" and "/" not in value:
        raise ValueError("请使用 Asia/Shanghai、America/New_Yo" + "rk 或 Etc/UTC 等 IANA 时区。")
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("时区不存在，请填写有效的 IANA 时区名称。") from None
    return value


class TimeInput(StrictInput):
    timezone: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "IANA 时区，如 Asia/Shanghai、America/"
            + "New_York、Etc/UTC；省略使用系统默认时区。禁止 C"
            + "ST 等缩写。"
        ),
    )

    @field_validator("timezone")
    @classmethod
    def timezone_name(cls, value):
        return validate_timezone(value) if value is not None else value


class ShellInput(StrictInput):
    command: str = Field(
        min_length=1,
        max_length=8000,
        description=(
            "要执行的 /bin/sh 命令。支持管道和本地已检查的脚本；禁止"
            + "联网、访问目录外数据或破坏系统。"
        ),
    )
    cwd: str = Field(
        default=".",
        min_length=1,
        max_length=1024,
        description=(
            "相对于授权目录的工作目录，默认 .；目录必须存在，禁止绝对路径、" + ".. 和符号链接。"
        ),
    )
    timeout_seconds: int = Field(
        default=10, ge=1, le=30, description="执行超时秒数，1–30，默认 10；超时终止进程组。"
    )

    @field_validator("command")
    @classmethod
    def valid_command(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("命令不能为空或包含空字节。")
        return value


class FileInput(StrictInput):
    operation: Literal["read", "create", "write"] = Field(
        description=(
            "read 读取现有文件；create 仅创建新文件，已存在时报错"
            + "；write 完整替换现有文件，不存在时报错。"
        )
    )
    path: str = Field(
        min_length=1,
        max_length=1024,
        description=(
            "相对于授权目录的文件路径，如 notes/todo.txt。禁止"
            + "绝对路径、..、符号链接和敏感文件；父目录须存在。"
        ),
    )
    content: str | None = Field(
        default=None,
        max_length=1048576,
        description=(
            "create/write 必填的 UTF-8 纯文本，可为空字符" + "串；read 不传此项。最大 1 MiB。"
        ),
    )

    @model_validator(mode="after")
    def check_content(self):
        if self.operation == "read" and "content" in self.model_fields_set:
            raise ValueError("read 不接受 content 参数。")
        if self.operation != "read" and self.content is None:
            raise ValueError("create/write 必须提供 content，可为空字符串。")
        if self.content is not None and len(self.content.encode("utf-8")) > 1024 * 1024:
            raise ValueError("文件内容不得超过 1 MiB。")
        return self


class ToolToggle(StrictInput):
    enabled: bool


class ToolCall(StrictInput):
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool_id: str
    success: bool
    code: str
    message: str
    data: dict[str, Any] | None = None
    duration_ms: int = 0


class ToolView(BaseModel):
    id: str
    name: str
    description: str
    limitations: list[str]
    input_schema: dict[str, Any]
    enabled: bool
    is_builtin: bool = True
    available: bool = True
    unavailable_reason: str | None = None
    defaults: dict[str, str]
