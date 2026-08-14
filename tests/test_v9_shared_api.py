from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from quant_recruiting.config import Settings
from quant_recruiting.db.base import Base
from quant_recruiting.db.models import Company, Job
from quant_recruiting.shared_api.app import create_shared_api


def _settings(root: Path, shared: Path) -> Settings:
    return Settings(
        local_data_dir=root / "local",
        shared_database_url=f"sqlite:///{shared}",
        shared_transport="postgres",
        shared_enabled=True,
        api_environment="test",
    )


def test_shared_api_contracts_pagination_filters_and_privacy() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        shared = root / "shared.db"
        engine = create_engine(f"sqlite:///{shared}")
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine).begin() as session:
            company = Company(slug="example", name="Example Firm", primary_domain="example.test")
            session.add(company)
            session.flush()
            now = datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 compatibility
            session.add(
                Job(
                    company_id=company.id,
                    title="Software Engineer Intern",
                    role_family="software_engineering",
                    job_url="https://example.test/jobs/1",
                    source_type="fixture",
                    status="open",
                    date_first_seen=now,
                    date_last_seen=now,
                )
            )
        client = TestClient(create_shared_api(_settings(root, shared)))

        assert client.get("/api/v1/health").json()["status"] == "ok"
        companies = client.get("/api/v1/companies?limit=1").json()
        assert companies["items"][0]["slug"] == "example"
        assert client.get("/api/v1/jobs?role_family=software_engineering").json()["items"]
        assert client.get("/api/v1/companies?query=missing").json()["items"] == []

        manifest_response = client.get("/api/v1/sync/manifest")
        assert manifest_response.status_code == 200
        assert "jobs" in manifest_response.json()["collections"]
        assert (
            client.get(
                "/api/v1/sync/manifest",
                headers={"If-None-Match": manifest_response.headers["etag"]},
            ).status_code
            == 304
        )

        changes = client.get("/api/v1/sync/changes").json()["changes"]
        assert {item["collection"] for item in changes} >= {"companies", "jobs"}
        openapi = client.get("/openapi.json").json()
        assert not any("candidate" in path or "conversation" in path for path in openapi["paths"])
        engine.dispose()
