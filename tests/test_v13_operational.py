from __future__ import annotations

import json
from pathlib import Path

from quant_recruiting.ats_capabilities import capability_report
from quant_recruiting.config import Settings
from quant_recruiting.email_fixtures import capture_email_fixture
from quant_recruiting.email_ingestion import GmailProvider, import_eml
from quant_recruiting.local_ops import cloud_sync_warnings
from quant_recruiting.system_readiness import system_readiness


class _Request:
    def __init__(self, value: dict) -> None:
        self.value = value

    def execute(self) -> dict:
        return self.value


class _Messages:
    def list(self, **kwargs: object) -> _Request:
        assert kwargs["maxResults"] == 100
        return _Request({"messages": [{"id": "m1"}], "nextPageToken": None})

    def get(self, **_kwargs: object) -> _Request:
        return _Request({"id": "m1", "raw": ""})


class _History:
    def list(self, **kwargs: object) -> _Request:
        assert kwargs["startHistoryId"] == "old"
        return _Request({"history": [{"messagesAdded": [{"message": {"id": "m2"}}]}]})


class _Users:
    def __init__(self) -> None:
        self.message_api = _Messages()
        self.history_api = _History()

    def messages(self) -> _Messages:
        return self.message_api

    def history(self) -> _History:
        return self.history_api


class _Service:
    def __init__(self) -> None:
        self.users_api = _Users()

    def users(self) -> _Users:
        return self.users_api


def test_gmail_provider_supports_bounded_list_and_history() -> None:
    provider = GmailProvider(_Service())
    assert provider.list_messages() == [{"id": "m1"}]
    assert provider.list_history_message_ids("old") == ["m2"]


def test_email_fixture_capture_is_redacted(tmp_path: Path) -> None:
    settings = Settings(local_data_dir=tmp_path / "local", shared_enabled=False)
    source = tmp_path / "mail.eml"
    source.write_text(
        "From: Recruiter <recruiter@firm.test>\n"
        "To: Candidate <candidate@private.test>\n"
        "Subject: Assessment\n"
        "Message-ID: <private@firm.test>\n"
        "\nComplete at https://assessment.test/token-secret or call +44 7700 900123.\n",
        encoding="utf-8",
    )
    imported = import_eml(source, settings)
    result = capture_email_fixture(imported["message_id"], settings)
    text = Path(str(result["eml"])).read_text(encoding="utf-8")
    metadata = json.loads(Path(str(result["metadata"])).read_text(encoding="utf-8"))
    assert "candidate@private.test" not in text
    assert "token-secret" not in text
    assert metadata["contains_private_data"] is False


def test_capability_report_is_evidence_shaped(tmp_path: Path) -> None:
    settings = Settings(local_data_dir=tmp_path / "local", shared_enabled=False)
    rows = capability_report(settings)
    greenhouse = next(row for row in rows if row["provider"] == "greenhouse")
    assert {"fixture_count", "real_world_fixture_count", "last_verified"}.issubset(greenhouse)
    assert isinstance(greenhouse["known_limitations"], list)


def test_local_path_warning_and_readiness_are_explicit(tmp_path: Path) -> None:
    cloud_path = tmp_path / "OneDrive" / "RecruitingAssistant"
    warnings = cloud_sync_warnings(cloud_path)
    assert warnings and "OneDrive" in warnings[0]
    settings = Settings(local_data_dir=tmp_path / "local", shared_enabled=False)
    result = system_readiness(settings)
    assert result["private_push_enabled"] is False
    assert any(row["name"] == "Local SQLite" for row in result["checks"])
