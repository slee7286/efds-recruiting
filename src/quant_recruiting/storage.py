"""Explicit storage routing for local-private and shared intelligence data."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from quant_recruiting.config import Settings, get_settings
from quant_recruiting.db.session import get_engine
from quant_recruiting.local_db import local_session_scope


def get_shared_engine(settings: Settings | None = None) -> Any:
    config = settings or get_settings()
    if not config.shared_enabled or not config.shared_database_url:
        raise RuntimeError("shared PostgreSQL is disabled or SHARED_DATABASE_URL is not configured")
    return get_engine(config.shared_database_url)


@contextmanager
def get_local_session(settings: Settings | None = None) -> Generator[Session]:
    with local_session_scope(settings) as session:
        yield session


@contextmanager
def get_shared_session(settings: Settings | None = None) -> Generator[Session]:
    engine = get_shared_engine(settings)
    session = Session(bind=engine, autoflush=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


@contextmanager
def private_session_scope(settings: Settings | None = None) -> Generator[Session]:
    config = settings or get_settings()
    if config.storage_mode == "local_first":
        with local_session_scope(config) as session:
            yield session
    else:
        with get_shared_session(config) as session:
            yield session


def assert_private_write_is_local(settings: Settings | None = None) -> None:
    config = settings or get_settings()
    if config.auto_push_private:
        raise RuntimeError(
            "private automatic push is prohibited; auto_push_private is hard-disabled"
        )
