from datetime import datetime, timezone

from sqlalchemy.orm import Session

from quant_recruiting.db.models import Application, ApplicationEvent

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017 - Python 3.10 local verification compatibility


def record_application_event(
    session: Session,
    application: Application,
    *,
    event_type: str,
    source_type: str,
    new_status: str | None = None,
    notes: str | None = None,
    source_reference: str | None = None,
) -> ApplicationEvent:
    event = ApplicationEvent(
        application=application,
        event_type=event_type,
        previous_status=application.status,
        new_status=new_status,
        occurred_at=datetime.now(UTC),
        source_type=source_type,
        source_reference=source_reference,
        notes=notes,
    )
    if new_status:
        application.status = new_status
        application.last_action_at = event.occurred_at
    session.add(event)
    session.flush()
    return event
