from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.config import Settings
from quant_recruiting.db.models import Company, CompanyATS, Job, JobObservation, RoleFamily
from quant_recruiting.discovery.core import DiscoveryContext
from quant_recruiting.discovery.official import OfficialSiteDiscoveryProvider
from quant_recruiting.discovery.persistence import persist_discovered_url
from quant_recruiting.ingestion.web import (
    DiscoveredSource,
    SourceCollector,
    persist_fetch_error,
)
from quant_recruiting.utils import canonicalize_url, normalize_text

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017 - Python 3.10 compatibility

ROLE_RULES: tuple[tuple[str, tuple[str, ...], float], ...] = (
    (
        "quantitative_research",
        ("quantitative research", "quant research", "quant researcher", "qr intern"),
        0.95,
    ),
    ("quantitative_trading", ("quantitative trader", "quant trader", "quant trading"), 0.95),
    (
        "investment_banking",
        ("investment banking", "investment bank", "m&a analyst", "summer analyst"),
        0.88,
    ),
    ("equity_research", ("equity research", "equity analyst"), 0.9),
    ("sales_and_trading", ("sales and trading", "sales & trading"), 0.9),
    ("asset_management", ("asset management", "portfolio analyst", "portfolio management"), 0.85),
    ("private_equity", ("private equity", "buyout analyst"), 0.9),
    ("venture_capital", ("venture capital", "venture analyst"), 0.9),
    ("machine_learning", ("machine learning", "ml engineer", "machine learning intern"), 0.9),
    ("data_science", ("data scientist", "data science", "data analyst"), 0.85),
    (
        "software_engineering",
        ("software engineer", "software engineering", "swe intern", "developer"),
        0.9,
    ),
    ("trading", ("trader", "trading"), 0.7),
    ("research", ("researcher", "research intern"), 0.7),
)


@dataclass(frozen=True)
class JobPosting:
    url: str
    title: str
    description: str
    date_posted: date | None
    valid_through: datetime | None
    employment_type: str | None
    location_text: str | None
    external_id: str | None
    structured_data: dict[str, Any]
    raw_html: bytes


