from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from quant_recruiting.ai_workspace import import_conversations, search_conversations
from quant_recruiting.config import Settings
from quant_recruiting.db.base import Base
from quant_recruiting.db.models import CandidateEvidence, CandidateExperience, Company, Job
from quant_recruiting.local_db import local_diagnostics
from quant_recruiting.local_ops import backup_local, restore_local
from quant_recruiting.storage import get_local_session
from quant_recruiting.sync import pull_shared, sync_status


def _settings(root: Path, shared: Path | None = None) -> Settings:
    return Settings(
        local_data_dir=root / "local",
        shared_database_url=f"sqlite:///{shared}" if shared else None,
        shared_transport="postgres",
        shared_enabled=shared is not None,
    )


def test_local_sqlite_integrity_wal_foreign_keys_and_fts() -> None:
    with TemporaryDirectory() as directory:
        diagnostics = local_diagnostics(_settings(Path(directory)))
        assert diagnostics["integrity"] == "ok"
        assert diagnostics["foreign_keys"] is True
        assert diagnostics["journal_mode"] == "wal"
        assert diagnostics["fts5"] is True


def test_shared_pull_materializes_cache_and_is_incremental() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        shared_path = root / "shared.db"
        shared_engine = create_engine(f"sqlite:///{shared_path}")
        Base.metadata.create_all(shared_engine)
        with sessionmaker(bind=shared_engine).begin() as session:
            company = Company(slug="example", name="Example")
            session.add(company)
            session.flush()
            now = datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 compatibility
            session.add(
                Job(
                    company_id=company.id,
                    title="Software Engineer Intern",
                    role_family="software_engineering",
                    job_url="https://example.test/job",
                    source_type="fixture",
                    date_first_seen=now,
                    date_last_seen=now,
                    status="open",
                )
            )
        settings = _settings(root, shared_path)
        first = pull_shared(settings)
        second = pull_shared(settings)
        assert first["found"] == 2
        assert first["changed"] == 2
        assert second["changed"] == 0
        assert len(sync_status(settings)) == 2
        with get_local_session(settings) as local:
            assert local.query(Company).count() == 1
            assert local.query(Job).count() == 1
        shared_engine.dispose()


def test_private_candidate_data_works_without_shared_database() -> None:
    with TemporaryDirectory() as directory:
        settings = _settings(Path(directory))
        assert settings.auto_push_private is False
        with get_local_session(settings) as session:
            experience = CandidateExperience(
                experience_type="project", organization="Local", title="Private project"
            )
            session.add(experience)
            session.flush()
            session.add(
                CandidateEvidence(
                    experience_id=experience.id,
                    evidence_type="achievement",
                    statement="Private evidence",
                    confidence=1.0,
                    approved_for_application=True,
                )
            )
        with get_local_session(settings) as session:
            assert session.query(CandidateEvidence).count() == 1


def test_conversation_import_deduplicates_and_searches_locally() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        export = root / "conversations.json"
        export.write_text(
            json.dumps(
                [
                    {
                        "conversation_id": "conversation-1",
                        "title": "Local application",
                        "mapping": {
                            "1": {
                                "message": {
                                    "author": {"role": "user"},
                                    "content": {"parts": ["Private context"]},
                                }
                            },
                            "2": {
                                "message": {
                                    "author": {"role": "assistant"},
                                    "content": {"parts": ["Draft answer"]},
                                }
                            },
                        },
                    }
                ]
            ),
            encoding="utf-8",
        )
        settings = _settings(root)
        assert import_conversations("chatgpt", export, settings)["new"] == 1
        assert import_conversations("chatgpt", export, settings)["duplicates"] == 1
        assert search_conversations("Draft", settings)[0]["title"] == "Local application"


def test_backup_restore_preserves_private_database() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        settings = _settings(root)
        with get_local_session(settings) as session:
            session.add(
                CandidateExperience(
                    experience_type="education", organization="Local", title="Degree"
                )
            )
        backup = backup_local(settings, destination=root / "backup.zip")
        restored = restore_local(backup, settings, destination=root / "restored")
        assert (restored / "recruiting.db").exists()
        restored_settings = Settings(local_data_dir=restored, shared_enabled=False)
        with get_local_session(restored_settings) as session:
            assert session.query(CandidateExperience).count() == 1


def test_restore_rejects_unsafe_archive_paths() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        backup = root / "unsafe.zip"
        with zipfile.ZipFile(backup, "w") as archive:
            archive.writestr(
                "recruiting-assistant/backup-manifest.json",
                json.dumps(
                    {
                        "version": 1,
                        "files": [{"path": "../outside.txt", "sha256": "unused"}],
                    }
                ),
            )
            archive.writestr("recruiting-assistant/../outside.txt", "unsafe")
        try:
            restore_local(backup, _settings(root), destination=root / "restored")
        except ValueError as error:
            assert "unsafe backup path" in str(error)
        else:
            raise AssertionError("unsafe archive path was accepted")
        assert not (root / "restored").exists()
