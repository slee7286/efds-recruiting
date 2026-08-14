"""Deterministic research-query generation and public URL classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.db.models import Company, ResearchQuery, ResearchSearchResult
from quant_recruiting.utils import canonicalize_url

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017

RESEARCH_CATEGORIES = (
    "firm_overview",
    "business_model",
    "strategy",
    "culture",
    "values",
    "leadership",
    "technology",
    "research",
    "products",
    "markets",
    "transactions",
    "clients",
    "competitors",
    "careers",
    "internships",
    "graduate_programmes",
    "recruiting_cycle",
    "application_process",
    "interview_process",
    "candidate_experience",
    "news",
    "reports",
    "research_papers",
    "events",
    "podcasts",
    "videos",
    "social",
    "employee_content",
    "interview_questions",
    "online_assessments",
    "preparation_resources",
)

TEMPLATES: dict[str, tuple[str, ...]] = {
    "careers": ('"{company}" careers', '"{company}" internship', '"{company}" graduate programme'),
    "recruiting_cycle": ('"{company}" recruiting cycle {cycle}', '"{company}" application process'),
    "interview_process": (
        '"{company}" interview process',
        '"{company}" online assessment',
        '"{company}" candidate experience',
    ),
    "technology": ('"{company}" technology', '"{company}" engineering'),
    "research": (
        '"{company}" research',
        '"{company}" annual report',
        '"{company}" investor presentation',
    ),
    "news": ('"{company}" news', '"{company}" announcement'),
    "preparation_resources": (
        '"{company}" interview questions',
        '"{company}" interview preparation',
    ),
}


@dataclass(frozen=True)
class ResearchQuerySpec:
    query: str
    category: str
    role_family: str | None = None
    recruiting_cycle: str | None = None


@dataclass(frozen=True)
class SearchResult:
    url: str
    provider: str = "fixture"
    title: str | None = None
    snippet: str | None = None
    rank: int | None = None
    published_at: datetime | None = None
    source_type_guess: str | None = None
    metadata: dict[str, Any] | None = None


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int) -> list[SearchResult]: ...


class SearchProviderUnavailable(RuntimeError):
    """Raised when search execution was requested without valid configuration."""


class BraveSearchProvider:
    name = "brave"

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout
        self.client = client

    def search(self, query: str, *, limit: int) -> list[SearchResult]:
        request_client = self.client or httpx.Client()
        response = request_client.get(
            self.endpoint,
            params={"q": query, "count": min(max(limit, 1), 20)},
            headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("web", {}).get("results", []) if isinstance(payload, dict) else []
        return [
            SearchResult(
                provider=self.name,
                url=str(item.get("url", "")),
                title=item.get("title"),
                snippet=item.get("description"),
                rank=index,
                source_type_guess=classify_url(str(item.get("url", "")))[0],
                metadata={"raw_provider_result": item},
            )
            for index, item in enumerate(results[:limit], start=1)
            if isinstance(item, dict) and item.get("url")
        ]


def get_search_provider(settings: Any) -> SearchProvider:
    provider = (settings.search_provider or "").strip().lower()
    if provider == "brave" and settings.search_api_key:
        return BraveSearchProvider(
            settings.search_api_key, settings.search_endpoint, settings.http_timeout_seconds
        )
    raise SearchProviderUnavailable(
        "No configured search provider. Set SEARCH_PROVIDER=brave and SEARCH_API_KEY."
    )


def generate_queries(
    company: Company,
    role_family: str | None = None,
    cycle: str | None = None,
    categories: list[str] | None = None,
) -> list[ResearchQuerySpec]:
    selected = categories or [
        "careers",
        "recruiting_cycle",
        "interview_process",
        "technology",
        "research",
        "news",
        "preparation_resources",
    ]
    names = [company.name, *[alias.alias for alias in company.aliases]]
    output: list[ResearchQuerySpec] = []
    seen: set[str] = set()
    for category in selected:
        for name in names:
            for template in TEMPLATES.get(
                category, (f'"{{company}}" {category.replace("_", " ")}',)
            ):
                query = template.format(company=name, cycle=cycle or "")
                if role_family and category in {
                    "careers",
                    "interview_process",
                    "preparation_resources",
                }:
                    query = f"{query} {role_family.replace('_', ' ')}"
                if query not in seen:
                    seen.add(query)
                    output.append(ResearchQuerySpec(query, category, role_family, cycle))
    return output


def classify_url(url: str) -> tuple[str, str]:
    lowered = url.lower()
    if "greenhouse.io" in lowered:
        return "ats", "greenhouse"
    if "lever.co" in lowered:
        return "ats", "lever"
    if "ashbyhq.com" in lowered:
        return "ats", "ashby"
    if "reddit.com" in lowered:
        return "reddit", "search_result"
    if "youtube.com" in lowered or "youtu.be" in lowered:
        return "youtube", "search_result"
    if "github.com" in lowered:
        return "github", "search_result"
    if lowered.endswith(".pdf") or ".pdf?" in lowered:
        return "pdf", "report"
    if any(token in lowered for token in ("news", "reuters", "bloomberg", "ft.com")):
        return "news", "news"
    return "other", "search_result"


def normalize_result(result: SearchResult) -> SearchResult:
    return SearchResult(
        provider=result.provider,
        url=canonicalize_url(result.url),
        title=result.title,
        snippet=result.snippet,
        rank=result.rank,
        published_at=result.published_at,
        source_type_guess=result.source_type_guess or classify_url(result.url)[0],
        metadata=result.metadata or {},
    )


def persist_search_results(
    session: Session, query: ResearchQuery, results: list[SearchResult]
) -> int:
    """Persist provider results idempotently without promoting them to claims."""
    created = 0
    for raw_result in results:
        result = normalize_result(raw_result)
        existing = session.scalar(
            select(ResearchSearchResult).where(
                ResearchSearchResult.query_id == query.id,
                ResearchSearchResult.canonical_url == result.url,
            )
        )
        if existing is None:
            source_type, provider_type = classify_url(result.url)
            session.add(
                ResearchSearchResult(
                    query=query,
                    company_id=query.company_id,
                    url=result.url,
                    canonical_url=result.url,
                    result_rank=result.rank,
                    title=result.title,
                    snippet=result.snippet,
                    published_at=result.published_at,
                    discovered_at=query.discovered_at,
                    role_family_id=query.role_family_id,
                    recruiting_cycle=query.recruiting_cycle,
                    metadata_={
                        **(result.metadata or {}),
                        "provider": result.provider,
                        "source_type": result.source_type_guess or source_type,
                        "classification": provider_type,
                    },
                )
            )
            created += 1
    session.flush()
    return created