def _jsonld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            parsed = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values = parsed if isinstance(parsed, list) else [parsed]
        for value in values:
            if isinstance(value, dict) and isinstance(value.get("@graph"), list):
                values.extend(item for item in value["@graph"] if isinstance(item, dict))
            elif isinstance(value, dict):
                objects.append(value)
    return objects


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def extract_job_posting(url: str, html: bytes) -> JobPosting | None:
    soup = BeautifulSoup(html, "html.parser")
    posting = next(
        (
            item
            for item in _jsonld_objects(soup)
            if item.get("@type") == "JobPosting" or "JobPosting" in (item.get("@type") or [])
        ),
        None,
    )
    if posting is None:
        return None
    location = posting.get("jobLocation") or posting.get("applicantLocationRequirements")
    if isinstance(location, list):
        location = "; ".join(json.dumps(item, sort_keys=True) for item in location)
    elif isinstance(location, dict):
        location = json.dumps(location, sort_keys=True)
    identifier = posting.get("identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("value") or identifier.get("name")
    posting_title = posting.get("title") or (
        soup.title.get_text(" ", strip=True) if soup.title else "Untitled role"
    )
    return JobPosting(
        url=canonicalize_url(str(posting.get("url") or url)),
        title=str(posting_title),
        description=BeautifulSoup(str(posting.get("description") or ""), "html.parser").get_text(
            " ", strip=True
        ),
        date_posted=_parse_date(posting.get("datePosted")),
        valid_through=_parse_datetime(posting.get("validThrough")),
        employment_type=str(posting.get("employmentType"))
        if posting.get("employmentType")
        else None,
        location_text=location,
        external_id=str(identifier) if identifier else None,
        structured_data=posting,
        raw_html=html,
    )


def classify_role(title: str, text: str = "") -> tuple[str, float]:
    haystack = normalize_text(f"{title} {text}")
    for role_family, patterns, confidence in ROLE_RULES:
        if any(pattern in haystack for pattern in patterns):
            return role_family, confidence
    return "other", 0.2


def extract_internship_cycle(text: str) -> tuple[str | None, str | None]:
    patterns = (
        r"\b(?:summer|spring|autumn|fall)?\s*(20(?:2[5-9]|3\d))\s+(?:internship|intern|graduate)\b",
        r"\bclass of\s+(20(?:2[5-9]|3\d))\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1), match.group(0)
    return None, None


def _job_hash(posting: JobPosting) -> str:
    payload = {
        "title": posting.title,
        "description": posting.description,
        "valid_through": posting.valid_through.isoformat() if posting.valid_through else None,
        "employment_type": posting.employment_type,
        "location": posting.location_text,
        "structured_data": posting.structured_data,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def upsert_job(
    session: Session,
    company: Company,
    posting: JobPosting,
    source_url: str | None = None,
    ats: CompanyATS | None = None,
) -> tuple[Job, bool, bool]:
    now = datetime.now(UTC)
    content_hash = _job_hash(posting)
    role_family, confidence = classify_role(posting.title, posting.description)
    role_family_ref = session.scalar(select(RoleFamily).where(RoleFamily.slug == role_family))
    cycle, cycle_wording = extract_internship_cycle(f"{posting.title} {posting.description}")
    canonical_url = canonicalize_url(posting.url)
    job: Job | None = None
    if posting.external_id:
        job = session.scalar(
            select(Job).where(Job.company_id == company.id, Job.external_id == posting.external_id)
        )
    if job is None:
        job = session.scalar(
            select(Job).where(Job.company_id == company.id, Job.job_url == canonical_url)
        )
    is_new = job is None
    changed = job is None or job.content_hash != content_hash
    if job is None:
        job = Job(
            company=company,
            external_id=posting.external_id,
            title=posting.title,
            role_family=role_family,
            role_family_ref=role_family_ref,
            ats=ats,
            employment_type=posting.employment_type,
            internship_cycle=cycle,
            location_text=posting.location_text,
            job_url=canonical_url,
            source_type="ats" if ats is not None else "official_website",
            source_url=source_url or canonical_url,
            description_text=posting.description,
            date_posted=posting.date_posted,
            date_first_seen=now,
            date_last_seen=now,
            application_deadline=posting.valid_through,
            status="open",
            content_hash=content_hash,
            classification_confidence=confidence,
            classification_method="deterministic_rules",
            classification_locked=False,
            metadata_={
                "structured_data": posting.structured_data,
                "cycle_wording": cycle_wording,
                "classification_method": "deterministic_rules",
                "ats_provider": ats.provider if ats is not None else None,
            },
        )
        session.add(job)
        session.flush()
    else:
        job.date_last_seen = now
        job.status = "open"
        if ats is not None:
            job.ats = ats
        if changed:
            job.title = posting.title
            if not job.classification_locked:
                job.role_family = role_family
                job.role_family_ref = role_family_ref
                job.classification_confidence = confidence
                job.classification_method = "deterministic_rules"
            job.employment_type = posting.employment_type
            job.internship_cycle = cycle
            job.location_text = posting.location_text
            job.description_text = posting.description
            job.application_deadline = posting.valid_through
            job.content_hash = content_hash
            job.metadata_ = {
                **job.metadata_,
                "structured_data": posting.structured_data,
                "cycle_wording": cycle_wording,
                "classification_method": "deterministic_rules",
            }
        session.flush()
    latest = session.scalar(
        select(JobObservation)
        .where(JobObservation.job_id == job.id)
        .order_by(JobObservation.observed_at.desc())
    )
    if latest is None or latest.content_hash != content_hash:
        session.add(
            JobObservation(
                job=job,
                observed_at=now,
                content_hash=content_hash,
                title=posting.title,
                description_text=posting.description,
                application_deadline=posting.valid_through,
                status=job.status,
                source_url=source_url or posting.url,
                structured_data=posting.structured_data,
            )
        )
    session.flush()
    return job, is_new, changed


def discover_jobs(
    session: Session,
    company: Company,
    settings: Settings,
    context: DiscoveryContext | None = None,
) -> dict[str, int]:
    provider = OfficialSiteDiscoveryProvider(session, settings)
    context = context or DiscoveryContext(
        max_pages=settings.discovery_max_pages, max_depth=settings.discovery_max_depth
    )
    candidates = provider.discover(company, context)
    considered = 0
    new_jobs = changed_jobs = unchanged_jobs = 0
    seen_job_ids: set = set()
    collector = SourceCollector()
    for candidate in candidates:
        item = persist_discovered_url(session, company, candidate)
        if (
            candidate.probable_source_type not in {"role_description", "internship", "careers"}
            and "job" not in candidate.url.lower()
        ):
            continue
        considered += 1
        if item.last_fetched_at and datetime.now(UTC) - item.last_fetched_at < timedelta(
            hours=settings.job_freshness_hours
        ):
            existing_job_id = item.metadata_.get("job_id")
            if existing_job_id:
                seen_job_ids.add(UUID(str(existing_job_id)))
            unchanged_jobs += 1
            continue
        try:
            fetched = collector.fetch(
                DiscoveredSource(
                    candidate.url,
                    "job_board",
                    metadata={"discovery_id": str(item.id), **candidate.metadata},
                ),
                settings,
            )
            posting = extract_job_posting(candidate.url, fetched.content)
            item.last_fetched_at = fetched.retrieved_at
            if posting is None:
                continue
            job, is_new, changed = upsert_job(session, company, posting, candidate.url)
            item.status = "ingested"
            item.metadata_ = {**item.metadata_, "job_id": str(job.id)}
            seen_job_ids.add(job.id)
            if is_new:
                new_jobs += 1
            elif changed:
                changed_jobs += 1
            else:
                unchanged_jobs += 1
        except (OSError, PermissionError, RuntimeError, ValueError, httpx.HTTPError) as exc:
            item.status = "failed"
            item.error_message = str(exc)
            persist_fetch_error(session, candidate.url, exc, operation="job_discovery")
    for job in session.scalars(
        select(Job).where(Job.company_id == company.id, Job.status == "open")
    ):
        if job.id not in seen_job_ids and considered:
            job.status = "closed"
    session.flush()
    return {
        "pages_considered": len(candidates),
        "job_candidates": considered,
        "new_jobs": new_jobs,
        "changed_jobs": changed_jobs,
        "unchanged_jobs": unchanged_jobs,
    }
