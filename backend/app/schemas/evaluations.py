from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = str
TaskStatus = Literal["pending", "running", "completed", "interrupted"]
CaseStatus = Literal[
    "pending", "executing", "grading", "passed", "failed", "execution_failed", "grading_failed"
]


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=100_000)

    @field_validator("content")
    @classmethod
    def content_valid(cls, value):
        return _text(value, "历史消息") or (_ for _ in ()).throw(ValueError("历史消息不能为空。"))


class ProcessRules(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_tool_ids: list[str] = Field(default_factory=list, max_length=100)
    max_tool_calls: int | None = Field(default=None, ge=0, le=10_000)
    max_duration_ms: int | None = Field(default=None, ge=1, le=3_600_000)

    @field_validator("expected_tool_ids")
    @classmethod
    def unique_tools(cls, value):
        if len(value) != len(set(value)) or any(
            not item.strip() or len(item) > 100 for item in value
        ):
            raise ValueError("期望工具标识无效或重复。")
        return value


def _text(value: str | None, field: str, maximum: int = 100_000):
    if value is None:
        return None
    if "\x00" in value or len(value) > maximum:
        raise ValueError(f"{field}内容无效。")
    return value.strip() or None


class DatasetSave(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)

    @field_validator("name")
    @classmethod
    def name_valid(cls, value):
        return _text(value, "名称", 100) or (_ for _ in ()).throw(ValueError("请填写名称。"))

    @field_validator("description")
    @classmethod
    def description_valid(cls, value):
        return _text(value, "说明", 5000) or ""


class CaseSave(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=1, max_length=100_000)
    expected_answer: str | None = Field(default=None, max_length=100_000)
    grading_criteria: str | None = Field(default=None, max_length=100_000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=100)
    process_rules: ProcessRules = Field(default_factory=ProcessRules)

    @field_validator("question", "expected_answer", "grading_criteria")
    @classmethod
    def contents(cls, value, info):
        return _text(value, info.field_name)

    @model_validator(mode="after")
    def material(self):
        if not self.question:
            raise ValueError("请填写用户问题。")
        if not self.expected_answer and not self.grading_criteria:
            raise ValueError("期望答案和评分要求至少填写一项。")
        return self


class DatasetView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str
    case_count: int = 0
    created_at: datetime
    updated_at: datetime


class CaseView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    dataset_id: str
    position: int
    question: str
    expected_answer: str | None
    grading_criteria: str | None
    history: list[HistoryMessage] = Field(default_factory=list)
    process_rules: ProcessRules = Field(default_factory=ProcessRules)
    created_at: datetime
    updated_at: datetime


class DatasetDetail(DatasetView):
    cases: list[CaseView]


class EvaluationOptions(BaseModel):
    agents: list[dict]
    models: list[dict]


class TaskSave(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_id: str = Field(min_length=1, max_length=36)
    agent_id: str = Field(min_length=1, max_length=36)
    scoring_model_id: str = Field(min_length=1, max_length=36)
    passing_score: float = Field(default=60, ge=0, le=100)
    tools_allowed: bool = False

    @field_validator("passing_score")
    @classmethod
    def finite_score(cls, value):
        import math

        if not math.isfinite(value):
            raise ValueError("通过分数必须是有限数字。")
        return value


class CaseReviewSave(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    review_status: Literal["unreviewed", "confirmed", "dismissed"]
    review_note: str | None = Field(default=None, max_length=5000)

    @field_validator("review_note")
    @classmethod
    def note_valid(cls, value):
        return _text(value, "复核说明", 5000)


class TaskCaseView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    position: int
    question: str
    expected_answer: str | None
    grading_criteria: str | None
    history: list[HistoryMessage] = Field(default_factory=list)
    process_rules: ProcessRules = Field(default_factory=ProcessRules)
    status: CaseStatus
    run_id: str | None
    answer: str | None
    score: float | None
    reason: str | None
    error: str | None
    grading_error_kind: str | None
    scoring_duration_ms: int | None
    scoring_total_tokens: int | None
    scoring_cached_input_tokens: int | None
    scoring_usage_complete: bool
    grading_attempts: int
    issue_category: str | None
    review_status: Literal["unreviewed", "confirmed", "dismissed"]
    review_note: str | None


class TaskStats(BaseModel):
    total: int
    completed: int
    passed: int
    failed: int
    execution_failed: int
    grading_failed: int
    average_score: float | None


class TaskView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    dataset_id: str
    dataset_name: str
    agent_id: str
    agent_name: str
    scoring_model_id: str
    scoring_model_name: str
    passing_score: float
    tools_allowed: bool
    status: TaskStatus
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    stats: TaskStats


class TaskDetail(TaskView):
    scoring_model_identifier: str
    scoring_model_snapshot: dict
    agent_snapshot: dict
    cases: list[TaskCaseView]
