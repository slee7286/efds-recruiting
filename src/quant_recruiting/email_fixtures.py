"""Explicit, local-only sanitized recruiting-email fixture capture."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from uuid import UUID

from sqlalchemy import or_, select

from quant_recruiting.config import Settings, get_settings
from quant_recruiting.local_models import LocalEmailMessage
from quant_recruiting.storage import get_local_session

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017


def _redact(value: str | None) -> str:
    text = value or ""
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "person@example.invalid", text)
    text = re.sub(r"\+?\d[\d ()-]{7,}\d", "[PHONE REDACTED]", text)
    text = re.sub(
        r"https?://[^\s<>]+",
        lambda match: "https://example.invalid/redacted-link",
        text,
    )
    return text


def capture_email_fixture(message_id: str, settings: Settings | None = None) -> dict[str, object]:
    config = settings or get_settings()
    with get_local_session(config) as session:
        try:
            parsed_id = UUID(message_id)
        except ValueError:
            parsed_id = None
        query = select(LocalEmailMessage)
        if parsed_id:
            query = query.where(LocalEmailMessage.id == parsed_id)
        else:
            query = query.where(
                or_(
                    LocalEmailMessage.provider_message_id == message_id,
                    LocalEmailMessage.message_id_header == message_id,
                )
            )
        message = session.scalar(query)
        if message is None:
            raise ValueError(f"local email message not found: {message_id}")
        body = _redact(message.text_body)
        subject = _redact(message.subject)
        sender = "Recruiting <recruiter@example.invalid>"
        raw = EmailMessage()
        raw["From"] = sender
        raw["To"] = "Candidate <person@example.invalid>"
        raw["Subject"] = subject
        raw["Date"] = (message.sent_at or datetime.now(UTC)).isoformat()
        raw["Message-ID"] = "<fixture@example.invalid>"
        raw.set_content(body)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    destination = config.local_data_dir / "cache" / "email-fixtures"
    destination.mkdir(parents=True, exist_ok=True)
    stem = f"email-{message.id}-{digest}"
    eml_path = destination / f"{stem}.eml"
    metadata_path = destination / f"{stem}.json"
    eml_path.write_bytes(raw.as_bytes())
    metadata = {
        "fixture_schema_version": 1,
        "source_kind": "local_sanitized",
        "contains_private_data": False,
        "original_local_message_id": str(message.id),
        "provider": message.provider,
        "classification": (message.metadata_ or {}).get("classification"),
        "captured_at": datetime.now(UTC).isoformat(),
        "redactions": ["email addresses", "phone numbers", "URLs", "message ID"],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"eml": str(eml_path), "metadata": str(metadata_path), **metadata}
