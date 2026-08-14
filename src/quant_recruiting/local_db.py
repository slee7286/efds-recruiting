"""Local SQLite storage for private candidate/application data."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from quant_recruiting import local_models as _local_models  # noqa: F401 - register local tables
from quant_recruiting.config import Settings, get_settings
from quant_recruiting.db import models as _models  # noqa: F401 - register ORM tables
from quant_recruiting.db.base import Base

LOCAL_SCHEMA_VERSION = 5

# Private records plus the compact shared objects needed for offline operation.
# The same stable UUID-backed models are reused locally; `local_sync_state`
# records whether a row came from the shared read-only cache.
LOCAL_TABLE_NAMES = {
    "companies",
    "company_aliases",
    "company_domains",
    "role_families",
    "company_ats",
    "jobs",
    "job_observations",
    "research_sources",
    "research_documents",
    "research_claims",
    "firm_intelligence_items",
    "firm_intelligence_sources",
    "recruiting_cycles",
    "recruiting_events",
    "interview_stages",
    "interview_reports",
    "interview_questions",
    "interview_report_questions",
    "skills",
    "job_skills",
    "interview_question_skills",
    "resources",
    "resource_skills",
    "resource_sections",
    "resource_section_skills",
    "resource_role_families",
    "resource_companies",
    "resource_interview_stages",
    "candidate_experiences",
    "candidate_evidence",
    "candidate_evidence_skills",
    "candidate_stories",
    "candidate_story_evidence",
    "candidate_profiles",
    "candidate_sensitive_fields",
    "candidate_cv_sections",
    "candidate_cv_entries",
    "applications",
    "application_events",
    "application_requirements",
    "application_requirement_evidence",
    "application_gaps",
    "application_arguments",
    "application_argument_evidence",
    "application_argument_sources",
    "cv_versions",
    "cv_bullets",
    "cv_bullet_evidence",
    "application_questions",
    "application_answers",
    "application_answer_evidence",
    "application_answer_sources",
    "cover_letter_blocks",
    "cover_letter_block_evidence",
    "cover_letter_block_sources",
    "application_artifacts",
    "artifact_provenance",
    "review_events",
    "question_attempts",
    "ai_tasks",
    "ai_task_runs",
    "ai_task_outputs",
    "ai_prompt_versions",
    "browser_fill_runs",
    "browser_field_mappings",
    "local_sync_state",
    "local_sync_cursors",
    "local_shared_cache",
    "local_application_references",
    "ai_conversations",
    "ai_conversation_messages",
    "ai_conversation_attachments",
    "ai_conversation_links",
    "ai_conversation_annotations",
    "local_publish_intents",
    "browser_runs",
    "browser_pages",
    "browser_fields",
    "local_browser_field_mappings",
    "browser_fill_attempts",
    "browser_uploads",
    "browser_validation_errors",
    "browser_run_attempts",
    "browser_parsed_values",
    "browser_field_aliases",
    "candidate_form_values",
    "application_form_values",
    "email_accounts",
    "email_threads",
    "email_messages",
    "email_attachments",
    "email_links",
    "email_extractions",
    "assessment_providers",
    "timeline_events",
    "recruiting_actions",
    "reminders",
    "interview_appointments",
    "assessments",
    "prep_plans",
    "prep_plan_items",
    "recruiting_contacts",
    "interview_notes",
    "notifications",
    "background_runs",
    "background_task_results",
    "job_alert_rules",
    "job_alert_matches",
    "browser_issues",
}


def local_database_url(settings: Settings | None = None) -> str:
    config = settings or get_settings()
    if config.local_database_url:
        return config.local_database_url
    return f"sqlite:///{(config.local_data_dir / 'recruiting.db').as_posix()}"


def get_local_engine(settings: Settings | None = None) -> Engine:
    from sqlalchemy import create_engine

    url = local_database_url(settings)
    if url.startswith("sqlite:///") and not url.endswith(":memory:"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, **kwargs)
    if engine.url.get_backend_name() == "sqlite":
        _configure_sqlite(engine)
    return engine


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def upgrade_local(settings: Settings | None = None) -> None:
    engine = get_local_engine(settings)
    selected = [table for name, table in Base.metadata.tables.items() if name in LOCAL_TABLE_NAMES]
    Base.metadata.create_all(engine, tables=selected, checkfirst=True)
    with engine.begin() as connection:
        # The local schema intentionally has a lightweight migration chain.  Additive
        # columns are upgraded in place so V12 databases do not need to be rebuilt.
        additive_columns = {
            "browser_runs": {
                "dogfood": "BOOLEAN NOT NULL DEFAULT 0",
                "feedback_status": "VARCHAR(30)",
                "feedback_note": "TEXT",
                "manual_intervention_count": "INTEGER NOT NULL DEFAULT 0",
            },
            "email_accounts": {
                "history_id": "VARCHAR(255)",
                "last_full_sync_at": "DATETIME",
            },
        }
        for table_name, columns in additive_columns.items():
            present = {column["name"] for column in inspect(connection).get_columns(table_name)}
            for column_name, declaration in columns.items():
                if column_name not in present:
                    connection.exec_driver_sql(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {declaration}'
                    )
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS local_schema_version (version INTEGER NOT NULL)"
        )
        current = connection.execute(
            text("SELECT version FROM local_schema_version ORDER BY version DESC LIMIT 1")
        ).scalar_one_or_none()
        if current is None:
            connection.execute(
                text("INSERT INTO local_schema_version (version) VALUES (:v)"),
                {"v": LOCAL_SCHEMA_VERSION},
            )
        elif current in {1, 2, 3, 4}:
            connection.execute(
                text("UPDATE local_schema_version SET version = :v"),
                {"v": LOCAL_SCHEMA_VERSION},
            )
        elif current != LOCAL_SCHEMA_VERSION:
            raise RuntimeError(
                f"unsupported local schema version {current}; expected {LOCAL_SCHEMA_VERSION}"
            )
        connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS ai_conversation_fts "
            "USING fts5(conversation_id UNINDEXED, title, content)"
        )
    engine.dispose()


def local_diagnostics(settings: Settings | None = None) -> dict[str, object]:
    engine = get_local_engine(settings)
    upgrade_local(settings)
    with engine.begin() as connection:
        integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar_one()
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
        tables = inspect(connection).get_table_names()
        fts_available = bool(
            connection.exec_driver_sql(
                "SELECT 1 FROM pragma_compile_options WHERE compile_options LIKE 'ENABLE_FTS5%'"
            ).scalar_one_or_none()
        )
    engine.dispose()
    return {
        "path": str((settings or get_settings()).local_data_dir / "recruiting.db"),
        "integrity": integrity,
        "foreign_keys": foreign_keys == 1,
        "journal_mode": journal_mode,
        "table_count": len(tables),
        "fts5": fts_available,
    }


@contextmanager
def local_session_scope(settings: Settings | None = None) -> Generator[Session]:
    config = settings or get_settings()
    upgrade_local(config)
    engine = get_local_engine(config)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()
