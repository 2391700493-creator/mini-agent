"""配置只允许 SQLite 文件路径，不接受其他数据库连接字符串。"""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def resolve_database_path(path: str | Path | None = None) -> Path:
    value = (
        path if path is not None else os.getenv("MINI_AGENT_DATABASE_PATH", "data/mini-agent.db")
    )
    database_path = Path(value).expanduser()
    if not database_path.is_absolute():
        database_path = BACKEND_DIR / database_path
    return database_path.resolve()
