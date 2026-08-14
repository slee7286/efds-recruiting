from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from quant_recruiting.db.models import Company

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017 - Python 3.10 compatibility


@dataclass(frozen=True)
class DiscoveryContext:
    max_pages: int = 200
    max_depth: int = 2
    allowed_domains: set[str] = field(default_factory=set)
    denied_paths: tuple[str, ...] = ("/login", "/account", "/checkout", "/api/")
    minimum_score: float = 0.2
    per_domain_delay_seconds: float = 0.5


@dataclass(frozen=True)
class DiscoveredURLCandidate:
    url: str
    discovery_method: str
    probable_source_type: str
    relevance_score: float
    reason: str
    discovered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, object] = field(default_factory=dict)


class DiscoveryProvider(Protocol):
    def discover(
        self, company: Company, context: DiscoveryContext
    ) -> list[DiscoveredURLCandidate]: ...
