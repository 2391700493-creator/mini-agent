"""应用元数据、模型配置及加密凭据。"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AppMetadata(Base):
    __tablename__ = "app_metadata"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)


class LanguageModel(Base):
    __tablename__ = "language_models"
    __table_args__ = (
        Index(
            "uq_language_models_default",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
        ),
        CheckConstraint(
            "context_length > 0 AND max_output_tokens > 0 AND max_output_tokens <= context_length",
            name="ck_model_tokens",
        ),
        CheckConstraint("temperature >= 0 AND temperature <= 2", name="ck_model_temperature"),
        CheckConstraint(
            "input_price >= 0 AND output_price >= 0 AND cached_input_price >= 0",
            name="ck_model_prices",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    model_id: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(2048))
    context_length: Mapped[int]
    max_output_tokens: Mapped[int]
    temperature: Mapped[float] = mapped_column(Float)
    input_price: Mapped[float | None] = mapped_column(Float)
    output_price: Mapped[float | None] = mapped_column(Float)
    cached_input_price: Mapped[float | None] = mapped_column(Float)
    pricing_currency: Mapped[str] = mapped_column(
        String(3), default="CNY", server_default=text("'CNY'")
    )
    price_unit_tokens: Mapped[int] = mapped_column(
        Integer, default=1_000_000, server_default=text("1000000")
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModelSecret(Base):
    __tablename__ = "model_secrets"

    model_id: Mapped[str] = mapped_column(
        ForeignKey("language_models.id", ondelete="CASCADE"), primary_key=True
    )
    ciphertext: Mapped[str] = mapped_column(Text)


class ToolState(Base):
    __tablename__ = "tool_states"
    __table_args__ = (
        CheckConstraint("id IN ('current_time', 'shell', 'file')", name="ck_builtin_tool_id"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)


class SkillState(Base):
    __tablename__ = "skill_states"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class McpServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    command: Mapped[str] = mapped_column(Text)
    args: Mapped[list] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="untested")
    message: Mapped[str] = mapped_column(Text, default="未测试")
    diagnostic: Mapped[str | None] = mapped_column(Text)
    tested_at: Mapped[str | None] = mapped_column(String(40))
    last_success_at: Mapped[str | None] = mapped_column(String(40))
    tools: Mapped[list | None] = mapped_column(JSON, nullable=True)


class McpSecret(Base):
    __tablename__ = "mcp_secrets"

    server_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), primary_key=True
    )
    ciphertext: Mapped[str] = mapped_column(Text)


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        Index("uq_agents_default", "is_default", unique=True, sqlite_where=text("is_default = 1")),
        CheckConstraint("max_rounds >= 1 AND max_rounds <= 100", name="ck_agent_max_rounds"),
        CheckConstraint(
            "max_runtime_seconds >= 1 AND max_runtime_seconds <= 3600",
            name="ck_agent_max_runtime_seconds",
        ),
        CheckConstraint(
            "max_tool_calls >= 0 AND max_tool_calls <= 10000", name="ck_agent_max_tool_calls"
        ),
        CheckConstraint(
            "compression_trigger_ratio >= 0.5 AND compression_trigger_ratio <= 0.95",
            name="ck_agent_compression_trigger_ratio",
        ),
        CheckConstraint(
            "compression_keep_recent_turns >= 1 AND compression_keep_recent_turns <= 50",
            name="ck_agent_compression_keep_recent_turns",
        ),
        CheckConstraint(
            "compression_summary_target_tokens >= 128 "
            "AND compression_summary_target_tokens <= 32768",
            name="ck_agent_compression_summary_target_tokens",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(
        ForeignKey("language_models.id", ondelete="RESTRICT"), index=True
    )
    max_rounds: Mapped[int]
    max_runtime_seconds: Mapped[int] = mapped_column(default=300, server_default=text("300"))
    max_tool_calls: Mapped[int] = mapped_column(default=30, server_default=text("30"))
    max_total_tokens: Mapped[int | None]
    auto_compress: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    compression_trigger_ratio: Mapped[float] = mapped_column(
        Float, default=0.8, server_default=text("0.8")
    )
    compression_keep_recent_turns: Mapped[int] = mapped_column(default=4, server_default=text("4"))
    compression_summary_target_tokens: Mapped[int] = mapped_column(
        default=1000, server_default=text("1000")
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentPrompt(Base):
    __tablename__ = "agent_prompts"
    __table_args__ = (CheckConstraint("version >= 1", name="ck_agent_prompt_version"),)

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentTool(Base):
    __tablename__ = "agent_tools"

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("tool_states.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)


class AgentSkill(Base):
    __tablename__ = "agent_skills"

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("skill_states.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)


class AgentMcp(Base):
    __tablename__ = "agent_mcp_servers"

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    # None 仅用于迁移前绑定，兼容其既有权限；新绑定固定发现时的工具名清单。
    allowed_tools: Mapped[list | None] = mapped_column(JSON)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Automation(Base):
    __tablename__ = "automations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    prompt: Mapped[str] = mapped_column(Text)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    frequency: Mapped[str] = mapped_column(String(20))
    time: Mapped[str] = mapped_column(String(5))
    weekday: Mapped[int] = mapped_column(default=0)
    timezone: Mapped[str] = mapped_column(String(100))
    allow_tools: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="idle")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(100), default="新会话")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    title_custom: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)
    folder: Mapped[str | None] = mapped_column(String(1024))
    archive_error: Mapped[str | None] = mapped_column(String(200))
    context_summary: Mapped[str | None] = mapped_column(Text)
    summarized_through_sequence: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Memory(Base):
    """用户主动保存、按 Agent 隔离的跨会话背景。"""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    source_conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("uq_chat_message_order", "conversation_id", "sequence", unique=True),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_role"),
        CheckConstraint(
            "status IN ('generating', 'completed', 'failed', 'cancelled')", name="ck_chat_status"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    sequence: Mapped[int]
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 历史归属快照不设 Agent 外键，删除或改名均不影响旧消息。
    agent_id: Mapped[str | None] = mapped_column(String(36))
    agent_name: Mapped[str | None] = mapped_column(String(100))

    feedback_rating: Mapped[str | None] = mapped_column(String(20))

    attachments: Mapped[list["ChatAttachment"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="ChatAttachment.position"
    )


class ChatAttachment(Base):
    __tablename__ = "chat_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    name: Mapped[str] = mapped_column(String(200))
    mime_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int]
    digest: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, deferred=True)
    width: Mapped[int | None]
    height: Mapped[int | None]


class ChatGeneration(Base):
    __tablename__ = "chat_generations"
    __table_args__ = (
        Index(
            "uq_chat_active_generation",
            "conversation_id",
            unique=True,
            sqlite_where=text("status = 'generating'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # 评测 Run 没有聊天会话；仍复用同一张 Run 表和事件轨迹。
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_message_id: Mapped[str | None] = mapped_column(ForeignKey("chat_messages.id"))
    assistant_message_id: Mapped[str] = mapped_column(String(36))
    sequence: Mapped[int]
    agent_id: Mapped[str] = mapped_column(String(36))
    agent_name: Mapped[str] = mapped_column(String(100))
    model_id: Mapped[str | None] = mapped_column(String(36))
    model_name: Mapped[str | None] = mapped_column(String(100))
    model_identifier: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    end_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None]
    model_call_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    tool_call_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    usage_report_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    usage_complete: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    input_tokens: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    total_tokens: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    cached_input_tokens: Mapped[int | None]
    pricing_snapshot: Mapped[dict | None] = mapped_column(JSON)
    cost: Mapped[float | None] = mapped_column(Float)
    cost_status: Mapped[str] = mapped_column(
        String(20), default="unknown", server_default=text("'unknown'")
    )
    first_output_ms: Mapped[int | None]
    source: Mapped[str] = mapped_column(String(20), default="chat", server_default=text("'chat'"))


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (Index("ix_run_events_run_order", "run_id", "sequence"),)

    run_id: Mapped[str] = mapped_column(
        ForeignKey("chat_generations.id", ondelete="CASCADE"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(40))
    round: Mapped[int | None]
    call_id: Mapped[str | None] = mapped_column(String(36), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSON)
    has_payload: Mapped[bool] = mapped_column(Boolean, default=False)


class RunEventPayload(Base):
    __tablename__ = "run_event_payloads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "sequence"],
            ["run_events.run_id", "run_events.sequence"],
            ondelete="CASCADE",
        ),
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class EvaluationDataset(Base):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (Index("uq_evaluation_dataset_stable_key", "stable_key", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stable_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"
    __table_args__ = (
        CheckConstraint("length(question) > 0", name="ck_evaluation_case_question"),
        CheckConstraint(
            "expected_answer IS NOT NULL OR grading_criteria IS NOT NULL",
            name="ck_evaluation_case_material",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    grading_criteria: Mapped[str | None] = mapped_column(Text)
    history: Mapped[list | None] = mapped_column(JSON)
    process_rules: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvaluationTask(Base):
    __tablename__ = "evaluation_tasks"
    __table_args__ = (
        CheckConstraint(
            "passing_score >= 0 AND passing_score <= 100", name="ck_eval_passing_score"
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'interrupted')",
            name="ck_eval_task_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(36))
    dataset_name: Mapped[str] = mapped_column(String(100))
    agent_id: Mapped[str] = mapped_column(String(36))
    agent_name: Mapped[str] = mapped_column(String(100))
    scoring_model_id: Mapped[str] = mapped_column(String(36))
    scoring_model_name: Mapped[str] = mapped_column(String(100))
    scoring_model_identifier: Mapped[str] = mapped_column(String(200))
    scoring_model_snapshot: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'")
    )
    passing_score: Mapped[float] = mapped_column(Float)
    tools_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    agent_snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationTaskCase(Base):
    __tablename__ = "evaluation_task_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'executing', 'grading', 'passed', 'failed', "
            "'execution_failed', 'grading_failed')",
            name="ck_eval_case_status",
        ),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_eval_score"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_tasks.id", ondelete="CASCADE"), index=True
    )
    source_case_id: Mapped[str] = mapped_column(String(36))
    position: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    grading_criteria: Mapped[str | None] = mapped_column(Text)
    history: Mapped[list | None] = mapped_column(JSON)
    process_rules: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_generations.id", ondelete="SET NULL")
    )
    answer: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    grading_error_kind: Mapped[str | None] = mapped_column(String(20))
    scoring_duration_ms: Mapped[int | None] = mapped_column(Integer)
    scoring_input_tokens: Mapped[int | None] = mapped_column(Integer)
    scoring_output_tokens: Mapped[int | None] = mapped_column(Integer)
    scoring_total_tokens: Mapped[int | None] = mapped_column(Integer)
    scoring_cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    scoring_usage_complete: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("1")
    )
    grading_attempts: Mapped[int] = mapped_column(Integer, default=0)
    issue_category: Mapped[str | None] = mapped_column(String(40))
    review_status: Mapped[str] = mapped_column(
        String(20), default="unreviewed", server_default=text("'unreviewed'")
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
