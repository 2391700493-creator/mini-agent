from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    Agent,
    AgentMcp,
    AgentPrompt,
    AgentSkill,
    AgentTool,
    LanguageModel,
    ModelSecret,
)
from app.schemas.agents import AgentSummary

BINDINGS = {"tools": AgentTool, "skills": AgentSkill, "mcp_servers": AgentMcp}


def get(session: Session, agent_id: str) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "Agent 已不存在，请返回列表。")
    return agent


def bindings(session: Session, agent_id: str, kind: str):
    table = BINDINGS[kind]
    return list(
        session.scalars(select(table).where(table.agent_id == agent_id).order_by(table.resource_id))
    )


def prompt(session: Session, agent_id: str) -> AgentPrompt:
    return session.scalar(
        select(AgentPrompt)
        .where(AgentPrompt.agent_id == agent_id)
        .order_by(AgentPrompt.version.desc())
        .limit(1)
    )


def summary(session: Session, agent: Agent) -> AgentSummary:
    model = session.get(LanguageModel, agent.model_id)
    has_secret = session.get(ModelSecret, agent.model_id) is not None
    has_prompt = prompt(session, agent.id) is not None
    is_ready = model is not None and has_secret and has_prompt
    unavailable_reason = None
    if not has_secret:
        unavailable_reason = "模型密钥不可用，请检查模型配置。"
    elif not has_prompt:
        unavailable_reason = "系统提示词未设置，请编辑 Agent 后保存。"
    return AgentSummary(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        model_id=agent.model_id,
        model_name=model.display_name,
        model_identifier=model.model_id,
        max_rounds=agent.max_rounds,
        max_runtime_seconds=agent.max_runtime_seconds,
        max_tool_calls=agent.max_tool_calls,
        max_total_tokens=agent.max_total_tokens,
        auto_compress=agent.auto_compress,
        compression_trigger_ratio=agent.compression_trigger_ratio,
        compression_keep_recent_turns=agent.compression_keep_recent_turns,
        compression_summary_target_tokens=agent.compression_summary_target_tokens,
        is_default=agent.is_default,
        updated_at=agent.updated_at.replace(tzinfo=UTC),
        **{
            key: session.scalar(
                select(func.count()).select_from(table).where(table.agent_id == agent.id)
            )
            for key, table in [
                ("tool_count", AgentTool),
                ("skill_count", AgentSkill),
                ("mcp_server_count", AgentMcp),
            ]
        },
        is_ready=is_ready,
        unavailable_reason=unavailable_reason,
    )


def listing(session: Session):
    return [
        summary(session, agent)
        for agent in session.scalars(
            select(Agent).order_by(Agent.is_default.desc(), Agent.updated_at.desc(), Agent.id)
        )
    ]


def switch_default(session: Session, agent_id: str):
    now = datetime.now(UTC)
    session.execute(
        update(Agent).where(Agent.is_default.is_(True)).values(is_default=False, updated_at=now)
    )
    session.execute(
        update(Agent).where(Agent.id == agent_id).values(is_default=True, updated_at=now)
    )
