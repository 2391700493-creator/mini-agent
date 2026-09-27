from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, resolve_database_path
from app.db import make_engine
from app.models import AppMetadata


def test_migration_round_trip_and_model_parity(migration_config: Config, database_path: Path):
    command.upgrade(migration_config, "head")
    command.check(migration_config)
    engine = make_engine(database_path)
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == ScriptDirectory.from_config(migration_config).get_current_head()
        )
        assert connection.scalar(text("SELECT value FROM app_metadata")) == "mini-agent"
    engine.dispose()

    command.downgrade(migration_config, "base")
    engine = make_engine(database_path)
    assert "app_metadata" not in inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(migration_config, "head")
    command.upgrade(migration_config, "head")
    engine = make_engine(database_path)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM app_metadata")) == 1
    engine.dispose()


def test_sqlite_configuration_and_persistence(migrated_database: Path):
    engine = make_engine(migrated_database)
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
        assert connection.scalar(text("PRAGMA busy_timeout")) == 5000
    with Session(engine) as session:
        session.add(AppMetadata(key="test_record", value="saved"))
        session.commit()
    engine.dispose()

    reopened_engine = make_engine(migrated_database)
    with Session(reopened_engine) as session:
        assert session.get(AppMetadata, "test_record").value == "saved"
        session.add(AppMetadata(key="not_committed", value="discarded"))
        session.flush()
    with Session(reopened_engine) as session:
        assert session.get(AppMetadata, "not_committed") is None
    reopened_engine.dispose()


def test_relative_database_path_is_independent_of_cwd(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MINI_AGENT_DATABASE_PATH", "data/custom.db")
    assert resolve_database_path() == BACKEND_DIR / "data/custom.db"
    assert resolve_database_path(tmp_path / "absolute.db") == tmp_path / "absolute.db"
