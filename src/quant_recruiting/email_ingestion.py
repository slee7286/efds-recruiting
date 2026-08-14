"""Local recruiting-email ingestion, classification, linking, and extraction.

The module deliberately has no shared-database dependency. Gmail integration is a
provider boundary around a caller-supplied, OAuth-authenticated service object;
manual EML import is the fully testable provider-neutral path.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse
from uuid import UUID

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.config import Settings, get_settings
from quant_recruiting.db.models import Application, Company
from quant_recruiting.local_models import (
    LocalEmailAccount,
    LocalEmailAttachment,
    LocalEmailExtraction,
    LocalEmailLink,
    LocalEmailMessage,
    LocalEmailThread,
)
from quant_recruiting.storage import get_local_session

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017

ASSESSMENT_PROVIDERS = {
    "hackerrank": ("HackerRank", "hackerrank.com"),
    "codesignal": ("CodeSignal", "codesignal.com"),
    "codility": ("Codility", "codility.com"),
    "shl": ("SHL", "shl.com"),
    "hirevue": ("HireVue", "hirevue.com"),
    "testgorilla": ("TestGorilla", "testgorilla.com"),
    "pymetrics": ("Pymetrics", "pymetrics.com"),
    "arctic_shores": ("Arctic Shores", "arcticshores.com"),
    "company_custom": ("Company-hosted assessment", ""),
    "other": ("Other", ""),
}

# V12 deliberately requests no send, modify, delete, or archive permission.
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

CLASSIFICATION_RULES: dict[str, tuple[str, ...]] = {
    "application_confirmation": (
        "application has been received",
        "application received",
        "thanks for applying",
        "thank you for applying",
    ),
    "online_assessment": (
        "online assessment",
        "oa invitation",
        "assessment invitation",
        "complete the assessment",
    ),
    "coding_assessment": ("coding assessment", "coding challenge", "technical assessment"),
    "psychometric_assessment": (
        "psychometric",
        "numerical reasoning",
        "verbal reasoning",
        "logical reasoning",
    ),
    "hirevue": ("hirevue", "video interview", "on-demand interview", "video assessment"),
    "interview_invitation": (
        "invite you to interview",
        "interview invitation",
        "would like to interview",
        "schedule an interview",
    ),
    "interview_confirmation": (
        "interview is confirmed",
        "interview confirmation",
        "your interview is confirmed",
    ),
    "interview_reschedule": ("reschedule", "rescheduled", "change your interview time"),
    "request_for_information": (
        "please provide",
        "additional information",
        "right to work",
        "work authorization",
    ),
    "rejection": (
        "regret to inform",
        "not moving forward",
        "unsuccessful",
        "we will not be progressing",
        "rejected",
    ),
    "offer": ("pleased to offer", "offer of employment", "congratulations on your offer"),
    "withdrawal_confirmation": ("withdrawal confirmation", "application withdrawn"),
    "deadline_reminder": ("deadline", "due by", "complete within", "expires on"),
    "recruiter_outreach": (
        "recruiter",
        "talent acquisition",
        "career opportunity",
        "interested in your background",
    ),
}


class RecruitingEmailProvider(Protocol):
    """Provider-neutral read-only email interface."""

    provider: str

    def list_messages(
        self, *, cursor: str | None = None, query: str | None = None
    ) -> list[dict[str, Any]]: ...

    def get_message(self, message_id: str) -> dict[str, Any]: ...

    def get_thread(self, thread_id: str) -> list[dict[str, Any]]: ...


class GmailProvider:
    """Thin adapter around an OAuth-authenticated Gmail API service.

    The service is injected so the local application owns OAuth and secret storage,
    while this module remains testable without Gmail credentials or web scraping.
    """

    provider = "gmail"

    def __init__(self, service: Any) -> None:
        self.service = service

    def list_messages(
        self, *, cursor: str | None = None, query: str | None = None
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page_token = cursor
        for _ in range(20):
            response = (
                self.service.users()
                .messages()
                .list(userId="me", q=query or "", pageToken=page_token, maxResults=100)
                .execute()
            )
            results.extend(cast(list[dict[str, Any]], response.get("messages", [])))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return results

    def list_history_message_ids(self, history_id: str) -> list[str]:
        """Return message IDs added since a Gmail history ID."""
        ids: list[str] = []
        page_token: str | None = None
        for _ in range(20):
            response = (
                self.service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=history_id,
                    historyTypes=["messageAdded"],
                    pageToken=page_token,
                    maxResults=100,
                )
                .execute()
            )
            for record in response.get("history", []):
                for added in record.get("messagesAdded", []):
                    message_id = added.get("message", {}).get("id")
                    if message_id and message_id not in ids:
                        ids.append(str(message_id))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return ids

    def get_message(self, message_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.service.users().messages().get(userId="me", id=message_id, format="raw").execute(),
        )

    def get_thread(self, thread_id: str) -> list[dict[str, Any]]:
        response = (
            self.service.users().threads().get(userId="me", id=thread_id, format="raw").execute()
        )
        return cast(list[dict[str, Any]], response.get("messages", []))


@dataclass(frozen=True)
class EmailEnvelope:
    provider: str
    provider_message_id: str | None
    provider_thread_id: str | None
    message_id_header: str | None
    subject: str
    sender_name: str | None
    sender_email: str | None
    recipients: list[str]
    sent_at: datetime | None
    text_body: str
    html_body: str | None = None
    raw_bytes: bytes | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EmailClassification:
    classification: str
    confidence: float
    method: str
    reasons: list[str]


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _body_from_message(message: Message) -> tuple[str, str | None, list[dict[str, Any]]]:
    plain: list[str] = []
    html: str | None = None
    attachments: list[dict[str, Any]] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        raw_payload = part.get_payload(decode=True)
        payload = raw_payload if isinstance(raw_payload, bytes) else b""
        if filename or disposition == "attachment":
            attachments.append(
                {
                    "filename": filename or "attachment",
                    "media_type": part.get_content_type(),
                    "size_bytes": len(payload),
                }
            )
            continue
        content_type = part.get_content_type()
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if content_type == "text/html":
            html = text
            plain.append(BeautifulSoup(text, "html.parser").get_text(" "))
        elif content_type == "text/plain":
            plain.append(text)
    return _clean_text("\n".join(plain)), html, attachments


def parse_eml(path: Path, *, provider: str = "manual") -> EmailEnvelope:
    raw = path.read_bytes()
    message = BytesParser(policy=policy.default).parsebytes(raw)
    sender = getaddresses([message.get("From", "")])
    sender_name, sender_email = sender[0] if sender else (None, None)
    recipient_values = [email or name for name, email in getaddresses(message.get_all("To", []))]
    sent_at: datetime | None = None
    date_header = message.get("Date")
    if isinstance(date_header, str):
        try:
            sent_at = parsedate_to_datetime(date_header)
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=UTC)
            sent_at = sent_at.astimezone(UTC)
        except (TypeError, ValueError, IndexError):
            sent_at = None
    text, html, attachments = _body_from_message(message)
    return EmailEnvelope(
        provider=provider,
        provider_message_id=None,
        provider_thread_id=None,
        message_id_header=message.get("Message-ID"),
        subject=_clean_text(str(message.get("Subject", ""))),
        sender_name=sender_name or None,
        sender_email=sender_email or None,
        recipients=recipient_values,
        sent_at=sent_at,
        text_body=text,
        html_body=html,
        raw_bytes=raw,
        attachments=attachments,
        metadata={"path": str(path)},
    )


def envelope_from_gmail(
    raw_message: dict[str, Any], *, account_address: str | None = None
) -> EmailEnvelope:
    import base64

    raw = base64.urlsafe_b64decode(raw_message.get("raw", "") + "===")
    pathless = parse_raw_email(raw, provider="gmail")
    headers = raw_message.get("payload", {}).get("headers", [])
    values = {item.get("name", "").lower(): item.get("value", "") for item in headers}
    return EmailEnvelope(
        provider="gmail",
        provider_message_id=raw_message.get("id"),
        provider_thread_id=raw_message.get("threadId"),
        message_id_header=values.get("message-id") or pathless.message_id_header,
        subject=values.get("subject") or pathless.subject,
        sender_name=pathless.sender_name,
        sender_email=pathless.sender_email,
        recipients=pathless.recipients or ([account_address] if account_address else []),
        sent_at=pathless.sent_at,
        text_body=pathless.text_body,
        html_body=pathless.html_body,
        raw_bytes=raw,
        attachments=pathless.attachments,
        metadata={"gmail_label_ids": raw_message.get("labelIds", [])},
    )


def parse_raw_email(raw: bytes, *, provider: str = "manual") -> EmailEnvelope:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    temp = EmailEnvelope(
        provider=provider,
        provider_message_id=None,
        provider_thread_id=None,
        message_id_header=message.get("Message-ID"),
        subject="",
        sender_name=None,
        sender_email=None,
        recipients=[],
        sent_at=None,
        text_body="",
    )
    text, html, attachments = _body_from_message(message)
    sender = getaddresses([message.get("From", "")])
    sender_name, sender_email = sender[0] if sender else (None, None)
    sent_at: datetime | None = None
    date_header = message.get("Date")
    if isinstance(date_header, str):
        try:
            sent_at = parsedate_to_datetime(date_header)
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=UTC)
            sent_at = sent_at.astimezone(UTC)
        except (TypeError, ValueError, IndexError):
            pass
    return EmailEnvelope(
        **{
            **temp.__dict__,
            "subject": _clean_text(str(message.get("Subject", ""))),
            "sender_name": sender_name or None,
            "sender_email": sender_email or None,
            "recipients": [
                email or name for name, email in getaddresses(message.get_all("To", []))
            ],
            "sent_at": sent_at,
            "text_body": text,
            "html_body": html,
            "raw_bytes": raw,
            "attachments": attachments,
        }
    )


def classify_email(
    envelope: EmailEnvelope, companies: list[Company] | None = None
) -> EmailClassification:
    haystack = f"{envelope.subject}\n{envelope.text_body}".lower()
    candidates: list[tuple[str, int, list[str]]] = []
    for classification, phrases in CLASSIFICATION_RULES.items():
        hits = [phrase for phrase in phrases if phrase in haystack]
        if hits:
            candidates.append((classification, len(hits), hits))
    if not candidates:
        return EmailClassification("non_recruiting", 0.2, "rules", ["no recruiting phrase matched"])
    candidates.sort(key=lambda item: item[1], reverse=True)
    classification, hit_count, reasons = candidates[0]
    confidence = min(0.95, 0.5 + hit_count * 0.15)
    if envelope.sender_email and any(
        token in envelope.sender_email.lower() for token in ("recruit", "talent", "careers", "hr")
    ):
        confidence = min(0.99, confidence + 0.1)
        reasons.append("sender resembles recruiting mailbox")
    if companies:
        matched = [company.name for company in companies if company.name.lower() in haystack]
        if matched:
            confidence = min(0.99, confidence + 0.05)
            reasons.append(f"company name matched: {matched[0]}")
    return EmailClassification(classification, confidence, "rules", reasons)


def _company_matches(envelope: EmailEnvelope, companies: list[Company]) -> list[Company]:
    haystack = f"{envelope.subject}\n{envelope.text_body}".lower()
    matches: list[Company] = []
    for company in companies:
        aliases = [company.name, company.slug, company.primary_domain or ""]
        if any(value and value.lower() in haystack for value in aliases):
            matches.append(company)
    return matches


def _parse_date(text: str, reference: datetime) -> datetime | None:
    formats = ("%d %B %Y", "%B %d, %Y", "%d %b %Y", "%b %d, %Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=reference.tzinfo or UTC)
        except ValueError:
            continue
    return None


def _timezone_for_abbreviation(value: str) -> Any | None:
    from zoneinfo import ZoneInfo

    zones = {
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
    zone = zones.get(value.upper())
    return ZoneInfo(zone) if zone else None


def extract_email_data(
    envelope: EmailEnvelope, classification: EmailClassification
) -> list[dict[str, Any]]:
    text = envelope.text_body
    reference = envelope.sent_at or datetime.now(UTC)
    extracted: list[dict[str, Any]] = []
    links = re.findall(r"https?://[^\s<>\]\)]+", text)
    for url in links:
        host = urlparse(url).netloc.lower()
        provider = next(
            (key for key, (_, domain) in ASSESSMENT_PROVIDERS.items() if domain and domain in host),
            None,
        )
        if provider or classification.classification in {
            "online_assessment",
            "coding_assessment",
            "psychometric_assessment",
            "hirevue",
        }:
            extracted.append(
                {
                    "type": "assessment_link",
                    "value": {"url": url, "provider": provider or "other"},
                    "span": url,
                    "confidence": 0.9 if provider else 0.55,
                }
            )
    date_patterns = (
        r"(?:[A-Z][a-z]{2,8}\s+\d{1,2}(?:st|nd|rd|th)?"
        r"(?:,?\s+\d{4})?|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})"
    )
    for match in re.finditer(date_patterns, text):
        raw = match.group(0)
        normalized = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", raw)
        parsed = _parse_date(normalized, reference)
        if parsed:
            extracted.append(
                {
                    "type": "date",
                    "value": {"local_datetime": parsed.isoformat(), "timezone": str(parsed.tzinfo)},
                    "span": raw,
                    "confidence": 0.8,
                }
            )
    relative = re.search(r"(?:within|in)\s+(\d+)\s+(hour|hours|day|days)", text, re.IGNORECASE)
    if relative and envelope.sent_at:
        amount = int(relative.group(1))
        delta = (
            timedelta(hours=amount)
            if relative.group(2).lower().startswith("hour")
            else timedelta(days=amount)
        )
        extracted.append(
            {
                "type": "deadline",
                "value": {
                    "original": relative.group(0),
                    "calculated": (envelope.sent_at + delta).isoformat(),
                    "calculation_method": "email_timestamp_plus_relative_duration",
                },
                "span": relative.group(0),
                "confidence": 0.9,
            }
        )
    time_match = re.search(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\s*([A-Z]{2,4})?\b", text, re.IGNORECASE
    )
    if time_match:
        zone = time_match.group(4)
        tz = _timezone_for_abbreviation(zone) if zone else None
        extracted.append(
            {
                "type": "time",
                "value": {
                    "time": time_match.group(0),
                    "timezone": zone,
                    "timezone_resolved": bool(tz),
                },
                "span": time_match.group(0),
                "confidence": 0.85 if tz else 0.45,
            }
        )
    if classification.classification in {
        "interview_invitation",
        "interview_confirmation",
        "interview_reschedule",
    }:
        extracted.append(
            {
                "type": "interview_event",
                "value": {"classification": classification.classification},
                "span": envelope.subject,
                "confidence": classification.confidence,
            }
        )
    extracted.append(
        {
            "type": "classification",
            "value": {"classification": classification.classification},
            "span": envelope.subject,
            "confidence": classification.confidence,
        }
    )
    return extracted


def _upsert_account(
    session: Session, envelope: EmailEnvelope, address: str | None
) -> LocalEmailAccount:
    account = session.scalar(
        select(LocalEmailAccount).where(
            LocalEmailAccount.provider == envelope.provider, LocalEmailAccount.address == address
        )
    )
    if account is None:
        account = LocalEmailAccount(provider=envelope.provider, address=address, status="connected")
        session.add(account)
        session.flush()
    return account


def _link_application(
    session: Session, envelope: EmailEnvelope, companies: list[Company]
) -> tuple[Application | None, Company | None, float, str]:
    matches = _company_matches(envelope, companies)
    applications = list(session.scalars(select(Application).join(Application.job)))
    candidates = [
        item
        for item in applications
        if not matches or item.job.company_id in {company.id for company in matches}
    ]
    title_hits = [
        item for item in candidates if item.job.title.lower() in envelope.text_body.lower()
    ]
    if len(title_hits) == 1:
        return title_hits[0], title_hits[0].job.company, 0.92, "company_and_role_title"
    if len(matches) == 1 and len(candidates) == 1:
        return candidates[0], matches[0], 0.82, "company_and_single_application"
    if len(matches) == 1:
        return None, matches[0], 0.55, "company_name_only"
    return None, None, 0.0, "unresolved"


def ingest_envelope(
    envelope: EmailEnvelope, settings: Settings | None = None, *, account_address: str | None = None
) -> dict[str, Any]:
    config = settings or get_settings()
    content_hash = hashlib.sha256(
        envelope.raw_bytes or envelope.text_body.encode("utf-8")
    ).hexdigest()
    with get_local_session(config) as session:
        existing = session.scalar(
            select(LocalEmailMessage).where(
                LocalEmailMessage.provider == envelope.provider,
                LocalEmailMessage.content_hash == content_hash,
            )
        )
        if existing:
            return {
                "message_id": str(existing.id),
                "duplicate": True,
                "classification": existing.metadata_.get("classification"),
            }
        account = _upsert_account(session, envelope, account_address or envelope.sender_email)
        thread = None
        if envelope.provider_thread_id:
            thread = session.scalar(
                select(LocalEmailThread).where(
                    LocalEmailThread.account_id == account.id,
                    LocalEmailThread.provider_thread_id == envelope.provider_thread_id,
                )
            )
        if thread is None:
            thread = LocalEmailThread(
                account_id=account.id,
                provider_thread_id=envelope.provider_thread_id,
                subject=envelope.subject,
                first_message_at=envelope.sent_at,
                last_message_at=envelope.sent_at,
            )
            session.add(thread)
            session.flush()
        companies = list(session.scalars(select(Company)))
        classification = classify_email(envelope, companies)
        retain_text = config.email_storage_mode != "metadata_only"
        message = LocalEmailMessage(
            account_id=account.id,
            thread_id=thread.id,
            provider=envelope.provider,
            provider_message_id=envelope.provider_message_id,
            provider_thread_id=envelope.provider_thread_id,
            message_id_header=envelope.message_id_header,
            subject=envelope.subject,
            sender_name=envelope.sender_name,
            sender_email=envelope.sender_email,
            recipients=envelope.recipients,
            sent_at=envelope.sent_at,
            received_at=datetime.now(UTC),
            text_body=envelope.text_body if retain_text else None,
            content_hash=content_hash,
            metadata_={
                "classification": classification.classification,
                "classification_confidence": classification.confidence,
                "classification_method": classification.method,
                **envelope.metadata,
            },
        )
        if envelope.raw_bytes and config.email_storage_mode == "raw":
            raw_dir = config.local_data_dir / "email" / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{content_hash}.eml"
            if not raw_path.exists():
                raw_path.write_bytes(envelope.raw_bytes)
            message.raw_path = str(raw_path)
        session.add(message)
        session.flush()
        for attachment in envelope.attachments:
            session.add(
                LocalEmailAttachment(
                    message_id=message.id,
                    filename=str(attachment.get("filename", "attachment")),
                    media_type=attachment.get("media_type"),
                    size_bytes=attachment.get("size_bytes"),
                    metadata_=attachment,
                )
            )
        application, company, link_confidence, link_method = _link_application(
            session, envelope, companies
        )
        if application or company:
            session.add(
                LocalEmailLink(
                    message_id=message.id,
                    application_id=application.id if application else None,
                    company_id=company.id if company else None,
                    job_id=application.job_id if application else None,
                    confidence=link_confidence,
                    method=link_method,
                    link_type="suggested",
                    approved=link_confidence >= 0.8,
                )
            )
        for item in extract_email_data(envelope, classification):
            session.add(
                LocalEmailExtraction(
                    message_id=message.id,
                    extraction_type=item["type"],
                    value=item["value"],
                    text_span=item.get("span"),
                    confidence=item["confidence"],
                    needs_review=item["confidence"] < 0.7,
                )
            )
        return {
            "message_id": str(message.id),
            "duplicate": False,
            "classification": classification.classification,
            "confidence": classification.confidence,
            "application_id": str(application.id) if application else None,
            "company_id": str(company.id) if company else None,
        }


def import_eml(path: Path, settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    result = ingest_envelope(parse_eml(path), config)
    if not result["duplicate"]:
        from quant_recruiting.recruiting_operations import process_email_message

        result.update(process_email_message(UUID(result["message_id"]), config))
    return result


def sync_gmail(
    provider: RecruitingEmailProvider,
    settings: Settings | None = None,
    *,
    account_address: str | None = None,
    query: str | None = None,
    message_ids: list[str] | None = None,
) -> dict[str, Any]:
    config = settings or get_settings()
    messages = (
        [{"id": message_id} for message_id in message_ids]
        if message_ids is not None
        else provider.list_messages(query=query)
    )
    result: dict[str, Any] = {"found": len(messages), "new": 0, "duplicates": 0, "results": []}
    for item in messages:
        envelope = envelope_from_gmail(
            provider.get_message(str(item["id"])), account_address=account_address
        )
        current = ingest_envelope(envelope, config, account_address=account_address)
        if not current["duplicate"]:
            from quant_recruiting.recruiting_operations import process_email_message

            current.update(process_email_message(UUID(current["message_id"]), config))
        result["results"].append(current)
        result["duplicates" if current["duplicate"] else "new"] += 1
    return result
