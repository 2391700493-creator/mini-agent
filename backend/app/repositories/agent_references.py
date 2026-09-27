"""资源删除前的引用检查；调用方须持有对应资源锁或写事务。"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, AgentMcp, AgentSkill


def ensure_unreferenced(session: Session, kind: str, resource_id: str):
    query = select(Agent.name)
    if kind == "model":
        query = query.where(Agent.model_id == resource_id)
    else:
        binding = {"skill": AgentSkill, "mcp": AgentMcp}[kind]
        query = query.join(binding, binding.agent_id == Agent.id).where(
            binding.resource_id == resource_id
        )
    names = list(session.scalars(query.order_by(Agent.name, Agent.id)))
    if names:
        raise HTTPException(
            409,
            "无法删除，正在被 Agent 使用："
            + "、".join(f"「{name}」" for name in names)
            + "。请先修改或删除这些 Agent，再重试。",
        )
