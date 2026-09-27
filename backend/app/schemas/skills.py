"""Skill 是任务说明；文件内容与运行能力分开管理。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SkillContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    instructions: str = Field(min_length=1, max_length=500_000)

    @field_validator("name", "description", "instructions")
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("内容不能为空或包含空字节。")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("内容必须是有效的 UTF-8 文本。") from None
        return value

    @field_validator("name", "description")
    @classmethod
    def trim_metadata(cls, value):
        return value.strip()

    @field_validator("name")
    @classmethod
    def single_line(cls, value):
        if any(ord(char) < 32 for char in value):
            raise ValueError("名称不能包含换行或控制字符。")
        return value


class SkillSave(SkillContent):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class SkillToggle(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


class SkillSummary(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool
    updated_at: datetime


class SkillDetail(SkillSummary):
    instructions: str
    revision: str


class ScanIssue(BaseModel):
    directory: str
    message: str


class SkillList(BaseModel):
    items: list[SkillSummary]
    issues: list[ScanIssue]
