from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from quant_recruiting.companion_app import create_companion_app
from quant_recruiting.config import Settings
from quant_recruiting.db.models import CandidateProfile
from quant_recruiting.storage import get_local_session


def test_local_companion_pages_and_onboarding_are_local() -> None:
    with TemporaryDirectory() as directory:
        settings = Settings(local_data_dir=Path(directory), local_host="testserver")
        client = TestClient(create_companion_app(settings))
        assert client.get("/").status_code == 200
        assert "stored locally" in client.get("/").text
        assert client.get("/jobs").status_code == 200
        assert client.get("/local-data").status_code == 200
        for path in (
            "/email",
            "/timeline",
            "/assessments",
            "/interviews",
            "/preparation",
            "/notifications",
            "/browser",
            "/browser/capabilities",
            "/background",
        ):
            assert client.get(path).status_code == 200
        onboarding = client.get("/onboarding")
        assert onboarding.status_code == 200
        token = onboarding.text.split("name='csrf' value='")[1].split("'")[0]
        response = client.post(
            "/onboarding",
            data={"csrf": token, "preferred_name": "Local User", "email": "local@example.test"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        with get_local_session(settings) as session:
            profile = session.query(CandidateProfile).one()
            assert profile.preferred_name == "Local User"
