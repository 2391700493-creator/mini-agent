from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SkillState


def states(session: Session) -> dict[str, SkillState]:
    return {item.id: item for item in session.scalars(select(SkillState))}


def ensure_states(session: Session, ids: list[str]) -> dict[str, SkillState]:
    current = states(session)
    for skill_id in ids:
        if skill_id not in current:
            item = SkillState(id=skill_id, enabled=True, updated_at=datetime.now(UTC))
            session.add(item)
            current[skill_id] = item
    session.commit()
    return current


def set_enabled(session: Session, skill_id: str, enabled: bool):
    item = session.get(SkillState, skill_id)
    item.enabled = enabled
    item.updated_at = datetime.now(UTC)
    session.commit()


def delete(session: Session, skill_id: str):
    item = session.get(SkillState, skill_id)
    if item is not None:
        session.delete(item)
    session.commit()
