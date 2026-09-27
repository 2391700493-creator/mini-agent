from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ToolState


def states(session: Session) -> dict[str, bool]:
    return {item.id: item.enabled for item in session.scalars(select(ToolState))}


def enabled(session: Session, tool_id: str) -> bool:
    state = session.get(ToolState, tool_id, populate_existing=True)
    return state is not None and state.enabled


def set_enabled(session: Session, tool_id: str, value: bool):
    state = session.get(ToolState, tool_id)
    if state is None:
        raise LookupError("工具状态未初始化，请执行数据库迁移。")
    state.enabled = value
    session.commit()
