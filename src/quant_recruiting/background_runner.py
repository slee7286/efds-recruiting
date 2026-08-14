"""Safe, local-only background operations.

This runner deliberately does not open browsers, send email, or call an AI
provider. Every task is bounded and recorded in the local database.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from quant_recruiting.config import Settings, get_settings
from quant_recruiting.db.models import Application, Job
from quant_recruiting.local_models import (
    LocalBackgroundRun,
    LocalBackgroundTaskResult,
    LocalJobAlertMatch,
    LocalJobAlertRule,
    LocalNotification,
)
from quant_recruiting.recruiting_operations import deliver_due_reminders
from quant_recruiting.storage import get_local_session
from quant_recruiting.sync import pull_shared, refresh_job_freshness

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017


class BackgroundAlreadyRunning(RuntimeError):
    """Another local background execution owns the lock."""


class _LocalLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> _LocalLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.handle = self.path.open("x", encoding="utf-8")
            self.handle.write(f"pid={os.getpid()}\n")
            self.handle.flush()
        except FileExistsError as exc:
            raise BackgroundAlreadyRunning("a background run is already active") from exc
        return self

    def __exit__(self, *_: object) -> None:
        if self.handle is not None:
            self.handle.close()
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _result(
    session: Any,
    run: LocalBackgroundRun,
    task_type: str,
    status: str,
    count: int = 0,
    error: str | None = None,
    **metadata: Any,
) -> None:
    session.add(
        LocalBackgroundTaskResult(
            run_id=run.id,
            task_type=task_type,
            status=status,
            count=count,
            error_summary=error,
            metadata_=metadata,
        )
    )


def _job_matches(job: Job, filters: dict[str, Any]) -> bool:
    def values(key: str) -> list[str]:
        value = filters.get(key, [])
        if isinstance(value, str):
            return [value.lower()]
        return [str(item).lower() for item in value] if isinstance(value, list) else []

    company_values = values("companies") or values("company")
    if company_values and not any(
        value in {job.company.name.lower(), job.company.slug.lower()} for value in company_values
    ):
        return False
    role_values = values("role_families") or values("role_family")
    if role_values and job.role_family.lower() not in role_values:
        return False
    locations = values("locations") or values("location")
    location = f"{job.location_text or ''} {job.city or ''} {job.country or ''}".lower()
    if locations and not any(value in location for value in locations):
        return False
    cycles = values("cycles") or values("cycle")
    if cycles and (job.internship_cycle or "").lower() not in cycles:
        return False
    keywords = values("keywords") or values("keyword")
    text = f"{job.title} {job.description_text or ''} {job.requirements_text or ''}".lower()
    return not keywords or all(keyword in text for keyword in keywords)


def evaluate_job_alerts(settings: Settings | None = None) -> dict[str, int]:
    config = settings or get_settings()
    with get_local_session(config) as session:
        rules = list(
            session.scalars(select(LocalJobAlertRule).where(LocalJobAlertRule.enabled.is_(True)))
        )
        jobs = list(session.scalars(select(Job).where(Job.status.in_(["open", "discovered"]))))
        matches = 0
        notifications = 0
        for rule in rules:
            for job in jobs:
                if not _job_matches(job, rule.filters):
                    continue
                existing = session.scalar(
                    select(LocalJobAlertMatch).where(
                        LocalJobAlertMatch.rule_id == rule.id,
                        LocalJobAlertMatch.shared_job_id == str(job.id),
                    )
                )
                if existing:
                    continue
                notification = LocalNotification(
                    notification_type="job_alert",
                    title="New matching job",
                    body=f"{job.company.name} — {job.title}",
                    entity_type="job",
                    entity_id=str(job.id),
                    priority=rule.metadata_.get("priority", 0),
                )
                session.add(notification)
                session.flush()
                session.add(
                    LocalJobAlertMatch(
                        rule_id=rule.id,
                        shared_job_id=str(job.id),
                        matched_at=datetime.now(UTC),
                        notification_id=notification.id,
                    )
                )
                matches += 1
                notifications += 1
        return {"matches": matches, "notifications": notifications}


def run_once(settings: Settings | None = None, *, trigger: str = "manual") -> dict[str, Any]:
    config = settings or get_settings()
    lock = _LocalLock(config.local_data_dir / "cache" / "background-run.lock")
    with lock:
        started = datetime.now(UTC)
        with get_local_session(config) as session:
            run = LocalBackgroundRun(started_at=started, trigger=trigger, status="running")
            session.add(run)
            session.flush()
        summary: dict[str, Any] = {"run_id": str(run.id), "tasks": {}}
        try:
            # Gmail OAuth is intentionally not guessed. A configured provider can
            # be wired by the local email service; otherwise the run records a
            # clear no-op instead of pretending that a mailbox was checked.
            summary["tasks"]["email_sync"] = {
                "status": "skipped",
                "reason": "no local OAuth provider configured"
                if config.background_email_sync
                else "disabled",
            }
            with get_local_session(config) as session:
                current = session.get(LocalBackgroundRun, run.id)
                if current:
                    _result(
                        session, current, "email_sync", "skipped", metadata="oauth_not_configured"
                    )
            shared_available = bool(
                config.shared_transport == "postgres" and config.shared_database_url
            ) or bool(config.shared_transport == "api" and config.shared_api_url)
            if (
                config.background_shared_sync
                and config.shared_enabled
                and not config.offline_mode
                and shared_available
            ):
                try:
                    result = pull_shared(config)
                    summary["tasks"]["shared_sync"] = result
                    with get_local_session(config) as session:
                        current = session.get(LocalBackgroundRun, run.id)
                        if current:
                            _result(
                                session,
                                current,
                                "shared_sync",
                                "completed",
                                int(result.get("changed", 0)),
                            )
                except Exception as exc:  # noqa: BLE001 - retained as local run history
                    summary["tasks"]["shared_sync"] = {"status": "failed", "error": str(exc)}
                    with get_local_session(config) as session:
                        current = session.get(LocalBackgroundRun, run.id)
                        if current:
                            _result(session, current, "shared_sync", "failed", error=str(exc))
            else:
                summary["tasks"]["shared_sync"] = {
                    "status": "skipped",
                    "reason": "offline, disabled, or not configured",
                }
            reminders: dict[str, Any] = (
                deliver_due_reminders(config)
                if config.background_reminders
                else {"due": 0, "delivered": 0, "status": "disabled"}
            )
            summary["tasks"]["reminders"] = reminders
            alerts: dict[str, Any] = (
                evaluate_job_alerts(config)
                if config.background_job_alerts
                else {"matches": 0, "notifications": 0, "status": "disabled"}
            )
            summary["tasks"]["job_alerts"] = alerts
            refreshed = 0
            if config.background_active_job_refresh:
                with get_local_session(config) as session:
                    applications = list(
                        session.scalars(
                            select(Application).where(
                                Application.status.not_in(["rejected", "withdrawn", "offer"])
                            )
                        )
                    )
                for application in applications:
                    try:
                        result = refresh_job_freshness(application.id, config)
                        refreshed += int(bool(result.get("refreshed")))
                    except Exception:
                        continue
            summary["tasks"]["active_job_refresh"] = {"refreshed": refreshed}
            with get_local_session(config) as session:
                current = session.get(LocalBackgroundRun, run.id)
                if current:
                    current.status = "completed"
                    current.completed_at = datetime.now(UTC)
                    current.metadata_ = {"summary": summary}
                    _result(
                        session,
                        current,
                        "reminders",
                        "completed",
                        int(reminders.get("delivered", 0)),
                    )
                    _result(
                        session, current, "job_alerts", "completed", int(alerts.get("matches", 0))
                    )
                    _result(session, current, "active_job_refresh", "completed", refreshed)
        except Exception as exc:
            with get_local_session(config) as session:
                current = session.get(LocalBackgroundRun, run.id)
                if current:
                    current.status = "failed"
                    current.completed_at = datetime.now(UTC)
                    current.error_summary = str(exc)
            raise
        return summary


def add_job_alert_rule(
    name: str, filters: dict[str, Any], settings: Settings | None = None
) -> dict[str, Any]:
    config = settings or get_settings()
    with get_local_session(config) as session:
        rule = LocalJobAlertRule(name=name, filters=filters, enabled=True)
        session.add(rule)
        session.flush()
        return {"id": str(rule.id), "name": rule.name, "filters": rule.filters}


def list_job_alert_rules(settings: Settings | None = None) -> list[dict[str, Any]]:
    with get_local_session(settings or get_settings()) as session:
        return [
            {
                "id": str(rule.id),
                "name": rule.name,
                "enabled": rule.enabled,
                "filters": rule.filters,
            }
            for rule in session.scalars(
                select(LocalJobAlertRule).order_by(LocalJobAlertRule.created_at)
            )
        ]
