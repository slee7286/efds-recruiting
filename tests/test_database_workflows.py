import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from quant_recruiting.ai_queue import prepare_company_task
from quant_recruiting.application_service import record_application_event
from quant_recruiting.company_service import add_company_alias, add_company_domain, resolve_company
from quant_recruiting.config import Settings
from quant_recruiting.db.base import Base
from quant_recruiting.db.models import Application, Company, Job, ResearchDocument
from quant_recruiting.db.seed import seed_skills
from quant_recruiting.ingestion.web import DiscoveredSource, FetchedSource, persist_fetched_source
from quant_recruiting.research_export import export_company

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="requires an isolated PostgreSQL test database",
)


def test_database_workflows_require_postgres(tmp_path) -> None:
    """Exercise persistence, versioning, events, exports, AI manifests, and seeding."""
    assert os.environ["TEST_DATABASE_URL"].startswith("postgresql")
    schema = f"qr_test_{uuid4().hex[:12]}"
    admin_engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        os.environ["TEST_DATABASE_URL"],
        connect_args={"options": f"-c search_path={schema}"},
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            company = Company(name="Test Firm", slug="test-firm")
            session.add(company)
            session.flush()
            add_company_alias(session, company, "Test Firm Capital")
            add_company_domain(session, company, "example.test", domain_type="corporate")
            assert resolve_company(session, "test-firm").id == company.id
            assert resolve_company(session, "Test Firm Capital").id == company.id
            assert resolve_company(session, "example.test").id == company.id
            now = datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 local verification compatibility
            job = Job(
                company=company,
                title="Quant Intern",
                role_family="quantitative_research",
                job_url="https://example.test/job",
                source_type="manual",
                date_first_seen=now,
                date_last_seen=now,
            )
            session.add(job)
            session.flush()
            settings = Settings(data_dir=tmp_path / "data", research_dir=tmp_path / "research")
            settings.ensure_directories()
            source = DiscoveredSource(
                "https://example.test/research?utm_source=test", "official_website"
            )
            first = FetchedSource(
                source,
                b"<html><title>Test</title><p>Alpha</p></html>",
                "text/html",
                200,
                now,
            )
            source_row, document_one, changed = persist_fetched_source(
                session, company, first, settings
            )
            assert changed is True
            _, identical, changed = persist_fetched_source(session, company, first, settings)
            assert changed is False
            assert identical.id == document_one.id
            second = FetchedSource(
                source,
                b"<html><title>Test</title><p>Beta</p></html>",
                "text/html",
                200,
                now,
            )
            _, document_two, changed = persist_fetched_source(session, company, second, settings)
            assert changed is True
            assert document_two.version == 2
            assert session.scalar(
                select(ResearchDocument).where(
                    ResearchDocument.source_id == source_row.id,
                    ResearchDocument.version == 1,
                )
            )
            application = Application(job=job)
            session.add(application)
            session.flush()
            event = record_application_event(
                session,
                application,
                event_type="status_change",
                source_type="test",
                new_status="shortlisted",
            )
            assert event.previous_status == "discovered"
            assert application.status == "shortlisted"
            assert seed_skills(session) > 0
            assert seed_skills(session) == 0
            export_path = export_company(session, company, settings)
            source_export = next((settings.research_dir / company.slug / "sources").glob("*.md"))
            assert "source_id:" in source_export.read_text(encoding="utf-8")
            task = prepare_company_task(session, company, settings)
            assert task.input_manifest_path is not None
            assert (settings.data_dir / "ai_queue" / str(task.id) / "manifest.json").exists()
            assert export_path.exists()
            session.commit()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
