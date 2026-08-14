"""Unauthenticated public ATS adapters.

Adapters deliberately accept an injected HTTP client so tests never depend on
third-party services and production callers can apply the shared HTTP policy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Protocol

import httpx
from bs4 import BeautifulSoup

from quant_recruiting.db.models import Company, CompanyATS
from quant_recruiting.jobs import JobPosting
from quant_recruiting.utils import canonicalize_url

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017


@dataclass(frozen=True)
class ATSDetection:
    provider: str
    board_identifier: str
    board_url: str
    confidence: float


class ATSAdapter(Protocol):
    provider: str

    def list_jobs(self, config: CompanyATS, client: httpx.Client) -> list[dict[str, Any]]: ...

    def normalize_job(self, payload: dict[str, Any], config: CompanyATS) -> JobPosting: ...


def detect_ats(url: str) -> ATSDetection | None:
    patterns = (
        ("greenhouse", r"(?:boards|job-boards)\.greenhouse\.io/([^/?#]+)", 0.99),
        ("lever", r"jobs\.lever\.co/([^/?#]+)", 0.99),
        ("ashby", r"jobs\.ashbyhq\.com/([^/?#]+)", 0.99),
    )
    for provider, pattern, confidence in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            identifier = match.group(1)
            return ATSDetection(provider, identifier, canonicalize_url(url), confidence)
    return None


def _text(value: Any) -> str:
    return BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _posting(
    config: CompanyATS,
    payload: dict[str, Any],
    *,
    title: str,
    description: Any,
    url: str,
    external_id: Any,
    date_posted: Any = None,
    valid_through: Any = None,
    employment_type: Any = None,
    location: Any = None,
) -> JobPosting:
    return JobPosting(
        url=canonicalize_url(url),
        title=title,
        description=_text(description),
        date_posted=_date(date_posted),
        valid_through=_datetime(valid_through),
        employment_type=str(employment_type) if employment_type else None,
        location_text=_text(location) if location else None,
        external_id=str(external_id) if external_id is not None else None,
        structured_data=payload,
        raw_html=json.dumps(payload, sort_keys=True).encode(),
    )


class GreenhouseAdapter:
    provider = "greenhouse"

    def list_jobs(self, config: CompanyATS, client: httpx.Client) -> list[dict[str, Any]]:
        response = client.get(
            f"https://boards-api.greenhouse.io/v1/boards/{config.board_identifier}/jobs",
            params={"content": "true"},
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("jobs", []) if isinstance(payload, dict) else []

    def normalize_job(self, payload: dict[str, Any], config: CompanyATS) -> JobPosting:
        location = (
            payload.get("location", {}).get("name")
            if isinstance(payload.get("location"), dict)
            else payload.get("location")
        )
        return _posting(
            config,
            payload,
            title=str(payload.get("title") or "Untitled role"),
            description=payload.get("content"),
            url=str(payload.get("absolute_url") or config.board_url),
            external_id=payload.get("id"),
            date_posted=payload.get("first_published"),
            location=location,
        )


class LeverAdapter:
    provider = "lever"

    def list_jobs(self, config: CompanyATS, client: httpx.Client) -> list[dict[str, Any]]:
        response = client.get(
            f"https://api.lever.co/v0/postings/{config.board_identifier}", params={"mode": "json"}
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    def normalize_job(self, payload: dict[str, Any], config: CompanyATS) -> JobPosting:
        raw_categories = payload.get("categories")
        categories: dict[str, Any] = raw_categories if isinstance(raw_categories, dict) else {}
        return _posting(
            config,
            payload,
            title=str(payload.get("text") or "Untitled role"),
            description=payload.get("descriptionPlain") or payload.get("description"),
            url=str(payload.get("hostedUrl") or payload.get("applyUrl") or config.board_url),
            external_id=payload.get("id"),
            date_posted=payload.get("createdAt"),
            employment_type=categories.get("commitment"),
            location=categories.get("location"),
        )


class AshbyAdapter:
    provider = "ashby"

    def list_jobs(self, config: CompanyATS, client: httpx.Client) -> list[dict[str, Any]]:
        response = client.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{config.board_identifier}"
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("jobs", []) if isinstance(payload, dict) else []

    def normalize_job(self, payload: dict[str, Any], config: CompanyATS) -> JobPosting:
        return _posting(
            config,
            payload,
            title=str(payload.get("title") or "Untitled role"),
            description=payload.get("descriptionPlain") or payload.get("descriptionHtml"),
            url=str(payload.get("jobUrl") or payload.get("applyUrl") or config.board_url),
            external_id=payload.get("jobUrl") or payload.get("applyUrl"),
            date_posted=payload.get("publishedAt"),
            employment_type=payload.get("employmentType"),
            location=payload.get("location"),
        )


ADAPTERS: dict[str, ATSAdapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
}


def adapter_for(provider: str) -> ATSAdapter:
    try:
        return ADAPTERS[provider]
    except KeyError as exc:
        raise ValueError(f"unsupported ATS provider: {provider}") from exc


def detect_company_ats(company: Company) -> list[ATSDetection]:
    urls = [company.careers_url or ""] + [str(domain.domain) for domain in company.domains]
    detections: dict[tuple[str, str], ATSDetection] = {}
    for url in urls:
        detection = detect_ats(url)
        if detection:
            detections[(detection.provider, detection.board_identifier)] = detection
    return list(detections.values())
