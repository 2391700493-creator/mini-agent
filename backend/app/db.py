"""统一 SQLite 连接和请求级会话；表结构只由 Alembic 管理。"""

from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import resolve_database_path


class Base(DeclarativeBase):
    pass


def make_engine(database_path: str | Path | None = None) -> Engine:
    path = resolve_database_path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("sqlite", database=str(path)),
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _connection_record):
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    return engine


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session
