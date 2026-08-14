from __future__ import annotations

import re
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from quant_recruiting.config import Settings
from quant_recruiting.db.models import (
    Company,
    FetchError,
    ResearchDocument,
    ResearchSource,
    SourceArtifact,
)
from quant_recruiting.utils import canonicalize_url, sha256_bytes, sha256_text

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017 - Python 3.10 local verification compatibility
_LAST_REQUEST_BY_HOST: dict[str, float] = {}


@dataclass(frozen=True)
class DiscoveredSource:
    url: str
    source_type: str = "official_website"
    title: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class FetchedSource:
    discovered: DiscoveredSource
    content: bytes
    content_type: str
    status_code: int
    retrieved_at: datetime
    headers: dict[str, str] | None = None


@dataclass(frozen=True)
class NormalizedDocument:
    title: str
    content: str
    content_hash: str
    document_type: str = "web_page"
    metadata: dict[str, object] | None = None


class SourceCollector:
    """Base collector with extension points for future source-specific collectors."""

    def discover(self, company: Company) -> list[DiscoveredSource]:
        if not company.careers_url:
            return []
        return [DiscoveredSource(company.careers_url, "careers_page")]

    def fetch(self, source: DiscoveredSource, settings: Settings) -> FetchedSource:
        parsed = urlsplit(source.url)
        retrieved_at = datetime.now(UTC)
        if parsed.scheme == "file":
            path_text = unquote(parsed.path)
            if len(path_text) >= 3 and path_text[0] == "/" and path_text[2] == ":":
                path_text = path_text[1:]
            content = Path(path_text).read_bytes()
            suffix = Path(path_text).suffix.lower()
            content_type = "application/pdf" if suffix == ".pdf" else "text/html"
            return FetchedSource(source, content, content_type, 200, retrieved_at)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only http(s) and local file URLs are supported")
        if not self.robots_allowed(source.url, settings):
            raise PermissionError(f"robots.txt disallows fetching {source.url}")
        response = self._request(source.url, settings)
        content_type = response.headers.get("content-type", "").lower()
        if content_type and not any(
            value in content_type for value in ("text/", "html", "xml", "json", "pdf")
        ):
            raise ValueError(f"unsupported content type: {content_type}")
        return FetchedSource(
            source,
            response.content,
            content_type or "text/html",
            response.status_code,
            retrieved_at,
            dict(response.headers),
        )

    def robots_allowed(self, url: str, settings: Settings) -> bool:
        parsed = urlsplit(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            response = httpx.get(
                robots_url,
                headers={"User-Agent": settings.http_user_agent},
                timeout=min(settings.http_timeout_seconds, 10),
                follow_redirects=True,
            )
            if response.status_code in {401, 403}:
                return False
            if response.status_code >= 400:
                return True
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(response.text.splitlines())
            return parser.can_fetch(settings.http_user_agent, url)
        except httpx.HTTPError:
            return True

    def _request(self, url: str, settings: Settings) -> httpx.Response:
        host = urlsplit(url).netloc.lower()
        elapsed = time.monotonic() - _LAST_REQUEST_BY_HOST.get(host, 0.0)
        if elapsed < settings.http_per_host_delay_seconds:
            time.sleep(settings.http_per_host_delay_seconds - elapsed)
        last_error: Exception | None = None
        for attempt in range(settings.http_max_retries + 1):
            try:
                _LAST_REQUEST_BY_HOST[host] = time.monotonic()
                response = httpx.get(
                    url,
                    headers={"User-Agent": settings.http_user_agent, "Accept-Encoding": "gzip, br"},
                    timeout=settings.http_timeout_seconds,
                    follow_redirects=True,
                )
                if len(response.content) > settings.http_max_response_bytes:
                    raise ValueError("response exceeds configured maximum size")
                if response.status_code in {408, 425, 429} or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.HTTPStatusError,
                ValueError,
            ) as exc:
                last_error = exc
                if isinstance(exc, ValueError) or (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code < 500
                    and exc.response.status_code not in {408, 425, 429}
                ):
                    raise
                if attempt < settings.http_max_retries:
                    time.sleep(min(2**attempt, 4))
        raise RuntimeError(f"fetch failed after retries: {url}") from last_error

    def normalize(self, fetched: FetchedSource) -> NormalizedDocument:
        content_type = str(fetched.content_type).lower()
        if "pdf" in content_type or fetched.discovered.url.lower().split("?")[0].endswith(".pdf"):
            return self.normalize_pdf(fetched)
        soup = BeautifulSoup(fetched.content, "html.parser")
        for element in soup(["script", "style", "noscript", "svg"]):
            element.decompose()
        title = (
            (soup.title.get_text(" ", strip=True) if soup.title else None)
            or fetched.discovered.title
            or fetched.discovered.url
        )
        blocks: list[str] = []
        for element in soup.find_all(["h1", "h2", "h3", "p", "li", "td", "th"]):
            text = re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()
            if text and (not blocks or blocks[-1] != text):
                blocks.append(("- " if element.name == "li" else "") + text)
        metadata: dict[str, object] = {}
        for meta in soup.find_all("meta"):
            key = meta.get("property") or meta.get("name")
            value = meta.get("content")
            key_text = str(key) if key else ""
            if (
                key
                and value
                and key_text.lower()
                in {"author", "article:published_time", "og:site_name", "description"}
            ):
                metadata[key_text.lower()] = str(value)
        content = f"# {title}\n\n" + "\n\n".join(blocks)
        content = content.strip() + "\n"
        return NormalizedDocument(title, content, sha256_text(content), metadata=metadata)

    def normalize_pdf(self, fetched: FetchedSource) -> NormalizedDocument:
        try:
            import io

            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(fetched.content))
            pages: list[str] = []
            for index, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                pages.append(f"<!-- page: {index} -->\n\n{text}".strip())
            metadata = reader.metadata
            title = str(
                (metadata.title if metadata else None)
                or fetched.discovered.title
                or fetched.discovered.url
            )
            content = f"# {title}\n\n" + "\n\n".join(pages) + "\n"
            return NormalizedDocument(
                title, content, sha256_text(content), "pdf", {"page_count": len(reader.pages)}
            )
        except Exception as exc:
            raise ValueError(f"PDF normalization failed: {exc}") from exc


