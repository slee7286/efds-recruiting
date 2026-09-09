"""Bounded public ATS capture followed by the offline opportunity digest.

This module is deliberately separate from the database-backed collectors.  It
fetches only manifest-declared public pages, preserves the exact response
bytes, and hands a normalized capture manifest to :mod:`opportunity_digest`.
No credentials, cookies, database sessions, browser automation, or Factory
services are used here.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from quant_recruiting.ats import adapter_for
from quant_recruiting.jobs import classify_role, extract_internship_cycle
from quant_recruiting.opportunity_digest import (
    build_opportunity_digest,
    render_digest_json,
    render_digest_markdown,
    run_fixture_digest,
)

SCHEMA_VERSION = "efds-public-opportunity-batch-v1"
PARSER_VERSION = "efds-public-opportunity-parser-v1"
POLICY_ID = "efds-public-opportunity-policy-v1"
UTC = UTC
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_SAFE_HEADERS = {
    "cache-control",
    "content-length",
    "content-type",
    "etag",
    "last-modified",
    "location",
    "retry-after",
}
_RELEVANT_ROLE_FAMILIES = {
    "quantitative_research",
    "quantitative_trading",
    "investment_banking",
    "equity_research",
    "sales_and_trading",
    "asset_management",
    "machine_learning",
    "data_science",
    "software_engineering",
    "trading",
    "research",
}


class PublicBatchError(ValueError):
    """Raised when the bounded public batch cannot safely proceed."""


@dataclass(frozen=True)
class CollectionLimits:
    max_sources: int = 5
    max_requests: int = 75
    max_total_bytes: int = 50 * 1024 * 1024
    max_response_bytes: int = 2 * 1024 * 1024
    min_host_interval_seconds: float = 2.0
    request_timeout_seconds: float = 20.0
    wall_clock_seconds: float = 15 * 60
    max_retries: int = 2
    max_pages_per_source: int = 10


@dataclass(frozen=True)
class PublicSource:
    source_id: str
    firm: str
    official_careers_url: str
    endpoint_url: str
    provider: str
    board_id: str
    allowed_hosts: tuple[str, ...]
    board_evidence: str
    adapter: str
    pagination: str
    observed_at_utc: str

    @classmethod
    def from_mapping(cls, value: Any) -> PublicSource:
        if type(value) is not dict:
            raise PublicBatchError("source must be an object")
        required = {
            "source_id",
            "firm",
            "official_careers_url",
            "endpoint_url",
            "provider",
            "board_id",
            "allowed_hosts",
            "board_evidence",
            "adapter",
            "pagination",
            "observed_at_utc",
        }
        if set(value) != required:
            raise PublicBatchError(
                f"source keys must be exactly {', '.join(sorted(required))}"
            )
        strings = (
            "source_id",
            "firm",
            "official_careers_url",
            "endpoint_url",
            "provider",
            "board_id",
            "board_evidence",
            "adapter",
            "pagination",
            "observed_at_utc",
        )
        for key in strings:
            if type(value[key]) is not str or not value[key].strip():
                raise PublicBatchError(f"source.{key} must be a non-empty string")
        if type(value["allowed_hosts"]) is not list or not value["allowed_hosts"]:
            raise PublicBatchError("source.allowed_hosts must be a non-empty array")
        hosts: list[str] = []
        for host in value["allowed_hosts"]:
            if type(host) is not str or not host.strip() or host != host.lower():
                raise PublicBatchError("source.allowed_hosts must contain lowercase hosts")
            hosts.append(host.strip())
        _validate_public_url(value["official_careers_url"], set(hosts))
        _validate_public_url(value["endpoint_url"], set(hosts))
        if value["provider"] != value["adapter"]:
            raise PublicBatchError("source.provider and source.adapter must match")
        _validate_timestamp(value["observed_at_utc"], "source.observed_at_utc")
        return cls(
            source_id=value["source_id"].strip(),
            firm=value["firm"].strip(),
            official_careers_url=value["official_careers_url"],
            endpoint_url=value["endpoint_url"],
            provider=value["provider"],
            board_id=value["board_id"].strip(),
            allowed_hosts=tuple(sorted(set(hosts))),
            board_evidence=value["board_evidence"].strip(),
            adapter=value["adapter"].strip(),
            pagination=value["pagination"].strip(),
            observed_at_utc=value["observed_at_utc"],
        )


@dataclass(frozen=True)
class PublicBatchManifest:
    batch_id: str
    scope: str
    sources: tuple[PublicSource, ...]
    limits: CollectionLimits

    @classmethod
    def from_mapping(cls, value: Any) -> PublicBatchManifest:
        if type(value) is not dict:
            raise PublicBatchError("batch manifest must be an object")
        required = {"schema_version", "batch_id", "scope", "limits", "sources"}
        if set(value) != required:
            raise PublicBatchError("batch manifest has unexpected or missing fields")
        if value["schema_version"] != SCHEMA_VERSION:
            raise PublicBatchError("unsupported batch manifest schema_version")
        if any(
            type(value[key]) is not str or not value[key].strip()
            for key in ("batch_id", "scope")
        ):
            raise PublicBatchError("batch_id and scope must be non-empty strings")
        limits = _limits_from_mapping(value["limits"])
        raw_sources = value["sources"]
        if type(raw_sources) is not list or not raw_sources:
            raise PublicBatchError("sources must be a non-empty array")
        if len(raw_sources) > limits.max_sources:
            raise PublicBatchError("source count exceeds max_sources")
        sources = tuple(PublicSource.from_mapping(item) for item in raw_sources)
        source_ids = [source.source_id for source in sources]
        if len(set(source_ids)) != len(source_ids):
            raise PublicBatchError("source_id values must be unique")
        return cls(value["batch_id"].strip(), value["scope"].strip(), sources, limits)

    def as_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "batch_id": self.batch_id,
            "scope": self.scope,
            "limits": asdict(self.limits),
            "sources": [
                {
                    "source_id": source.source_id,
                    "firm": source.firm,
                    "official_careers_url": source.official_careers_url,
                    "endpoint_url": source.endpoint_url,
                    "provider": source.provider,
                    "board_id": source.board_id,
                    "allowed_hosts": list(source.allowed_hosts),
                    "board_evidence": source.board_evidence,
                    "adapter": source.adapter,
                    "pagination": source.pagination,
                    "observed_at_utc": source.observed_at_utc,
                }
                for source in self.sources
            ],
        }


@dataclass(frozen=True)
class _ResponseCapture:
    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    attempts: int

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _read_json(path: Path) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PublicBatchError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except OSError as exc:
        raise PublicBatchError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PublicBatchError(f"invalid JSON in {path}: {exc.msg}") from exc


def _validate_timestamp(value: str, context: str) -> None:
    if not value.endswith("Z"):
        raise PublicBatchError(f"{context} must have UTC Z suffix")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PublicBatchError(f"{context} is not an ISO timestamp") from exc


def _limits_from_mapping(value: Any) -> CollectionLimits:
    if type(value) is not dict:
        raise PublicBatchError("limits must be an object")
    defaults = asdict(CollectionLimits())
    if set(value) != set(defaults):
        raise PublicBatchError("limits must contain the complete known limit set")
    for key, default in defaults.items():
        if type(value[key]) is not type(default) or value[key] <= 0:
            raise PublicBatchError(f"limits.{key} must be a positive {type(default).__name__}")
    if value["max_sources"] > 5 or value["max_requests"] > 75:
        raise PublicBatchError("manifest exceeds authorized collection ceiling")
    if value["max_total_bytes"] > 50 * 1024 * 1024 or value["max_response_bytes"] > 2 * 1024 * 1024:
        raise PublicBatchError("manifest exceeds authorized byte ceiling")
    if value["min_host_interval_seconds"] < 2.0:
        raise PublicBatchError("manifest cannot reduce the two-second host interval")
    if value["request_timeout_seconds"] > 20.0 or value["wall_clock_seconds"] > 15 * 60:
        raise PublicBatchError("manifest exceeds authorized timeout ceiling")
    if value["max_retries"] > 2:
        raise PublicBatchError("manifest exceeds authorized retry ceiling")
    return CollectionLimits(**value)


def _validate_public_url(value: str, allowed_hosts: set[str]) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise PublicBatchError("URL must be credential-free HTTP(S)")
    host = (parsed.hostname or "").lower()
    if not host:
        raise PublicBatchError("URL host is not in the verified allowlist: <missing>")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise PublicBatchError("local destination is not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise PublicBatchError("private or local destination is not allowed")
    if host not in allowed_hosts:
        raise PublicBatchError(f"URL host is not in the verified allowlist: {host}")
    return value


def _safe_headers(headers: httpx.Headers) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() in _SAFE_HEADERS}


def _retry_after(headers: dict[str, str]) -> float:
    value = headers.get("retry-after", "")
    try:
        return max(0.0, float(value))
    except ValueError:
        return 0.0


class _BoundedFetcher:
    def __init__(
        self,
        client: httpx.Client,
        limits: CollectionLimits,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.limits = limits
        self.clock = clock
        self.sleeper = sleeper
        self.started = clock()
        self.requests = 0
        self.total_bytes = 0
        self.last_host_at: dict[str, float] = {}

    def _budget(self) -> None:
        if self.requests >= self.limits.max_requests:
            raise PublicBatchError("request budget exhausted")
        if self.total_bytes >= self.limits.max_total_bytes:
            raise PublicBatchError("download budget exhausted")
        if self.clock() - self.started > self.limits.wall_clock_seconds:
            raise PublicBatchError("collection wall-clock budget exhausted")

    def fetch(self, url: str, allowed_hosts: set[str]) -> _ResponseCapture:
        current_url = url
        attempts = 0
        while True:
            _validate_public_url(current_url, allowed_hosts)
            host = (urlsplit(current_url).hostname or "").lower()
            previous = self.last_host_at.get(host)
            if previous is not None:
                delay = self.limits.min_host_interval_seconds - (self.clock() - previous)
                if delay > 0:
                    if self.clock() - self.started + delay > self.limits.wall_clock_seconds:
                        raise PublicBatchError("host delay exceeds remaining wall-clock budget")
                    self.sleeper(delay)
            self._budget()
            self.last_host_at[host] = self.clock()
            self.requests += 1
            attempts += 1
            try:
                response_context = self.client.stream(
                    "GET",
                    current_url,
                    follow_redirects=False,
                    timeout=self.limits.request_timeout_seconds,
                )
                with response_context as response:
                    headers = _safe_headers(response.headers)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise PublicBatchError("redirect has no Location header")
                        current_url = urljoin(current_url, location)
                        if attempts > self.limits.max_retries + 1:
                            raise PublicBatchError("redirect/retry request budget exhausted")
                        continue
                    if response.status_code in {401, 403}:
                        raise PublicBatchError(
                            f"access denied fetching {current_url}: {response.status_code}"
                        )
                    if (
                        response.status_code in _RETRYABLE_STATUS
                        and attempts <= self.limits.max_retries
                    ):
                        delay = _retry_after(headers)
                        if self.clock() - self.started + delay > self.limits.wall_clock_seconds:
                            raise PublicBatchError(
                                "Retry-After exceeds remaining wall-clock budget"
                            )
                        if delay:
                            self.sleeper(delay)
                        continue
                    if response.status_code >= 400:
                        raise PublicBatchError(f"source returned HTTP {response.status_code}")
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_length = int(content_length)
                        except ValueError as exc:
                            raise PublicBatchError("response has malformed Content-Length") from exc
                        if declared_length > self.limits.max_response_bytes:
                            raise PublicBatchError("response exceeds per-response byte budget")
                        if declared_length > self.limits.max_total_bytes - self.total_bytes:
                            raise PublicBatchError("response exceeds total download byte budget")
                    chunks: list[bytes] = []
                    response_bytes = 0
                    for chunk in response.iter_bytes():
                        response_bytes += len(chunk)
                        if response_bytes > self.limits.max_response_bytes:
                            raise PublicBatchError("response exceeds per-response byte budget")
                        if response_bytes > self.limits.max_total_bytes - self.total_bytes:
                            raise PublicBatchError("response exceeds total download byte budget")
                        chunks.append(chunk)
                    body = b"".join(chunks)
            except httpx.TimeoutException as exc:
                if attempts <= self.limits.max_retries:
                    continue
                raise PublicBatchError(f"timeout fetching {current_url}") from exc
            except httpx.HTTPError as exc:
                raise PublicBatchError(f"HTTP failure fetching {current_url}: {exc}") from exc
            self.total_bytes += len(body)
            return _ResponseCapture(url, current_url, response.status_code, headers, body, attempts)


def _capture_metadata(response: _ResponseCapture) -> dict[str, Any]:
    return {
        "requested_url": response.requested_url,
        "final_url": response.final_url,
        "status_code": response.status_code,
        "headers": response.headers,
        "body_bytes": len(response.body),
        "body_sha256": response.body_sha256,
        "attempts": response.attempts,
    }


def _write_capture(root: Path, name: str, response: _ResponseCapture) -> dict[str, Any]:
    body_path = root / f"{name}.bin"
    body_path.write_bytes(response.body)
    metadata = _capture_metadata(response)
    _write_json(root / f"{name}.metadata.json", metadata)
    # Keep the digest input relocatable: the durable report records the file
    # beside this metadata, while the digest identity must not depend on the
    # absolute machine-specific output directory.
    metadata["body_file"] = body_path.name
    return metadata


def _sentence(text: str, terms: tuple[str, ...]) -> str | None:
    for part in re.split(r"(?<=[.!?])\s+", text):
        if any(term in part.lower() for term in terms):
            return " ".join(part.split())
    return None


def _clean_description(value: str) -> str:
    return BeautifulSoup(unescape(value), "html.parser").get_text(" ", strip=True)


def _programme_year(text: str) -> tuple[str | None, str | None]:
    year_match = re.search(r"\b(20(?:2[5-9]|3\d))\b", text)
    if year_match:
        return year_match.group(1), year_match.group(0)
    return None, None


def _eligibility_claims(text: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    dimensions = {
        "graduation": ("graduate", "class of", "degree", "graduating"),
        "work_authorization": ("right to work", "work authorization", "work authorisation"),
        "sponsorship": ("sponsor", "visa", "sponsorship"),
    }
    for dimension, terms in dimensions.items():
        sentence = _sentence(text, terms)
        if sentence is None:
            continue
        lowered = sentence.lower()
        status = (
            "required"
            if any(word in lowered for word in ("must", "required", "eligible"))
            else "unknown"
        )
        if any(
            word in lowered for word in ("no sponsorship", "without sponsorship", "not required")
        ):
            status = "not_required"
        value = {"dimension": dimension, "status": status, "detail": sentence}
        claims.append(value)
    return claims


def _primary_eligibility_claim(
    claims: list[dict[str, Any]],
) -> tuple[int, dict[str, Any]] | None:
    """Choose the single v1 eligibility fact while retaining all claims in raw input.

    Graduation is the most useful first-class digest fact for this batch.  Work
    authorization and sponsorship statements are compatible dimensions, not
    contradictory values for the same v1 field, so they remain available in
    the saved normalized record and human-review packet rather than being
    incorrectly collapsed into a conflict.
    """

    priority = {"graduation": 0, "work_authorization": 1, "sponsorship": 2}
    if not claims:
        return None

    def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        dimension = item[1].get("dimension")
        if not isinstance(dimension, str):
            dimension = ""
        return priority.get(dimension, 99), item[0]

    return min(enumerate(claims), key=sort_key)


def _claim(
    value: Any, source_id: str, record_id: str, field: str, locator: str
) -> dict[str, Any]:
    quote = (
        value
        if isinstance(value, str)
        else json.dumps(value, separators=(",", ":"), sort_keys=True)
    )
    return {
        "value": value,
        "evidence": [
            {
                "source_id": source_id,
                "record_id": record_id,
                "field": field,
                "locator": locator,
                "quote": quote,
            }
        ],
    }


def _record_from_posting(
    source: PublicSource,
    payload: dict[str, Any],
    config: Any,
    source_meta: dict[str, Any],
) -> dict[str, Any]:
    adapter = adapter_for(source.adapter)
    posting = adapter.normalize_job(payload, config)
    fallback_id = hashlib.sha256(posting.url.encode()).hexdigest()[:12]
    record_id = f"{source.source_id}-{posting.external_id or fallback_id}"
    description = _clean_description(posting.description)
    cycle, cycle_wording = extract_internship_cycle(f"{posting.title} {description}")
    if cycle is None:
        cycle, cycle_wording = _programme_year(f"{posting.title} {description}")
    role_family, _confidence = classify_role(posting.title, description)
    text = f"{posting.title} {description}".lower()
    is_insight = "insight" in text
    is_internship = "intern" in text or "placement" in text
    location = posting.location_text
    location_lower = location.lower() if location else ""
    uk_terms = ("london", "united kingdom", "uk", "england", "scotland", "wales", "edinburgh")
    clearly_non_uk = bool(location and not any(term in location_lower for term in uk_terms))
    if role_family not in _RELEVANT_ROLE_FAMILIES:
        status = "irrelevant"
        reason = "role_out_of_scope"
    elif clearly_non_uk:
        status = "irrelevant"
        reason = "location_out_of_scope"
    elif not (is_insight or is_internship):
        status = "irrelevant"
        reason = "programme_type_out_of_scope"
    else:
        status = "included"
        reason = None
    raw_payload: dict[str, Any] = {
        "provider_payload": payload,
        "source_context": {
            "firm": source.firm,
            "official_careers_url": source.official_careers_url,
            "board_evidence": source.board_evidence,
        },
        "derived": {
            "role": posting.title,
            "location": posting.location_text,
            "job_url": posting.url,
            "application_url": posting.url,
            "deadline": posting.valid_through.date().isoformat() if posting.valid_through else None,
            "program": {
                "category": "insight_programme" if is_insight else "internship",
                "year": cycle,
                "wording": cycle_wording,
            },
            "description": description,
            "eligibility_claims": _eligibility_claims(description),
        },
        "capture": source_meta,
    }
    facts: dict[str, list[dict[str, Any]]] = {
        "firm": [
            _claim(source.firm, source.source_id, record_id, "firm", "/source_context/firm")
        ],
        "role": [_claim(posting.title, source.source_id, record_id, "role", "/derived/role")],
        "job_url": [
            _claim(posting.url, source.source_id, record_id, "job_url", "/derived/job_url")
        ],
        "application_url": [
            _claim(
                posting.url,
                source.source_id,
                record_id,
                "application_url",
                "/derived/application_url",
            )
        ],
    }
    if posting.location_text:
        facts["location"] = [
            _claim(
                posting.location_text,
                source.source_id,
                record_id,
                "location",
                "/derived/location",
            )
        ]
    if raw_payload["derived"]["deadline"]:
        facts["deadline"] = [
            _claim(
                raw_payload["derived"]["deadline"],
                source.source_id,
                record_id,
                "deadline",
                "/derived/deadline",
            )
        ]
    eligibility_claims = raw_payload["derived"]["eligibility_claims"]
    primary_eligibility = _primary_eligibility_claim(eligibility_claims)
    if primary_eligibility is not None:
        index, value = primary_eligibility
        facts["eligibility"] = [
            _claim(
                value,
                source.source_id,
                record_id,
                "eligibility",
                f"/derived/eligibility_claims/{index}",
            )
        ]
    result: dict[str, Any] = {
        "record_id": record_id,
        "record_status": status,
        "external_id": posting.external_id,
        "raw_payload": raw_payload,
    }
    if reason:
        result["exclusion_reason"] = reason
    else:
        result["facts"] = facts
    return result


def _collection_report(
    manifest: PublicBatchManifest,
    fetcher: _BoundedFetcher,
    started: str,
    finished: str,
    outcomes: list[dict[str, Any]],
    *,
    digest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "batch_id": manifest.batch_id,
        "started_at_utc": started,
        "finished_at_utc": finished,
        "limits": asdict(manifest.limits),
        "requests": fetcher.requests,
        "downloaded_bytes": fetcher.total_bytes,
        "elapsed_seconds": max(0.0, fetcher.clock() - fetcher.started),
        "sources": outcomes,
        "digest_status": (
            digest["status"] if digest is not None else "capture_collected_not_rendered"
        ),
        "digest_id": digest["digest_id"] if digest is not None else None,
        "code": {
            "module": "quant_recruiting.public_opportunity_batch",
            "version": PARSER_VERSION,
        },
    }


def collect_public_batch(
    manifest_path: str | Path,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
    client: httpx.Client | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Collect one bounded batch and render its digest from saved captures."""

    manifest = PublicBatchManifest.from_mapping(_read_json(Path(manifest_path)))
    output = Path(output_dir)
    if output.exists() and not overwrite:
        existing = {item.name for item in output.iterdir()}
        if existing != {"source-manifest.json"}:
            raise PublicBatchError(
                "batch output directory is not empty; choose a new directory or --overwrite"
            )
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "source-manifest.json", manifest.as_mapping())
    captures_root = output / "captures"
    captures_root.mkdir(exist_ok=True)
    owns_client = client is None
    http_client = client or httpx.Client(
        trust_env=False, headers={"User-Agent": "efds-recruiting-public-batch/1"}
    )
    fetcher = _BoundedFetcher(http_client, manifest.limits, clock=clock, sleeper=sleeper)
    started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sources: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    try:
        for source in manifest.sources:
            source_dir = captures_root / source.source_id
            source_dir.mkdir(exist_ok=True)
            source_base: dict[str, Any] = {
                "source_id": source.source_id,
                "provider": source.provider,
                "board_id": source.board_id,
                "source_url": source.endpoint_url,
                "observed_at_utc": source.observed_at_utc,
                "records": [],
            }
            try:
                official = fetcher.fetch(source.official_careers_url, set(source.allowed_hosts))
                official_meta = _write_capture(source_dir, "official", official)
                board = fetcher.fetch(source.endpoint_url, set(source.allowed_hosts))
                board_meta = _write_capture(source_dir, "board-page-1", board)
                try:
                    payload = json.loads(board.body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise PublicBatchError(f"ATS response is not valid JSON: {exc}") from exc
                if source.provider == "greenhouse":
                    raw_jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
                elif source.provider == "ashby":
                    raw_jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
                else:
                    raw_jobs = payload if isinstance(payload, list) else []
                if not isinstance(raw_jobs, list):
                    raise PublicBatchError("ATS jobs payload is not an array")
                if len(raw_jobs) > manifest.limits.max_pages_per_source * 500:
                    source_base["capture_status"] = "truncated"
                    source_base["error"] = "record count exceeded declared pagination ceiling"
                else:
                    source_base["capture_status"] = "complete"
                config = SimpleNamespace(
                    board_identifier=source.board_id, board_url=source.endpoint_url
                )
                capture_meta = {
                    "official": official_meta,
                    "board": board_meta,
                }
                for index, payload_item in enumerate(raw_jobs):
                    if not isinstance(payload_item, dict):
                        source_base["records"].append(
                            {
                                "record_id": f"{source.source_id}-malformed-{index}",
                                "record_status": "malformed",
                                "exclusion_reason": "provider_record_not_an_object",
                                "raw_payload": {"provider_record": payload_item},
                            }
                        )
                        continue
                    source_base["records"].append(
                        _record_from_posting(source, payload_item, config, capture_meta)
                    )
            except (PublicBatchError, httpx.HTTPError, ValueError) as exc:
                source_base["capture_status"] = "failed"
                source_base["error"] = str(exc)
                source_base["records"] = []
            sources.append(source_base)
            outcomes.append(
                {
                    "source_id": source.source_id,
                    "status": source_base["capture_status"],
                    "record_count": len(source_base["records"]),
                    "error": source_base.get("error"),
                }
            )
    finally:
        if owns_client:
            http_client.close()
    capture_manifest: dict[str, Any] = {
        "schema_version": "efds-opportunity-capture-v1",
        "parser_version": PARSER_VERSION,
        "policy_id": POLICY_ID,
        "expected_sources": [source.source_id for source in manifest.sources],
        "sources": sources,
    }
    input_path = output / "digest-input.json"
    _write_json(input_path, capture_manifest)
    digest_output = output / "digest"
    digest_output.mkdir(exist_ok=True)
    finished = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_json(
        output / "collection-report.json",
        _collection_report(manifest, fetcher, started, finished, outcomes),
    )
    result = build_opportunity_digest(capture_manifest)
    json_path = digest_output / "opportunity-digest.json"
    markdown_path = digest_output / "opportunity-digest.md"
    json_path.write_text(render_digest_json(result), encoding="utf-8")
    markdown_path.write_text(render_digest_markdown(result), encoding="utf-8")
    report = _collection_report(manifest, fetcher, started, finished, outcomes, digest=result)
    _write_json(output / "collection-report.json", report)
    (output / "review-notes.md").write_text(
        "# Public opportunity batch review notes\n\n"
        "This batch is a bounded capture of the manifest-declared public employer/ATS sources. "
        "Review each included opportunity against the saved capture bytes before treating it "
        "as useful.\n",
        encoding="utf-8",
    )
    return {"output_dir": output, "input_path": input_path, "digest": result, "report": report}


def replay_public_batch(
    input_path: str | Path, output_dir: str | Path
) -> tuple[Path, Path, dict[str, Any]]:
    """Replay a saved digest input without network access."""

    return run_fixture_digest(input_path, output_dir)


def replay_saved_captures(
    batch_dir: str | Path, output_dir: str | Path | None = None
) -> dict[str, Any]:
    """Rebuild the normalized input and digest from one saved batch's bytes."""

    source_batch = Path(batch_dir)
    batch = Path(output_dir) if output_dir is not None else source_batch
    manifest = PublicBatchManifest.from_mapping(
        _read_json(source_batch / "source-manifest.json")
    )
    previous = _read_json(source_batch / "digest-input.json")
    previous_sources = {item["source_id"]: item for item in previous["sources"]}
    sources: list[dict[str, Any]] = []
    for source in manifest.sources:
        previous_source = previous_sources.get(source.source_id)
        source_dir = source_batch / "captures" / source.source_id
        board_path = source_dir / "board-page-1.bin"
        if previous_source is None or not board_path.exists():
            if previous_source is not None:
                sources.append(previous_source)
            continue
        try:
            payload = json.loads(board_path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicBatchError(
                f"saved ATS capture is unusable for {source.source_id}: {exc}"
            ) from exc
        if source.provider in {"greenhouse", "ashby"}:
            raw_jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        else:
            raw_jobs = payload if isinstance(payload, list) else []
        if not isinstance(raw_jobs, list):
            raise PublicBatchError(f"saved ATS jobs payload is not an array for {source.source_id}")
        official_meta = _read_json(source_dir / "official.metadata.json")
        board_meta = _read_json(source_dir / "board-page-1.metadata.json")
        official_meta["body_file"] = "official.bin"
        board_meta["body_file"] = "board-page-1.bin"
        config = SimpleNamespace(board_identifier=source.board_id, board_url=source.endpoint_url)
        records = [
            _record_from_posting(
                source,
                payload_item,
                config,
                {"official": official_meta, "board": board_meta},
            )
            for payload_item in raw_jobs
            if isinstance(payload_item, dict)
        ]
        rebuilt = {
            "source_id": source.source_id,
            "provider": source.provider,
            "board_id": source.board_id,
            "source_url": source.endpoint_url,
            "observed_at_utc": source.observed_at_utc,
            "capture_status": previous_source["capture_status"],
            "records": records,
        }
        if previous_source.get("error") is not None:
            rebuilt["error"] = previous_source["error"]
        sources.append(rebuilt)
    capture_manifest: dict[str, Any] = {
        "schema_version": "efds-opportunity-capture-v1",
        "parser_version": PARSER_VERSION,
        "policy_id": POLICY_ID,
        "expected_sources": [source.source_id for source in manifest.sources],
        "sources": sources,
    }
    batch.mkdir(parents=True, exist_ok=True)
    _write_json(batch / "source-manifest.json", manifest.as_mapping())
    _write_json(batch / "digest-input.json", capture_manifest)
    result = build_opportunity_digest(capture_manifest)
    digest_dir = batch / "digest"
    digest_dir.mkdir(exist_ok=True)
    (digest_dir / "opportunity-digest.json").write_text(
        render_digest_json(result), encoding="utf-8"
    )
    (digest_dir / "opportunity-digest.md").write_text(
        render_digest_markdown(result), encoding="utf-8"
    )
    request_count = 0
    downloaded_bytes = 0
    for source in manifest.sources:
        source_dir = batch / "captures" / source.source_id
        for name in ("official.bin", "board-page-1.bin"):
            path = source_dir / name
            if path.exists():
                request_count += 1
                downloaded_bytes += path.stat().st_size
    replay_report = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": manifest.batch_id,
        "started_at_utc": None,
        "finished_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "timing_note": (
            "Original collection timing was unavailable because the first implementation "
            "failed during digest construction before its report was written; this report "
            "describes the saved-capture replay, not a new network collection."
        ),
        "limits": asdict(manifest.limits),
        "requests": request_count,
        "downloaded_bytes": downloaded_bytes,
        "elapsed_seconds": None,
        "sources": [
            {
                "source_id": source["source_id"],
                "status": source["capture_status"],
                "record_count": len(source["records"]),
                "error": source.get("error"),
            }
            for source in capture_manifest["sources"]
        ],
        "digest_status": result["status"],
        "digest_id": result["digest_id"],
        "replayed_from_saved_captures": True,
        "code": {
            "module": "quant_recruiting.public_opportunity_batch",
            "version": PARSER_VERSION,
        },
    }
    _write_json(batch / "collection-report.json", replay_report)
    (batch / "review-notes.md").write_text(
        "# Public opportunity batch review notes\n\n"
        "The digest was regenerated from the saved official-page and ATS response bytes. "
        "The first collection reached both verified Greenhouse endpoints but failed during "
        "digest construction because an extraction evidence locator was incorrect; no second "
        "network collection was used. Review every included opportunity against its saved bytes.\n",
        encoding="utf-8",
    )
    return {"output_dir": batch, "input_path": batch / "digest-input.json", "digest": result}


def manifest_template(path: str | Path) -> None:
    """Write a small explicit template for a human-reviewed source manifest."""

    value = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": "efds-public-batch-YYYYMMDD",
        "scope": (
            "UK undergraduate-relevant finance and technology internships and insight programmes"
        ),
        "limits": asdict(CollectionLimits()),
        "sources": [],
    }
    _write_json(Path(path), value)
