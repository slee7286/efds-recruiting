from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.db.models import Company, DiscoveredURL
from quant_recruiting.discovery.core import DiscoveredURLCandidate
from quant_recruiting.utils import canonicalize_url


def persist_discovered_url(
    session: Session, company: Company, candidate: DiscoveredURLCandidate
) -> DiscoveredURL:
    canonical = canonicalize_url(candidate.url)
    item = session.scalar(
        select(DiscoveredURL).where(
            DiscoveredURL.company_id == company.id,
            DiscoveredURL.canonical_url == canonical,
        )
    )
    if item is None:
        item = DiscoveredURL(
            company=company,
            url=candidate.url,
            canonical_url=canonical,
            discovery_method=candidate.discovery_method,
            probable_source_type=candidate.probable_source_type,
            relevance_score=candidate.relevance_score,
            discovery_reason=candidate.reason,
            discovered_at=candidate.discovered_at,
            last_discovered_at=candidate.discovered_at,
            metadata_=candidate.metadata,
        )
        session.add(item)
    else:
        item.url = candidate.url
        item.discovery_method = candidate.discovery_method
        item.probable_source_type = candidate.probable_source_type
        item.relevance_score = max(item.relevance_score, candidate.relevance_score)
        item.discovery_reason = candidate.reason
        item.last_discovered_at = candidate.discovered_at
        item.metadata_ = {**item.metadata_, **candidate.metadata}
        if item.status in {"failed", "ignored"}:
            item.status = "discovered"
    session.flush()
    return item
