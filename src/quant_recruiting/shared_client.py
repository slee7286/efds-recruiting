"""Transport-neutral clients for shared recruiting intelligence."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Protocol

import httpx

from quant_recruiting.config import Settings, get_settings
from quant_recruiting.shared_api.schemas import (
    ApiVersionV1,
    SyncChangesV1,
    SyncManifestV1,
)
from quant_recruiting.storage import get_shared_session


class SharedClientError(RuntimeError):
    """A recoverable or user-actionable shared service failure."""


class SharedIntelligenceClient(Protocol):
    def manifest(self) -> SyncManifestV1: ...

    def changes(self, since: datetime | None = None, *, limit: int = 500) -> SyncChangesV1: ...

    def version(self) -> ApiVersionV1: ...


class HTTPSharedIntelligenceClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if not self.settings.shared_api_url:
            raise SharedClientError("SHARED_API_URL is required when SHARED_TRANSPORT=api")
        self.base_url = self.settings.shared_api_url.rstrip("/")
        self.transport = transport
        self._etag: str | None = None
        self._manifest: SyncManifestV1 | None = None

    def _request(self, path: str, params: dict[str, str | int] | None = None) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if path.endswith("/sync/manifest") and self._etag:
            headers["If-None-Match"] = self._etag
        attempts = max(0, self.settings.shared_api_max_retries) + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                with httpx.Client(
                    base_url=self.base_url,
                    timeout=self.settings.shared_api_timeout_seconds,
                    follow_redirects=True,
                    transport=self.transport,
                ) as client:
                    response = client.get(path, params=params, headers=headers)
                if response.status_code == 304:
                    return response
                if response.status_code >= 500 and attempt + 1 < attempts:
                    time.sleep(min(2**attempt * 0.2, 2.0))
                    continue
                if response.status_code >= 400:
                    raise SharedClientError(
                        f"shared API returned HTTP {response.status_code}: {response.text[:200]}"
                    )
                return response
            except (httpx.HTTPError, SharedClientError) as exc:
                last_error = exc
                if attempt + 1 < attempts and not isinstance(exc, SharedClientError):
                    time.sleep(min(2**attempt * 0.2, 2.0))
                    continue
                raise SharedClientError(str(exc)) from exc
        raise SharedClientError(str(last_error or "shared API request failed"))

    def manifest(self) -> SyncManifestV1:
        response = self._request("/api/v1/sync/manifest")
        if response.status_code == 304 and self._manifest is not None:
            return self._manifest
        try:
            result = SyncManifestV1.model_validate(response.json())
        except ValueError as exc:
            raise SharedClientError("shared API returned an invalid sync manifest") from exc
        self._etag = response.headers.get("etag")
        self._manifest = result
        return result

    def changes(self, since: datetime | None = None, *, limit: int = 500) -> SyncChangesV1:
        params: dict[str, str | int] = {"limit": min(max(limit, 1), 500)}
        if since:
            params["since"] = since.isoformat()
        response = self._request("/api/v1/sync/changes", params)
        try:
            return SyncChangesV1.model_validate(response.json())
        except ValueError as exc:
            raise SharedClientError("shared API returned invalid sync changes") from exc

    def version(self) -> ApiVersionV1:
        response = self._request("/api/v1/version")
        try:
            return ApiVersionV1.model_validate(response.json())
        except ValueError as exc:
            raise SharedClientError("shared API returned an invalid version response") from exc


class PostgresSharedIntelligenceClient:
    """Developer/admin transport retaining V8 direct PostgreSQL behavior."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def manifest(self) -> SyncManifestV1:
        from quant_recruiting.shared_api.app import _manifest

        return _manifest(self.settings)

    def changes(self, since: datetime | None = None, *, limit: int = 500) -> SyncChangesV1:
        from quant_recruiting.shared_api.app import _changes_from_session

        with get_shared_session(self.settings) as session:
            return _changes_from_session(session, since=since, limit=limit)

    def version(self) -> ApiVersionV1:
        from quant_recruiting.shared_api.app import _manifest

        return ApiVersionV1(dataset_version=_manifest(self.settings).dataset_version)


def get_shared_client(settings: Settings | None = None) -> SharedIntelligenceClient:
    config = settings or get_settings()
    if config.shared_transport == "postgres":
        return PostgresSharedIntelligenceClient(config)
    if config.shared_transport != "api":
        raise SharedClientError(f"unsupported shared transport: {config.shared_transport}")
    return HTTPSharedIntelligenceClient(config)
