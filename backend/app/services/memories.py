from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Agent, Conversation, Memory
from app.repositories.language_models import write_transaction
from app.schemas.memories import MemorySave, MemoryView


class MemoryStore:
    def __init__(self, factory):
        self.factory = factory

    def listing(self, agent_id: str):
        with self.factory() as session:
            if session.get(Agent, agent_id) is None:
                raise HTTPException(404, "Agent 不存在。")
            return [
                MemoryView.model_validate(row)
                for row in session.scalars(
                    select(Memory)
                    .where(Memory.agent_id == agent_id)
                    .order_by(Memory.updated_at.desc(), Memory.id)
                )
            ]

    def save(self, agent_id: str, data: MemorySave, memory_id: str | None = None):
        with self.factory() as session, write_transaction(session):
            if session.get(Agent, agent_id) is None:
                raise HTTPException(404, "Agent 不存在。")
            if (
                data.source_conversation_id
                and session.get(Conversation, data.source_conversation_id) is None
            ):
                raise HTTPException(422, "来源会话不存在。")
            row = session.get(Memory, memory_id) if memory_id else None
            if memory_id and (row is None or row.agent_id != agent_id):
                raise HTTPException(404, "记忆不存在。")
            stamp = datetime.now(UTC)
            if row is None:
                row = Memory(
                    id=str(uuid4()),
                    agent_id=agent_id,
                    content=data.content,
                    source_conversation_id=data.source_conversation_id,
                    created_at=stamp,
                    updated_at=stamp,
                )
                session.add(row)
            else:
                row.content = data.content
                row.source_conversation_id = data.source_conversation_id
                row.updated_at = stamp
            session.flush()
            return MemoryView.model_validate(row)

    def delete(self, agent_id: str, memory_id: str):
        with self.factory() as session, write_transaction(session):
            row = session.get(Memory, memory_id)
            if row is None or row.agent_id != agent_id:
                raise HTTPException(404, "记忆不存在。")
            session.delete(row)
