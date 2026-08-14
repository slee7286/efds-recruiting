"""Local recruiting operations derived from email and existing intelligence."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.application_service import record_application_event
from quant_recruiting.config import Settings, get_settings
from quant_recruiting.db.models import (
    Application,
    InterviewQuestion,
    InterviewQuestionSkill,
    Resource,
    Skill,
)
from quant_recruiting.email_ingestion import ASSESSMENT_PROVIDERS, _parse_date
from quant_recruiting.local_models import (
    LocalAssessment,
    LocalEmailExtraction,
    LocalEmailLink,
    LocalEmailMessage,
    LocalInterviewAppointment,
    LocalNotification,
    LocalPrepPlan,
    LocalPrepPlanItem,
    LocalRecruitingAction,
    LocalReminder,
    LocalTimelineEvent,
)
from quant_recruiting.notifications import notify_locally
from quant_recruiting.storage import get_local_session

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017

STATUS_BY_CLASSIFICATION = {
    "application_confirmation": "applied",
    "online_assessment": "oa",
    "coding_assessment": "oa",
    "psychometric_assessment": "oa",
    "hirevue": "oa",
    "interview_invitation": "interview",
    "interview_confirmation": "interview",
    "interview_reschedule": "interview",
    "rejection": "rejected",
    "offer": "offer",
    "withdrawal_confirmation": "withdrawn",
}

EVENT_BY_CLASSIFICATION = {
    "application_confirmation": "application_confirmed",
    "online_assessment": "assessment_received",
    "coding_assessment": "assessment_received",
    "psychometric_assessment": "assessment_received",
    "hirevue": "assessment_received",
    "interview_invitation": "interview_invited",
    "interview_confirmation": "interview_scheduled",
    "interview_reschedule": "interview_rescheduled",
    "rejection": "rejection",
    "offer": "offer",
    "withdrawal_confirmation": "withdrawal",
}


def _message_link(session: Session, message_id: UUID) -> LocalEmailLink | None:
    return session.scalar(
        select(LocalEmailLink)
        .where(LocalEmailLink.message_id == message_id)
        .order_by(LocalEmailLink.approved.desc(), LocalEmailLink.confidence.desc())
    )


def _classification(message: LocalEmailMessage) -> str:
    return str(message.metadata_.get("classification", "other_recruiting"))


def _deadline(message_id: UUID, session: Session) -> datetime | None:
    rows = list(
        session.scalars(
            select(LocalEmailExtraction).where(
                LocalEmailExtraction.message_id == message_id,
                LocalEmailExtraction.extraction_type == "deadline",
            )
        )
    )
    for row in rows:
        value = row.value.get("calculated")
        if value:
            try:
                parsed = datetime.fromisoformat(str(value))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                continue
    return None


def _assessment_provider(text: str) -> str:
    lower = text.lower()
    for key, (_, domain) in ASSESSMENT_PROVIDERS.items():
        if key.replace("_", " ") in lower or (domain and domain in lower):
            return key
    return "company_custom" if "assessment" in lower else "other"


def _assessment_for_message(
    session: Session, message: LocalEmailMessage, application: Application
) -> LocalAssessment | None:
    classification = _classification(message)
    if classification not in {
        "online_assessment",
        "coding_assessment",
        "psychometric_assessment",
        "hirevue",
    }:
        return None
    existing = session.scalar(
        select(LocalAssessment).where(LocalAssessment.source_email_id == message.id)
    )
    if existing:
        return existing
    link = next(
        (
            extraction
            for extraction in session.scalars(
                select(LocalEmailExtraction).where(LocalEmailExtraction.message_id == message.id)
            )
            if extraction.extraction_type == "assessment_link"
        ),
        None,
    )
    value = link.value if link else {}
    assessment = LocalAssessment(
        application_id=application.id,
        assessment_type=classification,
        provider=str(value.get("provider") or _assessment_provider(message.text_body or "")),
        received_at=message.sent_at or message.received_at,
        due_at=_deadline(message.id, session),
        url=value.get("url"),
        source_email_id=message.id,
        status="received",
    )
    session.add(assessment)
    session.flush()
    return assessment


def _interview_datetime(message: LocalEmailMessage) -> tuple[datetime | None, str, str]:
    text = message.text_body or ""
    reference = message.sent_at or message.received_at or datetime.now(UTC)
    date_match = re.search(
        r"(?:[A-Z][a-z]{2,8}\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
        text,
    )
    time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\s*([A-Z]{2,4})?\b", text, re.I)
    if not date_match or not time_match:
        return None, "needs_review", "date/time not both explicit"
    date_value = _parse_date(re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", date_match.group(0)), reference)
    if date_value is None:
        return None, "needs_review", "date could not be parsed"
    hour = int(time_match.group(1))
    if time_match.group(3).upper() == "PM" and hour != 12:
        hour += 12
    if time_match.group(3).upper() == "AM" and hour == 12:
        hour = 0
    minute = int(time_match.group(2) or 0)
    zone_abbr = time_match.group(4)
    zone_map = {
        "ET": "America/New_York",
        "EST": "America/New_York",
        "EDT": "America/New_York",
        "PT": "America/Los_Angeles",
        "PST": "America/Los_Angeles",
        "PDT": "America/Los_Angeles",
        "CT": "America/Chicago",
        "CET": "Europe/Paris",
        "GMT": "Etc/GMT",
        "UTC": "UTC",
    }
    zone_name = zone_map.get(zone_abbr.upper()) if zone_abbr else None
    if zone_name:
        tz = ZoneInfo(zone_name)
        return (
            datetime(date_value.year, date_value.month, date_value.day, hour, minute, tzinfo=tz),
            zone_name,
            "explicit_date_time_timezone",
        )
    return (
        datetime(date_value.year, date_value.month, date_value.day, hour, minute, tzinfo=UTC),
        "needs_review",
        "explicit_date_time_ambiguous_timezone",
    )


def _interview_for_message(
    session: Session, message: LocalEmailMessage, application: Application
) -> LocalInterviewAppointment | None:
    classification = _classification(message)
    if classification not in {
        "interview_invitation",
        "interview_confirmation",
        "interview_reschedule",
    }:
        return None
    existing = session.scalar(
        select(LocalInterviewAppointment).where(
            LocalInterviewAppointment.source_email_id == message.id
        )
    )
    if existing:
        return existing
    starts_at, zone_name, method = _interview_datetime(message)
    if starts_at is None:
        return None
    url_match = re.search(r"https?://[^\s<>\]\)]+", message.text_body or "")
    appointment = LocalInterviewAppointment(
        application_id=application.id,
        interview_stage="interview",
        starts_at=starts_at,
        timezone_name=zone_name,
        meeting_url=url_match.group(0) if url_match else None,
        source_email_id=message.id,
        confirmation_status="confirmed"
        if zone_name != "needs_review" and classification == "interview_confirmation"
        else "needs_review",
        metadata_={"extraction_method": method, "original_text": (message.text_body or "")[:1000]},
    )
    session.add(appointment)
    session.flush()
    return appointment


def _timeline_once(
    session: Session,
    application_id: UUID | None,
    event_type: str,
    source_id: str,
    *,
    occurred_at: datetime | None,
    deadline_at: datetime | None,
    title: str,
    metadata: dict[str, Any] | None = None,
) -> LocalTimelineEvent:
    existing = session.scalar(
        select(LocalTimelineEvent).where(
            LocalTimelineEvent.source_type == "email",
            LocalTimelineEvent.source_id == source_id,
            LocalTimelineEvent.event_type == event_type,
        )
    )
    if existing:
        return existing
    event = LocalTimelineEvent(
        application_id=application_id,
        event_type=event_type,
        occurred_at=occurred_at,
        deadline_at=deadline_at,
        status="observed",
        source_type="email",
        source_id=source_id,
        title=title,
        metadata_=metadata or {},
    )
    session.add(event)
    session.flush()
    return event


def _action_once(
    session: Session,
    application_id: UUID,
    title: str,
    action_type: str,
    source_id: str,
    *,
    due_at: datetime | None,
    priority: int = 0,
) -> LocalRecruitingAction:
    existing = session.scalar(
        select(LocalRecruitingAction).where(
            LocalRecruitingAction.source_type == "email",
            LocalRecruitingAction.source_id == source_id,
            LocalRecruitingAction.action_type == action_type,
        )
    )
    if existing:
        return existing
    action = LocalRecruitingAction(
        application_id=application_id,
        title=title,
        action_type=action_type,
        due_at=due_at,
        status="open",
        priority=priority,
        source_type="email",
        source_id=source_id,
    )
    session.add(action)
    session.flush()
    return action


def _reminder_once(
    session: Session, action: LocalRecruitingAction, remind_at: datetime
) -> LocalReminder:
    existing = session.scalar(
        select(LocalReminder).where(
            LocalReminder.action_id == action.id, LocalReminder.remind_at == remind_at
        )
    )
    if existing:
        return existing
    reminder = LocalReminder(
        action_id=action.id, remind_at=remind_at, status="pending", delivery_method="dashboard"
    )
    session.add(reminder)
    session.flush()
    return reminder


def _schedule_offsets(
    session: Session,
    action: LocalRecruitingAction,
    due_at: datetime,
    offsets: list[timedelta],
) -> None:
    for offset in offsets:
        remind_at = due_at - offset
        if remind_at > due_at:
            continue
        _reminder_once(session, action, remind_at)


def process_email_message(message_id: UUID, settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    with get_local_session(config) as session:
        message = session.get(LocalEmailMessage, message_id)
        if message is None:
            raise ValueError("email message not found locally")
        link = _message_link(session, message_id)
        application = (
            session.get(Application, link.application_id) if link and link.application_id else None
        )
        classification = _classification(message)
        deadline = _deadline(message_id, session)
        event_type = EVENT_BY_CLASSIFICATION.get(classification)
        if event_type:
            _timeline_once(
                session,
                application.id if application else None,
                event_type,
                str(message.id),
                occurred_at=message.sent_at or message.received_at,
                deadline_at=deadline,
                title=classification.replace("_", " ").title(),
                metadata={"confidence": message.metadata_.get("classification_confidence", 0.0)},
            )
        status = STATUS_BY_CLASSIFICATION.get(classification)
        status_changed = False
        if (
            application
            and status
            and float(message.metadata_.get("classification_confidence", 0.0)) >= 0.8
            and application.status != status
        ):
            record_application_event(
                session,
                application,
                event_type=event_type or classification,
                source_type="email",
                source_reference=str(message.id),
                new_status=status,
                notes=f"Deterministic status suggestion from local email {message.id}",
            )
            status_changed = True
        assessment = _assessment_for_message(session, message, application) if application else None
        appointment = _interview_for_message(session, message, application) if application else None
        action = None
        if application and assessment:
            action = _action_once(
                session,
                application.id,
                f"Complete {assessment.provider} assessment",
                "complete_assessment",
                str(message.id),
                due_at=assessment.due_at,
                priority=10,
            )
            offsets = []
            if config.reminder_deadline_24h:
                offsets.append(timedelta(hours=24))
            if config.reminder_deadline_3h:
                offsets.append(timedelta(hours=3))
            if assessment.due_at:
                _schedule_offsets(session, action, assessment.due_at, offsets)
        elif application and appointment:
            action = _action_once(
                session,
                application.id,
                "Prepare for interview",
                "prepare_interview",
                str(message.id),
                due_at=appointment.starts_at - timedelta(hours=24),
                priority=10,
            )
            offsets = []
            if config.reminder_interview_24h:
                offsets.append(timedelta(hours=24))
            if config.reminder_interview_1h:
                offsets.append(timedelta(hours=1))
            if appointment.confirmation_status == "confirmed":
                _schedule_offsets(session, action, appointment.starts_at, offsets)
        elif application and classification == "request_for_information":
            action = _action_once(
                session,
                application.id,
                "Provide requested application information",
                "provide_information",
                str(message.id),
                due_at=deadline,
                priority=10,
            )
        if action and action.due_at and not (assessment or appointment):
            _reminder_once(session, action, action.due_at - timedelta(hours=24))
        message.metadata_ = {
            **message.metadata_,
            "processed_locally": True,
            "processed_at": datetime.now(UTC).isoformat(),
        }
        return {
            "message_id": str(message.id),
            "classification": classification,
            "application_id": str(application.id) if application else None,
            "status_changed": status_changed,
            "assessment_id": str(assessment.id) if assessment else None,
            "interview_id": str(appointment.id) if appointment else None,
            "action_id": str(action.id) if action else None,
        }


def build_prep_plan(
    application_id: UUID,
    settings: Settings | None = None,
    *,
    target: str = "application",
    target_id: UUID | None = None,
    daily_minutes: int = 120,
) -> dict[str, Any]:
    config = settings or get_settings()
    with get_local_session(config) as session:
        application = session.get(Application, application_id)
        if application is None:
            raise ValueError("application not found locally")
        plan = LocalPrepPlan(
            application_id=application.id,
            title=f"{application.job.company.name} — {application.job.title} preparation",
            status="draft",
            daily_minutes=daily_minutes,
            rationale=(
                "Deterministic plan ranked from role relevance, observed topics, "
                "candidate attempts, and deadline proximity."
            ),
        )
        if target == "assessment" and target_id:
            plan.assessment_id = target_id
        if target == "interview" and target_id:
            plan.interview_id = target_id
        session.add(plan)
        session.flush()
        query = (
            select(InterviewQuestion, Skill)
            .join(
                InterviewQuestionSkill, InterviewQuestionSkill.question_id == InterviewQuestion.id
            )
            .join(Skill, Skill.id == InterviewQuestionSkill.skill_id)
            .where(InterviewQuestion.company_id == application.job.company_id)
        )
        rows = list(session.execute(query))
        seen: set[UUID] = set()
        items = 0
        for question, skill in rows:
            if skill.id in seen:
                continue
            seen.add(skill.id)
            frequency = sum(
                1 for candidate_question, _ in rows if candidate_question.id == question.id
            )
            priority = min(100.0, 40.0 + frequency * 10.0)
            resource = session.scalar(
                select(Resource).where(Resource.title.ilike(f"%{skill.name}%")).limit(1)
            )
            session.add(
                LocalPrepPlanItem(
                    plan_id=plan.id,
                    skill_id=skill.id,
                    resource_id=resource.id if resource else None,
                    priority=priority,
                    estimated_minutes=min(60, max(15, daily_minutes // 4)),
                    rationale=(
                        f"Observed company interview evidence for {skill.name}; frequency is "
                        "within the collected corpus, not a probability."
                    ),
                )
            )
            items += 1
            if items >= 12:
                break
        return {
            "plan_id": str(plan.id),
            "application_id": str(application.id),
            "items": items,
            "daily_minutes": daily_minutes,
        }


def deliver_due_reminders(
    settings: Settings | None = None, *, now: datetime | None = None
) -> dict[str, int]:
    config = settings or get_settings()
    current = now or datetime.now(UTC)
    with get_local_session(config) as session:
        reminders = list(
            session.scalars(
                select(LocalReminder).where(
                    LocalReminder.status == "pending", LocalReminder.remind_at <= current
                )
            )
        )
        delivered = 0
        for reminder in reminders:
            reminder.status = "delivered"
            reminder.delivered_at = current
            action = (
                session.get(LocalRecruitingAction, reminder.action_id)
                if reminder.action_id
                else None
            )
            if action:
                desktop_delivered = notify_locally("Recruiting action due", action.title)
                session.add(
                    LocalNotification(
                        notification_type="deadline",
                        title="Recruiting action due",
                        body=action.title,
                        entity_type="action",
                        entity_id=str(action.id),
                        priority=action.priority,
                        metadata_={"desktop_delivered": desktop_delivered},
                    )
                )
            delivered += 1
        return {"due": len(reminders), "delivered": delivered}
