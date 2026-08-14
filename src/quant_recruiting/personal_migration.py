"""Non-destructive migration from legacy shared private rows into SQLite."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from quant_recruiting.config import Settings, get_settings
from quant_recruiting.db import models as _models  # noqa: F401 - register ORM tables
from quant_recruiting.db.base import Base
from quant_recruiting.local_db import upgrade_local
from quant_recruiting.storage import get_local_session, get_shared_session

PRIVATE_TABLES = [
    "candidate_profiles",
    "candidate_sensitive_fields",
    "candidate_experiences",
    "candidate_evidence",
    "candidate_evidence_skills",
    "candidate_stories",
    "candidate_story_evidence",
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
]
REFERENCE_TABLES = ["companies", "jobs"]
PATH_COLUMNS = {"source_path", "rendered_path", "raw_path", "normalized_path", "markdown_path"}


def _copy_private_path(value: Any, settings: Settings) -> Any:
    if not isinstance(value, str):
        return value
    source = Path(value)
    if not source.exists() or not source.is_file():
        return value
    destination = settings.local_data_dir / "migrated-files" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source, destination)
    return str(destination)


def migrate_personal_to_local(
    settings: Settings | None = None, *, dry_run: bool = False
) -> dict[str, Any]:
    config = settings or get_settings()
    upgrade_local(config)
    counts: dict[str, int] = {}
    with get_shared_session(config) as shared:
        rows_by_table: dict[str, list[dict[str, Any]]] = {}
        for name in [*REFERENCE_TABLES, *PRIVATE_TABLES]:
            table = Base.metadata.tables[name]
            rows = []
            for row in shared.execute(select(table)).mappings():
                values = dict(row)
                for column in PATH_COLUMNS & values.keys():
                    values[column] = _copy_private_path(values[column], config)
                rows.append(values)
            rows_by_table[name] = rows
            counts[name] = len(rows)
    if dry_run:
        return {"dry_run": True, "counts": counts, "copied": 0}
    copied = 0
    with get_local_session(config) as local:
        for name in [*REFERENCE_TABLES, *PRIVATE_TABLES]:
            table = Base.metadata.tables[name]
            for values in rows_by_table[name]:
                primary_keys = [column.name for column in table.primary_key.columns]
                predicate = [table.c[key] == values[key] for key in primary_keys]
                exists = local.execute(select(table).where(*predicate)).first()
                if exists:
                    local.execute(update(table).where(*predicate).values(**values))
                else:
                    local.execute(table.insert().values(**values))
                copied += 1
    return {"dry_run": False, "counts": counts, "copied": copied}
