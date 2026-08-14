from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import pytest
from sqlalchemy import select

from quant_recruiting import browser_engine
from quant_recruiting.browser_engine import (
    HumanSubmissionRequired,
    _guard_navigation,
    run_browser,
)
from quant_recruiting.browser_forms import (
    AshbyFormAdapter,
    GenericHTMLFormAdapter,
    GreenhouseFormAdapter,
    LeverFormAdapter,
    normalize_label,
)
from quant_recruiting.config import Settings
from quant_recruiting.db.models import Application, ApplicationArtifact, Company, Job
from quant_recruiting.local_models import LocalBrowserRun, LocalBrowserUpload
from quant_recruiting.storage import get_local_session

HTML = """
<form id="application_form">
  <label for="name">Full Name</label><input id="name" name="name" required>
  <label for="email">Email Address</label><input id="email" name="email" type="email" required>
  <label for="resume">Résumé</label><input id="resume" name="resume" type="file" required>
  <label for="question">Why do you want to join us?</label>
  <textarea id="question" name="question" required></textarea>
  <label for="sponsor">Will you now or in the future require sponsorship?</label>
  <select id="sponsor" name="sponsor" required><option>Yes</option><option>No</option></select>
    <label><input id="certify" type="checkbox">
      I certify that all information is accurate.
    </label>
  <button type="button">Continue</button>
  <button id="submit" type="submit">Submit Application</button>
</form>
<script>
  document.querySelector('form').addEventListener('submit', e => {
    e.preventDefault();
    window.submitCount = (window.submitCount || 0) + 1;
  });
</script>
"""


def test_normalize_label_is_conservative() -> None:
    assert normalize_label("Résumé / CV") == "résumé cv"


def test_ats_detection_is_provider_specific() -> None:
    class Page:
        def __init__(self, url: str) -> None:
            self.url = url

    assert LeverFormAdapter().detect(Page("https://jobs.lever.co/example/123")).provider == "lever"
    assert (
        AshbyFormAdapter().detect(Page("https://jobs.ashbyhq.com/example/123")).provider == "ashby"
    )
    assert GenericHTMLFormAdapter().detect(Page("https://example.test/apply")).provider == "generic"


def test_sensitive_and_final_submit_controls_are_gated() -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(HTML)
        adapter = GreenhouseFormAdapter()
        snapshot = adapter.inspect(page, step_index=1)
        assert any(item.field_type == "sensitive" for item in snapshot.fields)
        assert any(item.field_type == "legal_attestation" for item in snapshot.fields)
        assert any(item.field_type == "final_submit" for item in snapshot.navigation)
        payload = {
            "identity": {"name": "Ada Lovelace", "email": "ada@example.test"},
            "documents": {"cv": str(Path(__file__).resolve())},
            "questions": [
                {
                    "application_question_id": "q1",
                    "original_question": "Why do you want to join us?",
                    "answer": "Because the work is compelling.",
                }
            ],
            "sensitive_fields": {},
        }
        mapping = adapter.map_fields(snapshot, payload)
        assert mapping.unresolved_required
        sponsor = next(item for item in mapping.mappings if item.field.html_id == "sponsor")
        assert sponsor.status == "needs_input"
        assert sponsor.sensitive is True
        _guard_navigation("navigation_continue")
        with pytest.raises(HumanSubmissionRequired):
            _guard_navigation("final_submit")
        assert page.evaluate("window.submitCount || 0") == 0
        browser.close()


def test_explicit_sensitive_value_and_exact_answer_fill() -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(HTML)
        adapter = GreenhouseFormAdapter()
        snapshot = adapter.inspect(page, step_index=1)
        payload = {
            "identity": {"name": "Ada Lovelace", "email": "ada@example.test"},
            "questions": [
                {
                    "application_question_id": "q1",
                    "original_question": "Why do you want to join us?",
                    "answer": "Because the work is compelling.",
                }
            ],
            "sensitive_fields": {"visa_sponsorship": "No"},
        }
        mapping = adapter.map_fields(snapshot, payload)
        assert not any(
            item.field.html_id == "sponsor" and item.status == "needs_input"
            for item in mapping.mappings
        )
        filled = adapter.fill(page, mapping)
        verified = adapter.verify(page, type(mapping)(tuple(filled)))
        assert page.locator("#name").input_value() == "Ada Lovelace"
        assert page.locator("#question").input_value() == "Because the work is compelling."
        assert any(
            item.status == "verified" for item in verified if item.field.html_id == "question"
        )
        assert page.evaluate("window.submitCount || 0") == 0
        browser.close()


def test_local_fake_ats_run_reaches_human_gate_without_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        html = root / "greenhouse.html"
        html.write_text(HTML, encoding="utf-8")
        cv = root / "approved CV.pdf"
        cv.write_bytes(b"approved cv fixture")
        settings = Settings(
            local_data_dir=root / "local",
            shared_enabled=False,
            storage_mode="server_only",
            browser_headless=True,
            browser_screenshots=False,
        )
        with get_local_session(settings) as session:
            company = Company(slug="fixture-firm", name="Fixture Firm")
            session.add(company)
            session.flush()
            job = Job(
                company_id=company.id,
                title="Software Engineer Intern",
                role_family="software_engineering",
                job_url=html.as_uri(),
                source_type="fixture",
                date_first_seen=datetime.now(timezone.utc),  # noqa: UP017
                date_last_seen=datetime.now(timezone.utc),  # noqa: UP017
                status="open",
            )
            session.add(job)
            session.flush()
            application = Application(
                job_id=job.id,
                application_url=html.as_uri(),
                cover_letter_requirement="not_required",
            )
            session.add(application)
            session.flush()
            artifact = ApplicationArtifact(
                application_id=application.id,
                artifact_type="cv_pdf",
                version=1,
                status="approved",
                content_hash=__import__("hashlib").sha256(cv.read_bytes()).hexdigest(),
                rendered_path=str(cv),
            )
            session.add(artifact)
            session.flush()
            application_id = application.id
            artifact_id = artifact.id

        payload = {
            "identity": {"name": "Ada Lovelace", "email": "ada@example.test"},
            "documents": {"cv": str(cv)},
            "sensitive_fields": {"visa_sponsorship": "No"},
            "questions": [
                {
                    "application_question_id": "q1",
                    "original_question": "Why do you want to join us?",
                    "answer": "Because the work is compelling.",
                }
            ],
        }
        manifest = {"packet_version": 1, "artifact_file_ids": {"cv": str(artifact_id)}}
        monkeypatch.setattr(
            browser_engine,
            "preflight",
            lambda _application_id, _settings: {
                "application_id": str(application_id),
                "application_url": html.as_uri(),
                "packet_version": 1,
                "manifest": manifest,
                "payload": payload,
                "readiness": {},
            },
        )
        monkeypatch.setattr(
            browser_engine,
            "_current_packet",
            lambda _application, _settings: (manifest, dict(payload)),
        )
        result = run_browser(application_id, settings)
        assert result["status"] == "ready_for_human_submission", result
        with get_local_session(settings) as session:
            run = session.scalar(
                select(LocalBrowserRun).where(LocalBrowserRun.id == UUID(result["run_id"]))
            )
            assert run is not None
            assert run.status == "ready_for_human_submission"
            upload = session.scalar(
                select(LocalBrowserUpload).where(LocalBrowserUpload.run_id == run.id)
            )
            assert upload is not None
            assert upload.status == "verified"
            assert session.query(LocalBrowserRun).count() == 1
