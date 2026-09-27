from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import BACKEND_DIR
from app.main import create_app


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def migration_config(database_path: Path) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_path"] = database_path
    return config


@pytest.fixture
def migrated_database(database_path: Path, migration_config: Config) -> Path:
    command.upgrade(migration_config, "head")
    return database_path


@pytest.fixture
def client(migrated_database: Path):
    with TestClient(
        create_app(
            migrated_database,
            key_path=migrated_database.with_suffix(".key"),
            tool_root=migrated_database.parent / "workspace",
            skills_root=migrated_database.parent / "skills",
        )
    ) as test_client:
        yield test_client
