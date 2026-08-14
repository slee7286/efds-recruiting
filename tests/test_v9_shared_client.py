from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from quant_recruiting.config import Settings
from quant_recruiting.shared_client import HTTPSharedIntelligenceClient


def test_http_shared_client_validates_manifest_changes_and_304() -> None:
    with TemporaryDirectory() as directory:
        settings = Settings(
            local_data_dir=Path(directory),
            shared_api_url="https://shared.example.test",
            shared_transport="api",
        )
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path.endswith("/version"):
                return httpx.Response(
                    200,
                    json={
                        "api_version": "v1",
                        "client_minimum": "0.3.0",
                        "client_latest": "0.3.0",
                        "dataset_version": "dataset-1",
                        "schema_version": 1,
                    },
                )
            if request.url.path.endswith("/sync/manifest"):
                if request.headers.get("if-none-match") == '"dataset-1"':
                    return httpx.Response(304, headers={"ETag": '"dataset-1"'})
                return httpx.Response(
                    200,
                    headers={"ETag": '"dataset-1"'},
                    json={
                        "schema_version": 1,
                        "dataset_version": "dataset-1",
                        "generated_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - Python 3.10 compatibility
                        "collections": {},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "schema_version": 1,
                    "changes": [
                        {
                            "collection": "companies",
                            "operation": "upsert",
                            "entity_id": "company-1",
                            "version": "2026-01-01T00:00:00+00:00",
                            "updated_at": "2026-01-01T00:00:00+00:00",
                            "content_hash": "hash",
                            "payload": {"slug": "example", "name": "Example"},
                        }
                    ],
                    "next_cursor": None,
                },
            )

        client = HTTPSharedIntelligenceClient(settings, transport=httpx.MockTransport(handler))
        assert client.version().api_version == "v1"
        assert client.manifest().dataset_version == "dataset-1"
        assert client.manifest().dataset_version == "dataset-1"
        assert client.changes().changes[0].entity_id == "company-1"
        assert any(request.headers.get("if-none-match") == '"dataset-1"' for request in seen)
