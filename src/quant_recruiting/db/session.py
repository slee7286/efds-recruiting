from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from quant_recruiting.config import get_settings


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def get_engine(database_url: str | None = None) -> Any:
    if database_url:
        url = normalize_database_url(database_url)
    else:
        settings = get_settings()
        url = normalize_database_url(settings.shared_database_url or settings.database_url)
    return create_engine(url, pool_pre_ping=True)


@contextmanager
def session_scope() -> Generator[Session]:
    session = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def database_check() -> bool:
    with get_engine().connect() as connection:
        result: int = connection.execute(text("SELECT 1")).scalar_one()
        return result == 1


def database_diagnostics() -> dict[str, object]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    expected_heads = tuple(script.get_heads())
    with get_engine().begin() as connection:
        version = connection.execute(text("SHOW server_version")).scalar_one()
        current_rows = (
            connection.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num"))
            .scalars()
            .all()
        )
        extensions = (
            connection.execute(
                text("SELECT extname FROM pg_extension WHERE extname IN ('uuid-ossp','pgcrypto')")
            )
            .scalars()
            .all()
        )
        connection.execute(
            text("CREATE TEMP TABLE quant_recruiting_check (value integer) ON COMMIT DROP")
        )
        connection.execute(text("INSERT INTO quant_recruiting_check (value) VALUES (1)"))
        read_write = (
            connection.execute(text("SELECT value FROM quant_recruiting_check")).scalar_one() == 1
        )
    current = tuple(current_rows)
    return {
        "postgres_version": version,
        "current": current,
        "head": expected_heads,
        "schema_current": current == expected_heads,
        "extensions": extensions,
        "read_write": read_write,
    }
