from __future__ import annotations

from pathlib import Path

from quant_recruiting.ats_capabilities import all_capabilities, capabilities_for
from quant_recruiting.background_runner import BackgroundAlreadyRunning, _LocalLock
from quant_recruiting.browser_diagnostics import sanitize_dom
from quant_recruiting.browser_forms import adapter_for_page
from quant_recruiting.config import Settings
from quant_recruiting.local_db import local_diagnostics, upgrade_local
from quant_recruiting.windows_scheduler import task_xml


def test_capabilities_are_explicit_and_conservative() -> None:
    providers = {item.provider for item in all_capabilities()}
    assert {"workday", "smartrecruiters", "icims", "taleo"}.issubset(providers)
    assert capabilities_for("taleo").identity == "DETECTED_ONLY"
    assert capabilities_for("workday").education == "EXPERIMENTAL"


def test_provider_detection_uses_hostname_without_claiming_unknown_forms() -> None:
    class Page:
        def __init__(self, url: str) -> None:
            self.url = url

        class Locator:
            def count(self) -> int:
                return 0

        def locator(self, _selector: str) -> Locator:
            return self.Locator()

    assert adapter_for_page(Page("https://company.wd5.myworkdayjobs.com/job")).provider == "workday"
    assert (
        adapter_for_page(Page("https://jobs.smartrecruiters.com/company/job")).provider
        == "smartrecruiters"
    )
    assert adapter_for_page(Page("https://example.test/apply")).provider == "generic"


def test_fixture_sanitization_removes_values_and_scripts() -> None:
    html = """
    <html><script>secret()</script><form>
      <input id="email" value="ada@example.com">
      <input type="hidden" name="csrf_token" value="secret-token">
      <textarea>private answer</textarea>
    </form></html>
    """
    sanitized = sanitize_dom(html)
    assert "secret()" not in sanitized
    assert "ada@example.com" not in sanitized
    assert "secret-token" not in sanitized
    assert "private answer" not in sanitized


def test_local_schema_v12_integrity(tmp_path: Path) -> None:
    settings = Settings(local_data_dir=tmp_path, shared_enabled=False)
    upgrade_local(settings)
    diagnostics = local_diagnostics(settings)
    assert diagnostics["integrity"] == "ok"
    assert diagnostics["foreign_keys"] is True
    assert diagnostics["journal_mode"] == "wal"
    assert diagnostics["table_count"] >= 115


def test_background_lock_rejects_overlap(tmp_path: Path) -> None:
    lock_path = tmp_path / "background.lock"
    with _LocalLock(lock_path):
        try:
            with _LocalLock(lock_path):
                raise AssertionError("nested lock unexpectedly acquired")
        except BackgroundAlreadyRunning:
            pass


def test_task_scheduler_xml_is_local_runner_only() -> None:
    xml = task_xml("RecruitingAssistant.exe", interval_minutes=30)
    assert "background run-once" in xml
    assert "IgnoreNew" in xml
    assert "Submit" not in xml
