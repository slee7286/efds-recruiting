from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

from quant_recruiting.config import get_settings
from quant_recruiting.db import models  # noqa: F401
from quant_recruiting.db.base import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def compare_type(
    _context: Any,
    _inspected_column: Any,
    _metadata_column: Any,
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    """Treat portable SQLite JSON and PostgreSQL JSONB as the same model type."""
    inspected_name = str(getattr(inspected_type, "__visit_name__", "")).lower()
    metadata_name = str(getattr(metadata_type, "__visit_name__", "")).lower()
    if {inspected_name, metadata_name} <= {"json", "jsonb"}:
        return False
    return None


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=compare_type,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=compare_type,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
