"""Provider-neutral local ICS export for interview appointments."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from quant_recruiting.config import Settings, get_settings
from quant_recruiting.db.models import Application
from quant_recruiting.local_models import LocalInterviewAppointment
from quant_recruiting.storage import get_local_session

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def export_interview_ics(interview_id: UUID, settings: Settings | None = None) -> Path:
    config = settings or get_settings()
    with get_local_session(config) as session:
        appointment = session.get(LocalInterviewAppointment, interview_id)
        if appointment is None:
            raise ValueError("interview appointment not found locally")
        application = session.get(Application, appointment.application_id)
        if application is None:
            raise ValueError("application for interview appointment not found")
        company = application.job.company.name
        role = application.job.title
        start = appointment.starts_at
        end = appointment.ends_at or (start + timedelta(minutes=60))
        uid = f"{appointment.id}@recruiting-assistant.local"
        summary = f"{company} — {role} — {appointment.interview_stage}"
        description = "\n".join(
            item
            for item in (
                f"Company: {company}",
                f"Role: {role}",
                f"Stage: {appointment.interview_stage}",
                appointment.meeting_url or "",
                appointment.notes or "",
            )
            if item
        )
        content = "\r\n".join(
            (
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//Recruiting Assistant//Interview//EN",
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{_ics_datetime(datetime.now(UTC))}",
                f"DTSTART:{_ics_datetime(start)}",
                f"DTEND:{_ics_datetime(end)}",
                f"SUMMARY:{_ics_escape(summary)}",
                f"DESCRIPTION:{_ics_escape(description)}",
                f"LOCATION:{_ics_escape(appointment.location or '')}",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            )
        )
        output_dir = config.local_data_dir / "exports" / "calendar"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"interview-{interview_id}.ics"
        path.write_text(content, encoding="utf-8", newline="")
        return path
