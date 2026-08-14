from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.config import Settings
from quant_recruiting.db.models import Company, CompanyDomain
from quant_recruiting.discovery.core import (
    DiscoveredURLCandidate,
    DiscoveryContext,
    DiscoveryProvider,
)
from quant_recruiting.discovery.scoring import classify_research_category, score_url
from quant_recruiting.ingestion.web import DiscoveredSource, SourceCollector
from quant_recruiting.utils import canonicalize_url


def _strip_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(xml: str) -> tuple[list[str], list[str]]:
    """Return `(page_urls, child_sitemaps)` from sitemap or sitemap-index XML."""
    root = ElementTree.fromstring(xml)
    pages: list[str] = []
    children: list[str] = []
    for element in root.iter():
        if _strip_tag(element.tag) != "loc" or not element.text:
            continue
        if _strip_tag(root.tag) == "sitemapindex":
            children.append(element.text.strip())
        else:
            pages.append(element.text.strip())
    return pages, children


@dataclass
class OfficialSiteDiscoveryProvider(DiscoveryProvider):
    session: Session
    settings: Settings
    collector: SourceCollector = SourceCollector()

    def _domains(self, company: Company) -> dict[str, str]:
        domains = {
            domain.domain: domain.domain_type
            for domain in self.session.scalars(
                select(CompanyDomain).where(CompanyDomain.company_id == company.id)
            )
        }
        if company.primary_domain:
            hostname = urlsplit(
                company.primary_domain
                if "://" in company.primary_domain
                else f"https://{company.primary_domain}"
            ).hostname
            if hostname:
                domains.setdefault(hostname.lower().removeprefix("www."), "corporate")
        if company.careers_url:
            hostname = urlsplit(company.careers_url).hostname
            if hostname:
                domains.setdefault(hostname.lower().removeprefix("www."), "careers")
        return domains

    def _allowed(self, url: str, domains: dict[str, str], context: DiscoveryContext) -> bool:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            return parsed.scheme == "file"
        hostname = (parsed.hostname or "").lower().removeprefix("www.")
        allowed = context.allowed_domains or set(domains)
        return hostname in allowed and not any(
            parsed.path.lower().startswith(path) for path in context.denied_paths
        )

    def _fetch_urls_from_sitemaps(
        self, roots: list[str], domains: dict[str, str], context: DiscoveryContext
    ) -> list[str]:
        queue = deque(roots)
        seen: set[str] = set()
        pages: list[str] = []
        while queue and len(seen) < context.max_pages:
            sitemap_url = canonicalize_url(queue.popleft())
            if sitemap_url in seen or not self._allowed(sitemap_url, domains, context):
                continue
            seen.add(sitemap_url)
            try:
                fetched = self.collector.fetch(
                    DiscoveredSource(sitemap_url, "sitemap"), self.settings
                )
                page_urls, child_urls = parse_sitemap(
                    fetched.content.decode("utf-8", errors="replace")
                )
            except (ElementTree.ParseError, OSError, ValueError, PermissionError, RuntimeError):
                continue
            pages.extend(url for url in page_urls if self._allowed(url, domains, context))
            queue.extend(child_urls)
        return list(dict.fromkeys(pages))

    def _robots_sitemaps(self, domains: dict[str, str]) -> list[str]:
        declared: list[str] = []
        for domain in domains:
            try:
                response = httpx.get(
                    f"https://{domain}/robots.txt",
                    headers={"User-Agent": self.settings.http_user_agent},
                    timeout=min(self.settings.http_timeout_seconds, 10),
                    follow_redirects=True,
                )
            except httpx.HTTPError:
                continue
            if response.status_code >= 400:
                continue
            declared.extend(
                line.split(":", 1)[1].strip()
                for line in response.text.splitlines()
                if line.lower().startswith("sitemap:") and ":" in line
            )
        return declared

    def discover(self, company: Company, context: DiscoveryContext) -> list[DiscoveredURLCandidate]:
        domains = self._domains(company)
        if not domains:
            return []
        seeds = []
        if company.careers_url:
            seeds.append(company.careers_url)
        for domain in domains:
            seeds.extend([f"https://{domain}/", f"https://{domain}/sitemap.xml"])
        sitemap_roots = [url for url in seeds if url.lower().endswith((".xml", "sitemap.xml"))]
        sitemap_roots.extend(self._robots_sitemaps(domains))
        sitemap_pages = self._fetch_urls_from_sitemaps(sitemap_roots, domains, context)
        candidates: dict[str, DiscoveredURLCandidate] = {}
        for url in sitemap_pages:
            score, reasons = score_url(
                url, domain_type=domains.get(urlsplit(url).hostname or "", "")
            )
            if score >= context.minimum_score:
                category, category_confidence = classify_research_category(url)
                candidates[canonicalize_url(url)] = DiscoveredURLCandidate(
                    url=url,
                    discovery_method="sitemap",
                    probable_source_type=category,
                    relevance_score=score,
                    reason="; ".join(reasons),
                    metadata={"category": category, "category_confidence": category_confidence},
                )
        frontier = deque((url, 0) for url in seeds if not url.lower().endswith(".xml"))
        visited: set[str] = set()
        while frontier and len(visited) < context.max_pages:
            current, depth = frontier.popleft()
            canonical = canonicalize_url(current)
            if canonical in visited or not self._allowed(current, domains, context):
                continue
            visited.add(canonical)
            try:
                fetched = self.collector.fetch(
                    DiscoveredSource(current, "official_website"), self.settings
                )
            except (OSError, PermissionError, RuntimeError, ValueError):
                continue
            soup = BeautifulSoup(fetched.content, "html.parser")
            page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
            score, reasons = score_url(
                current,
                title=page_title,
                domain_type=domains.get(urlsplit(current).hostname or "", ""),
            )
            if score >= context.minimum_score:
                category, category_confidence = classify_research_category(current, page_title)
                candidates[canonical] = DiscoveredURLCandidate(
                    url=current,
                    discovery_method="seed_page" if depth == 0 else "internal_link",
                    probable_source_type=category,
                    relevance_score=score,
                    reason="; ".join(reasons),
                    metadata={
                        "title": page_title,
                        "depth": depth,
                        "category": category,
                        "category_confidence": category_confidence,
                    },
                )
            if depth >= context.max_depth:
                continue
            for anchor in soup.find_all("a", href=True):
                target = canonicalize_url(urljoin(current, str(anchor["href"])))
                if not self._allowed(target, domains, context) or target in visited:
                    continue
                anchor_text = anchor.get_text(" ", strip=True)
                linked_score, linked_reasons = score_url(target, anchor=anchor_text)
                if linked_score >= context.minimum_score / 2:
                    frontier.append((target, depth + 1))
                    if linked_score >= context.minimum_score:
                        category, category_confidence = classify_research_category(
                            target, anchor=anchor_text
                        )
                        candidates.setdefault(
                            target,
                            DiscoveredURLCandidate(
                                url=target,
                                discovery_method="internal_link",
                                probable_source_type=category,
                                relevance_score=linked_score,
                                reason="; ".join(linked_reasons),
                                metadata={
                                    "anchor": anchor_text,
                                    "depth": depth + 1,
                                    "category": category,
                                    "category_confidence": category_confidence,
                                },
                            ),
                        )
            if context.per_domain_delay_seconds:
                time.sleep(context.per_domain_delay_seconds)
        return sorted(candidates.values(), key=lambda item: item.relevance_score, reverse=True)
