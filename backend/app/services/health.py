import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.repositories.health import get_project_name
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)


def check_health(session: Session) -> HealthResponse:
    try:
        project = get_project_name(session)
        if project == "mini-agent":
            return HealthResponse(status="ok", database="connected", project=project)
    except SQLAlchemyError:
        session.rollback()
        logger.exception("SQLite 健康检查失败，请检查数据库文件与 Alembic 迁移")
    return HealthResponse(status="unavailable", database="unavailable")
