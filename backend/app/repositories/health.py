from sqlalchemy.orm import Session

from app.models import AppMetadata


def get_project_name(session: Session) -> str | None:
    metadata = session.get(AppMetadata, "project_name")
    return metadata.value if metadata else None
