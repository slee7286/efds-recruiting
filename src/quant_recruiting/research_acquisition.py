"""Search execution and bounded research-fetch queue operations."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_recruiting.config import Settings
from quant_recruiting.db.models import (
    Company,
    ResearchFetchQueue,
    ResearchQuery,
    ResearchSearchResult,
    SearchUsage,
)
from quant_recruiting.discovery.core import DiscoveredURLCandidate
from quant_recruiting.discovery.persistence import persist_discovered_url
from quant_recruiting.ingestion.web import (
    DiscoveredSource,
    SourceCollector,
    persist_fetch_error,
    persist_fetched_source,
)
from quant_recruiting.research_discovery import (
    SearchProvider,
    SearchProviderUnavailable,
    generate_queries,
    persist_search_results,
)

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017


def _candidate_score(company: Company, result: ResearchSearchResult) -> tuple[float, list[str]]:
    score = max(0.0, 1.0 - ((result.result_rank or 10) - 1) * 0.05)
    reasons = [f"search rank {result.result_rank or 'unknown'}"]
    host = urlsplit(result.canonical_url).hostname or ""
    company_domains = {company.primary_domain or ""}
    company_domains.update(domain.domain for domain in company.domains)
    if any(
        domain and (host == domain or host.endswith(f".{domain}")) for domain in company_domains
    ):
        score += 0.25
        reasons.append("company-owned domain")
    if result.metadata_.get("source_type") in {"ats", "pdf", "news", "youtube", "reddit"}:
        score += 0.05
        reasons.append(f"source type {result.metadata_['source_type']}")
    return min(score, 1.0), reasons


def execute_company_search(
    session: Session,
    company: Company,
    settings: Settings,
    provider: SearchProvider,
    *,
    category: str | None = None,
    role_family: str | None = None,
    cycle: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    specs = generate_queries(
        company,
        role_family=role_family,
        cycle=cycle,
        categories=[category] if category else None,
    )
    limit = limit or settings.search_default_limit
    if dry_run:
        return {"queries": len(specs), "results": 0, "created": 0}
    today_count = (
        session.scalar(
            select(func.coalesce(func.sum(SearchUsage.query_count), 0)).where(
                SearchUsage.provider == provider.name,
                SearchUsage.created_at
                >= datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0),
            )
        )
        or 0
    )
    if int(today_count) + len(specs) > settings.search_daily_budget:
        raise RuntimeError("configured daily search budget would be exceeded")
    result_count = created = 0
    for spec in specs:
        query = session.scalar(
            select(ResearchQuery).where(
                ResearchQuery.company_id == company.id,
                ResearchQuery.category == spec.category,
                ResearchQuery.query == spec.query,
            )
        )
        if query is None:
            query = ResearchQuery(
                company_id=company.id,
                category=spec.category,
                query=spec.query,
                provider=provider.name,
                discovered_at=datetime.now(UTC),
                recruiting_cycle=spec.recruiting_cycle,
                metadata_={"role_family": spec.role_family},
            )
            session.add(query)
            session.flush()
        results = provider.search(query.query, limit=limit)
        created += persist_search_results(session, query, results)
        result_count += len(results)
        session.add(
            SearchUsage(
                provider=provider.name,
                company_id=company.id,
                query_count=1,
                result_count=len(results),
            )
        )
    session.flush()
    return {"queries": len(specs), "results": result_count, "created": created}


def queue_company_results(
    session: Session, company: Company, *, min_score: float = 0.0
) -> dict[str, int]:
    results = session.scalars(
        select(ResearchSearchResult).where(ResearchSearchResult.company_id == company.id)
    )
    queued = 0
    for result in results:
        score, reasons = _candidate_score(company, result)
        if score < min_score:
            continue
        item = session.scalar(
            select(ResearchFetchQueue).where(
                ResearchFetchQueue.company_id == company.id,
                ResearchFetchQueue.canonical_url == result.canonical_url,
            )
        )
        if item is None:
            item = ResearchFetchQueue(
                company_id=company.id,
                url=result.url,
                canonical_url=result.canonical_url,
                source_type=str(result.metadata_.get("source_type", "other")),
                score=score,
                score_reasons=reasons,
                status="candidate",
                discovered_at=result.discovered_at,
                metadata_={"search_result_id": str(result.id)},
            )
            session.add(item)
            queued += 1
        else:
            item.score = max(item.score, score)
            item.score_reasons = list(dict.fromkeys([*item.score_reasons, *reasons]))
        persist_discovered_url(
            session,
            company,
            DiscoveredURLCandidate(
                result.url,
                "search_provider",
                str(result.metadata_.get("source_type", "other")),
                score,
                "; ".join(reasons),
                result.discovered_at,
                {"search_result_id": str(result.id), "provider": result.metadata_.get("provider")},
            ),
        )
    session.flush()
    return {"candidates": queued}


def fetch_company_queue(
    session: Session,
    company: Company,
    settings: Settings,
    *,
    min_score: float = 0.0,
    max_items: int = 20,
    dry_run: bool = False,
) -> dict[str, int]:
    items = list(
        session.scalars(
            select(ResearchFetchQueue)
            .where(
                ResearchFetchQueue.company_id == company.id,
                ResearchFetchQueue.status.in_(("candidate", "queued", "failed")),
                ResearchFetchQueue.score >= min_score,
            )
            .order_by(ResearchFetchQueue.score.desc())
            .limit(max_items)
        )
    )
    if dry_run:
        return {"considered": len(items), "fetched": 0, "failed": 0}
    collector = SourceCollector()
    fetched_count = failed_count = 0
    for item in items:
        item.status = "queued"
        item.attempts += 1
        try:
            fetched = collector.fetch(DiscoveredSource(item.url, item.source_type), settings)
            persist_fetched_source(session, company, fetched, settings)
            item.status = "normalized"
            item.fetched_at = fetched.retrieved_at
            fetched_count += 1
            persist_discovered_url(
                session,
                company,
                DiscoveredURLCandidate(
                    item.url,
                    "search_provider",
                    item.source_type,
                    item.score,
                    "; ".join(item.score_reasons),
                    item.discovered_at,
                    item.metadata_,
                ),
            )
        except Exception as exc:  # acquisition failures are persisted and isolated per item
            item.status = "failed"
            item.last_error = str(exc)
            persist_fetch_error(session, item.url, exc, operation="research_queue_fetch")
            failed_count += 1
    session.flush()
    return {"considered": len(items), "fetched": fetched_count, "failed": failed_count}


__all__ = [
    "SearchProviderUnavailable",
    "execute_company_search",
    "fetch_company_queue",
    "queue_company_results",
]
