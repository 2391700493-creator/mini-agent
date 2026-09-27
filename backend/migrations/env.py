"""迁移与应用共享路径解析及 SQLAlchemy metadata。"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL

from app.config import resolve_database_path
from app.db import Base, make_engine
from app.models import AppMetadata  # noqa: F401 — 注册当前模型到 metadata

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
database_path = resolve_database_path(config.attributes.get("database_path"))


def run_migrations_offline() -> None:
    context.configure(
        url=URL.create("sqlite", database=str(database_path)),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(database_path)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
