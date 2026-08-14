"""Small, explicit refresh scheduling primitives with failure backoff."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant_recruiting.db.models import RefreshTarget

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017


def is_due(target: RefreshTarget, now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC)
    return (target.status or "active") == "active" and (
        target.next_due_at is None or target.next_due_at <= current
    )


def next_due_at(target: RefreshTarget, now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    backoff = min(2**target.failure_count, 8)
    return current + timedelta(seconds=target.cadence_seconds * backoff)


def record_success(target: RefreshTarget, now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    target.last_attempted_at = current
    target.last_successful_at = current
    target.next_due_at = current + timedelta(seconds=target.cadence_seconds)
    target.failure_count = 0
    target.last_error = None


def record_failure(target: RefreshTarget, error: str, now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    target.last_attempted_at = current
    target.failure_count = (target.failure_count or 0) + 1
    target.last_error = error
    target.next_due_at = next_due_at(target, current)