def persist_fetched_source(
    session: Session, company: Company | None, fetched: FetchedSource, settings: Settings
) -> tuple[ResearchSource, ResearchDocument, bool]:
    normalized = SourceCollector().normalize(fetched)
    canonical_url = canonicalize_url(fetched.discovered.url)
    source = session.query(ResearchSource).filter_by(canonical_url=canonical_url).one_or_none()
    source_hash = sha256_bytes(fetched.content)
    changed = source is None or source.content_hash != source_hash
    if source is None:
        source = ResearchSource(
            company=company,
            url=fetched.discovered.url,
            canonical_url=canonical_url,
            source_type=fetched.discovered.source_type,
            title=normalized.title,
            retrieved_at=fetched.retrieved_at,
            content_hash=source_hash,
            http_status=fetched.status_code,
            source_quality="unknown",
            metadata_=fetched.discovered.metadata or {},
        )
        session.add(source)
        session.flush()
    elif not changed:
        source.retrieved_at = fetched.retrieved_at
        source.last_fetched_at = fetched.retrieved_at
        document = (
            session.query(ResearchDocument)
            .filter_by(source_id=source.id, content_hash=normalized.content_hash)
            .one()
        )
        return source, document, False
    version = session.query(ResearchDocument).filter_by(source_id=source.id).count() + 1
    company_slug = company.slug if company else "unassigned"
    source_dir = settings.data_dir / "raw" / company_slug / str(source.id)
    normalized_dir = settings.data_dir / "normalized" / company_slug / str(source.id)
    source_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)
    extension = ".pdf" if "pdf" in str(fetched.content_type).lower() else ".html"
    raw_path = source_dir / f"{source_hash}{extension}"
    normalized_path = normalized_dir / f"v{version}-{normalized.content_hash}.md"
    if not raw_path.exists():
        raw_path.write_bytes(fetched.content)
    if not normalized_path.exists():
        normalized_path.write_text(normalized.content, encoding="utf-8")
    source.url = fetched.discovered.url
    source.source_type = fetched.discovered.source_type
    source.title = normalized.title
    source.retrieved_at = fetched.retrieved_at
    source.last_fetched_at = fetched.retrieved_at
    if changed:
        source.last_changed_at = fetched.retrieved_at
    source.content_hash = source_hash
    source.raw_path = str(raw_path)
    source.normalized_path = str(normalized_path)
    source.metadata_ = {**source.metadata_, **(fetched.discovered.metadata or {})}
    source.metadata_ = {**source.metadata_, **(normalized.metadata or {})}
    artifact = (
        session.query(SourceArtifact)
        .filter_by(source_id=source.id, content_hash=source_hash)
        .one_or_none()
    )
    if artifact is None:
        session.add(
            SourceArtifact(
                source=source,
                version=version,
                media_type=fetched.content_type or "application/octet-stream",
                content_hash=source_hash,
                byte_size=len(fetched.content),
                local_path=str(raw_path),
                retrieved_at=fetched.retrieved_at,
                response_headers=fetched.headers or {},
                metadata_=normalized.metadata or {},
            )
        )
    document = ResearchDocument(
        source=source,
        company_id=company.id if company else None,
        document_type=normalized.document_type,
        title=normalized.title,
        content=normalized.content,
        markdown_path=str(normalized_path),
        content_hash=normalized.content_hash,
        version=version,
        generated_at=fetched.retrieved_at,
    )
    session.add(document)
    session.flush()
    return source, document, changed


def persist_fetch_error(
    session: Session,
    url: str,
    error: Exception,
    *,
    operation: str = "fetch",
    source: ResearchSource | None = None,
    retryable: bool = False,
) -> FetchError:
    item = FetchError(
        source=source,
        url=url,
        operation=operation,
        occurred_at=datetime.now(UTC),
        error_type=type(error).__name__,
        message=str(error),
        retryable=retryable,
    )
    session.add(item)
    session.flush()
    return item
