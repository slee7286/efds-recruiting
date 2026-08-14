from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from sqlalchemy import select

from quant_recruiting.calendar_export import export_interview_ics
from quant_recruiting.config import Settings
from quant_recruiting.db.models import Application, Company, Job
from quant_recruiting.email_ingestion import import_eml
from quant_recruiting.local_db import local_diagnostics
from quant_recruiting.local_models import (
    LocalAssessment,
    LocalEmailExtraction,
    LocalEmailMessage,
    LocalInterviewAppointment,
    LocalRecruitingAction,
    LocalReminder,
    LocalTimelineEvent,
)
from quant_recruiting.recruiting_operations import deliver_due_reminders
from quant_recruiting.storage import get_local_session
from quant_recruiting.sync import refresh_job_freshness

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017


def _settings(root: Path) -> Settings:
    return Settings(local_data_dir=root / "local", shared_enabled=False)


def _write_email(
    path: Path, subject: str, body: str, *, sender: str = "careers@example.test"
) -> None:
    path.write_text(
        "\n".join(
            (
                "From: Example Recruiting <" + sender + ">",
                "To: candidate@example.test",
                "Date: Tue, 18 Aug 2026 09:00:00 +0000",
                "Message-ID: <" + subject.replace(" ", "-").lower() + "@example.test>",
                "Subject: " + subject,
                "Content-Type: text/plain; charset=utf-8",
                "",
                body,
            )
        ),
        encoding="utf-8",
    )


def _application(settings: Settings) -> Application:
    with get_local_session(settings) as session:
        company = Company(slug="example-firm", name="Example Firm", primary_domain="example.test")
        session.add(company)
        session.flush()
        now = datetime.now(UTC)
        job = Job(
            company_id=company.id,
            title="Software Engineer Intern",
            role_family="software_engineering",
            job_url="https://example.test/jobs/swe",
            source_type="fixture",
            date_first_seen=now,
            date_last_seen=now,
            status="open",
        )
        session.add(job)
        session.flush()
        application = Application(job_id=job.id, application_url=job.job_url)
        session.add(application)
        session.flush()
        return application


def test_email_import_classifies_links_and_deduplicates() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        settings = _settings(root)
        application = _application(settings)
        email_path = root / "oa.eml"
        _write_email(
            email_path,
            "Example Firm online assessment invitation",
            "Thank you for applying to Example Firm for Software Engineer Intern. "
            "Please complete this online assessment within 72 hours: "
            "https://app.codesignal.com/test/example.",
        )
        first = import_eml(email_path, settings)
        second = import_eml(email_path, settings)
        assert first["duplicate"] is False
        assert second["duplicate"] is True
        with get_local_session(settings) as session:
            message = session.get(LocalEmailMessage, UUID(first["message_id"]))
            assert message is not None
            assert message.metadata_["classification"] == "online_assessment"
            assert first["application_id"] == str(application.id)
            assert session.query(LocalAssessment).count() == 1
            assessment = session.scalar(select(LocalAssessment))
            assert assessment is not None
            assert assessment.provider == "codesignal"
            assert assessment.due_at is not None
            assert session.query(LocalRecruitingAction).count() == 1
            assert session.query(LocalTimelineEvent).count() == 1
            assert session.query(LocalEmailExtraction).count() >= 2


def test_confirmation_and_rejection_status_events_are_local_and_conservative() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        settings = _settings(root)
        application = _application(settings)
        confirmation = root / "confirmation.eml"
        _write_email(
            confirmation,
            "Application received — Example Firm",
            "Thank you for applying to Example Firm for Software Engineer Intern. "
            "Your application has been received.",
        )
        confirmation_result = import_eml(confirmation, settings)
        assert confirmation_result["status_changed"] is True
        rejection = root / "rejection.eml"
        _write_email(
            rejection,
            "Example Firm application update",
            "We regret to inform you that we will not be progressing with your "
            "Software Engineer Intern application.",
            sender="talent@example.test",
        )
        rejection_result = import_eml(rejection, settings)
        assert rejection_result["status_changed"] is True
        with get_local_session(settings) as session:
            stored = session.get(Application, application.id)
            assert stored is not None
            assert stored.status == "rejected"
            assert len(stored.events) >= 2
            assert all(event.source_type == "email" for event in stored.events[-2:])


def test_interview_timezone_ambiguity_and_ics_export() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        settings = _settings(root)
        _application(settings)
        invite = root / "interview.eml"
        _write_email(
            invite,
            "Interview invitation — Example Firm",
            "We invite you to interview for Software Engineer Intern on August 20, 2026 "
            "at 2:00 PM ET. Join at https://meet.example.test/abc.",
        )
        result = import_eml(invite, settings)
        assert result["interview_id"]
        with get_local_session(settings) as session:
            appointment = session.get(LocalInterviewAppointment, UUID(result["interview_id"]))
            assert appointment is not None
            assert appointment.timezone_name == "America/New_York"
            assert appointment.confirmation_status == "needs_review"
            appointment.confirmation_status = "confirmed"
            interview_id = appointment.id
        ics = export_interview_ics(interview_id, settings)
        content = ics.read_text(encoding="utf-8")
        assert "BEGIN:VCALENDAR" in content
        assert "Example Firm" in content
        assert "meet.example.test" in content


def test_ambiguous_interview_time_is_not_silently_normalized() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        settings = _settings(root)
        _application(settings)
        invite = root / "ambiguous.eml"
        _write_email(
            invite,
            "Interview invitation — Example Firm",
            "We invite you to interview on August 20, 2026 at 2:00 PM. Please confirm.",
        )
        result = import_eml(invite, settings)
        with get_local_session(settings) as session:
            appointment = session.get(LocalInterviewAppointment, UUID(result["interview_id"]))
            assert appointment is not None
            assert appointment.timezone_name == "needs_review"
            assert appointment.confirmation_status == "needs_review"


def test_prep_plan_and_reminder_delivery_work_offline() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        settings = _settings(root)
        application = _application(settings)
        with get_local_session(settings) as session:
            action = LocalRecruitingAction(
                application_id=application.id,
                title="Complete assessment",
                action_type="complete_assessment",
                due_at=datetime.now(UTC) - timedelta(minutes=1),
                source_type="local_test",
                priority=10,
            )
            session.add(action)
            session.flush()
            session.add(
                LocalReminder(
                    action_id=action.id,
                    remind_at=datetime.now(UTC) - timedelta(minutes=1),
                    status="pending",
                    delivery_method="dashboard",
                )
            )
        delivery = deliver_due_reminders(settings)
        assert delivery["delivered"] == 1
        diagnostics = local_diagnostics(settings)
        assert diagnostics["integrity"] == "ok"
        assert diagnostics["journal_mode"] == "wal"


def test_job_freshness_reports_stale_offline_without_blocking_local_storage() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        settings = _settings(root).model_copy(update={"offline_mode": True})
        application = _application(settings)
        result = refresh_job_freshness(application.id, settings)
        assert result["stale"] is True
        assert result["offline"] is True
        assert result["refreshed"] is False
