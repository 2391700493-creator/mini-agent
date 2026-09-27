from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

RunStatus = Literal["running", "success", "partial", "failed", "cancelled"]


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str | None
    status: RunStatus
    agent_id: str
    agent_name: str
    model_id: str | None
    model_name: str | None
    model_identifier: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    model_call_count: int
    tool_call_count: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_input_tokens: int | None
    cost: float | None
    cost_currency: str | None
    cost_status: Literal["complete", "incomplete", "unknown"]
    usage_status: Literal["complete", "incomplete", "unknown"]
    first_output_ms: int | None
    end_reason: str | None
    error_summary: str | None

    @field_validator("started_at", "ended_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class RunAgentOption(BaseModel):
    id: str
    name: str


class RunModelOption(BaseModel):
    id: str | None
    name: str


class RunMetrics(BaseModel):
    total: int
    success_rate: float | None
    p95_duration_ms: int | None
    first_output_ms: int | None
    total_tokens: int | None
    tool_error_rate: float | None
    total_cost: float | None
    cost_currency: str | None
    incomplete_cost_runs: int


class RunPage(BaseModel):
    items: list[RunView]
    total: int
    page: int
    page_size: int
    agents: list[RunAgentOption]
    models: list[RunModelOption]
    metrics: RunMetrics


class RunEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    sequence: int
    type: str
    round: int | None
    call_id: str | None
    occurred_at: datetime
    data: dict
    has_payload: bool

    @field_validator("occurred_at")
    @classmethod
    def utc_timestamp(cls, value: datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class RunDetail(RunView):
    events: list[RunEventView]
    final_answer: str | None


class RunEventPayloadView(BaseModel):
    run_id: str
    sequence: int
    payload: dict
