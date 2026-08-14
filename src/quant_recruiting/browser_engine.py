"""Local Playwright application autofill with a mandatory human submit gate."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from html import escape as escape_html
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select

from quant_recruiting.artifacts import (
    application_readiness,
    application_root,
    sha256_bytes,
    sha256_text,
    verify_packet,
)
from quant_recruiting.browser_forms import (
    ApplicationFormAdapter,
    FieldMapping,
    FieldMappingResult,
    FormSnapshot,
    adapter_for_page,
    normalize_label,
)
from quant_recruiting.config import Settings, get_settings
from quant_recruiting.db.models import Application, CandidateProfile
from quant_recruiting.local_models import (
    LocalApplicationFormValue,
    LocalBrowserField,
    LocalBrowserFieldAlias,
    LocalBrowserFieldMapping,
    LocalBrowserFillAttempt,
    LocalBrowserIssue,
    LocalBrowserPage,
    LocalBrowserParsedValue,
    LocalBrowserRun,
    LocalBrowserRunAttempt,
    LocalBrowserUpload,
    LocalBrowserValidationError,
    LocalCandidateFormValue,
)
from quant_recruiting.storage import get_local_session
from quant_recruiting.sync import refresh_job_freshness


class BrowserAutomationError(RuntimeError):
    """Base error for local browser workflows."""


class PreflightFailed(BrowserAutomationError):
    """The application is not safe or complete enough to open."""


class StaleBrowserRun(BrowserAutomationError):
    """A run references artifacts older than the current approved packet."""


class HumanSubmissionRequired(BrowserAutomationError):
    """Raised whenever an action could submit an application."""


TERMINAL_STATUSES = {"applied", "interview", "rejected", "offer", "withdrawn"}
RUN_READY = "ready_for_human_submission"


def _utcnow() -> datetime:
    return datetime.now(getattr(timezone, "UTC", timezone.utc))  # noqa: UP017


def browser_run_directory(
    application_id: UUID, run_id: UUID, settings: Settings | None = None
) -> Path:
    config = settings or get_settings()
    path = application_root(application_id, config) / "browser" / str(run_id)
    (path / "screenshots").mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )


def _current_packet(
    application: Application, settings: Settings
) -> tuple[dict[str, Any], dict[str, Any]]:
    packet = application_root(application.id, settings) / "packet"
    manifest_path = packet / "manifest.json"
    payload_path = packet / "application_form_payload.json"
    if not manifest_path.exists() or not payload_path.exists():
        raise PreflightFailed(
            "verified application packet and application_form_payload.json are required"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    return manifest, payload


def _add_local_form_values(session: Any, payload: dict[str, Any], application_id: UUID) -> None:
    values: dict[str, Any] = {}
    for row in session.scalars(
        select(LocalCandidateFormValue).where(
            LocalCandidateFormValue.reusable.is_(True), LocalCandidateFormValue.approved.is_(True)
        )
    ):
        if row.value is not None:
            values[row.normalized_key] = row.value
    for row in session.scalars(
        select(LocalApplicationFormValue).where(
            LocalApplicationFormValue.application_id == application_id,
            LocalApplicationFormValue.approved.is_(True),
        )
    ):
        if row.value is not None:
            values[row.normalized_key] = row.value
    payload["_application_form_values"] = values
    payload["_field_aliases"] = {
        row.normalized_label: row.normalized_key
        for row in session.scalars(select(LocalBrowserFieldAlias))
    }


def preflight(application_id: UUID, settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    freshness = refresh_job_freshness(application_id, config)
    if freshness.get("status") == "closed":
        raise PreflightFailed("job became closed during freshness check")
    with get_local_session(config) as session:
        application = session.get(Application, application_id)
        if application is None:
            raise PreflightFailed("application does not exist in local storage")
        if application.status in TERMINAL_STATUSES:
            raise PreflightFailed(
                f"application status {application.status!r} requires explicit review before rerun"
            )
        if application.job.status == "closed":
            raise PreflightFailed("job is known closed")
        if not application.application_url and not application.job.job_url:
            raise PreflightFailed("application URL is missing")
        readiness = application_readiness(session, application)
        packet = verify_packet(session, application)
        if packet.get("status") != "valid":
            raise PreflightFailed(
                "packet verification failed: " + "; ".join(packet.get("errors", []))
            )
        if readiness.get("blocking_gaps"):
            raise PreflightFailed(
                "application readiness has blocking gaps: " + "; ".join(readiness["blocking_gaps"])
            )
        manifest, payload = _current_packet(application, config)
        return {
            "application_id": str(application.id),
            "application_url": application.application_url or application.job.job_url,
            "packet_version": manifest.get("packet_version"),
            "manifest": manifest,
            "payload": payload,
            "readiness": readiness,
            "job_freshness": freshness,
        }


def _create_run(
    application_id: UUID,
    settings: Settings,
    *,
    mode: str = "autofill",
    dogfood: bool = False,
) -> UUID:
    details = preflight(application_id, settings)
    run_id = uuid4()
    directory = browser_run_directory(application_id, run_id, settings)
    manifest = details["manifest"]
    payload_artifact_id = manifest.get("artifact_file_ids", {}).get("application_form_payload")
    with get_local_session(settings) as session:
        run = LocalBrowserRun(
            id=run_id,
            application_id=application_id,
            payload_artifact_id=UUID(payload_artifact_id) if payload_artifact_id else None,
            packet_version=details["packet_version"],
            application_url=details["application_url"],
            original_url=details["application_url"],
            status="created",
            browser_type="chromium",
            headless=settings.browser_headless,
            dogfood=dogfood,
            screenshot_dir=str(directory / "screenshots"),
            metadata_={
                "automatic_submit": False,
                "payload_path": manifest.get("payload"),
                "mode": mode,
                "dogfood": dogfood,
            },
        )
        session.add(run)
        session.flush()
        session.add(
            LocalBrowserRunAttempt(
                run_id=run.id,
                attempt_number=1,
                status="created",
                checkpoint="PRELOGIN",
            )
        )
    return run_id


def _current_attempt(session: Any, run: LocalBrowserRun) -> LocalBrowserRunAttempt:
    attempt = session.scalar(
        select(LocalBrowserRunAttempt)
        .where(LocalBrowserRunAttempt.run_id == run.id)
        .order_by(LocalBrowserRunAttempt.attempt_number.desc())
    )
    if attempt is None:
        attempt = LocalBrowserRunAttempt(
            run_id=run.id, attempt_number=1, status="created", checkpoint="PRELOGIN"
        )
        session.add(attempt)
        session.flush()
    return cast(LocalBrowserRunAttempt, attempt)


def _assert_not_stale(
    session: Any, run: LocalBrowserRun, application: Application, settings: Settings
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, payload = _current_packet(application, settings)
    if run.packet_version != manifest.get("packet_version"):
        raise StaleBrowserRun("approved packet version changed; start a new browser run")
    return manifest, payload


def _persist_snapshot(
    session: Any, run: LocalBrowserRun, snapshot: FormSnapshot
) -> dict[str, UUID]:
    page = LocalBrowserPage(
        run_id=run.id,
        step_index=snapshot.step_index,
        url=snapshot.url,
        title=snapshot.title,
        inspected_at=_utcnow(),
        metadata_={"field_count": len(snapshot.fields)},
    )
    session.add(page)
    session.flush()
    field_ids: dict[str, UUID] = {}
    for item in snapshot.fields:
        field = LocalBrowserField(
            run_id=run.id,
            page_id=page.id,
            field_key=item.field_key,
            original_label=item.original_label,
            normalized_key=normalize_label(item.original_label),
            field_type=item.field_type,
            input_type=item.input_type,
            html_name=item.html_name,
            html_id=item.html_id,
            aria_label=item.aria_label,
            placeholder=item.placeholder,
            required=item.required,
            visible=item.visible,
            disabled=item.disabled,
            options=list(item.options),
            current_value_hash=sha256_text(item.current_value or "")
            if item.current_value
            else None,
            metadata_=item.metadata,
        )
        session.add(field)
        session.flush()
        field_ids[item.field_key] = field.id
    run.current_step = f"page-{snapshot.step_index}"
    return field_ids


def _persist_mappings(
    session: Any, run: LocalBrowserRun, result: FieldMappingResult, field_ids: dict[str, UUID]
) -> None:
    for item in result.mappings:
        field_id = field_ids.get(item.field.field_key)
        if field_id is None:
            continue
        session.add(
            LocalBrowserFieldMapping(
                field_id=field_id,
                source_entity_type="application_form_payload" if item.source_key else None,
                source_entity_id=item.source_key,
                source_key=item.normalized_key,
                method=item.method,
                confidence=item.confidence,
                reason=item.reason,
                expected_value_hash=sha256_text(str(item.value))
                if item.value is not None
                else None,
                status=item.status,
                metadata_={"sensitive": item.sensitive},
            )
        )


def _persist_attempts(
    session: Any, run: LocalBrowserRun, mappings: list[FieldMapping], field_ids: dict[str, UUID]
) -> None:
    for item in mappings:
        session.add(
            LocalBrowserFillAttempt(
                run_id=run.id,
                field_id=field_ids.get(item.field.field_key),
                status=item.status,
                expected_value_hash=sha256_text(str(item.value))
                if item.value is not None
                else None,
                actual_value_hash=sha256_text(str(item.actual_value))
                if item.actual_value is not None
                else None,
                attempted_at=_utcnow(),
                metadata_={"method": item.method, "confidence": item.confidence},
            )
        )


def _persist_uploads(
    session: Any,
    run: LocalBrowserRun,
    page: Any,
    mappings: list[FieldMapping],
    manifest: dict[str, Any],
    field_ids: dict[str, UUID],
) -> list[str]:
    failures: list[str] = []
    artifact_keys = {"documents.cv": "cv", "documents.cover_letter": "cover_letter"}
    for item in mappings:
        if item.field.field_type != "documents" or item.status != "mapped":
            continue
        path = Path(str(item.value))
        key = artifact_keys.get(item.source_key or "")
        artifact_id = manifest.get("artifact_file_ids", {}).get(key) if key else None
        expected_hash = sha256_bytes(path.read_bytes()) if path.exists() else ""
        uploaded = False
        try:
            uploaded = bool(
                page.locator(item.field.selector).evaluate(
                    "el => !!(el.files && el.files.length > 0)"
                )
            )
        except Exception:
            uploaded = False
        status = "verified" if path.exists() and artifact_id and uploaded else "failed"
        if status == "failed":
            failures.append(item.field.original_label)
        if artifact_id:
            session.add(
                LocalBrowserUpload(
                    run_id=run.id,
                    field_id=field_ids.get(item.field.field_key),
                    artifact_id=UUID(str(artifact_id)),
                    artifact_type="cv_pdf" if key == "cv" else "cover_letter_pdf",
                    expected_hash=expected_hash,
                    uploaded_filename=path.name if path.exists() else None,
                    status=status,
                    uploaded_at=_utcnow(),
                )
            )
    return failures


def _write_run_files(
    run: LocalBrowserRun,
    application: Application,
    mappings: list[FieldMapping],
    settings: Settings,
    *,
    snapshot: FormSnapshot | None = None,
) -> None:
    directory = browser_run_directory(application.id, run.id, settings)
    fill_log = [
        {
            "field_key": item.field.field_key,
            "original_label": item.field.original_label,
            "normalized_key": item.normalized_key,
            "field_type": item.field.field_type,
            "required": item.field.required,
            "mapping_method": item.method,
            "mapping_confidence": item.confidence,
            "source_entity_type": "application_form_payload" if item.source_key else None,
            "source_entity_id": item.source_key,
            "expected_value_hash": sha256_text(str(item.value)) if item.value is not None else None,
            "actual_value_hash": sha256_text(str(item.actual_value))
            if item.actual_value is not None
            else None,
            "status": item.status,
            "sensitive": item.sensitive,
            "timestamp": _utcnow().isoformat(),
        }
        for item in mappings
    ]
    fill_path = directory / "fill-log.json"
    _write_json(
        fill_path,
        {"run_id": str(run.id), "application_id": str(application.id), "fields": fill_log},
    )
    validation_path = directory / "validation.json"
    _write_json(
        validation_path,
        {
            "status": run.status,
            "unresolved": [
                item["original_label"]
                for item in fill_log
                if item["status"] in {"needs_input", "failed", "verification_failed"}
            ],
        },
    )
    checklist = directory / "submission-checklist.md"
    checklist.write_text(
        f"# Submission checklist\n\nApplication: `{application.id}`\n\n"
        f"Status: **{run.status}**\n\nFinal submit clicked by automation: **NO**\n\n"
        "Review the visible application page and complete all manual/legal actions "
        "before submitting.\n",
        encoding="utf-8",
    )
    review = directory / "review.html"
    review.write_text(
        "<!doctype html><meta charset='utf-8'><title>Browser review</title>"
        f"<h1>{application.job.company.name} — {application.job.title}</h1>"
        f"<p>Status: <strong>{run.status}</strong></p>"
        "<p>Final submit clicked by automation: <strong>NO</strong></p>"
        f"<p><a href='{application.application_url or application.job.job_url}'>"
        "Application URL</a></p>",
        encoding="utf-8",
    )
    if snapshot is not None:
        snapshot_payload = asdict(snapshot)
        for item in snapshot_payload.get("fields", []):
            item["current_value"] = None
        _write_json(
            directory / "form-snapshot.json",
            {"run_id": str(run.id), "snapshot": snapshot_payload, "status": run.status},
        )
    run.fill_log_path = str(fill_path)
    run.review_html_path = str(review)
    run.form_snapshot_path = str(directory / "form-snapshot.json")


def _screenshot(
    page: Any, run: LocalBrowserRun, application: Application, settings: Settings, name: str
) -> None:
    if not settings.browser_screenshots:
        return
    if settings.browser_redact_sensitive_screenshots:
        run.metadata_ = {
            **(run.metadata_ or {}),
            "screenshot_redaction": "not guaranteed",
            "screenshots_may_contain_sensitive_data": True,
        }
    path = browser_run_directory(application.id, run.id, settings) / "screenshots" / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:
        run.metadata_ = {**(run.metadata_ or {}), "screenshot_warning": "capture failed"}


def _guard_navigation(action: str) -> None:
    if action == "final_submit":
        raise HumanSubmissionRequired(
            "final submission control detected; automation stopped before submit"
        )


def _page_blocker(page: Any) -> str | None:
    """Detect common human-only gates without attempting to bypass them."""
    url = str(page.url).lower()
    try:
        text = page.locator("body").inner_text(timeout=2_000).lower()
    except Exception:
        text = ""
    if any(
        token in text or token in url for token in ("recaptcha", "hcaptcha", "turnstile", "captcha")
    ):
        return "CAPTCHA or bot challenge detected"
    if any(token in url for token in ("/login", "/signin", "/account")) or any(
        token in text
        for token in ("single sign-on", "sign in to apply", "create an account to apply")
    ):
        return "Authentication or account creation required"
    return None


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def browser_diagnostics(settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    result: dict[str, Any] = {
        "playwright_installed": _playwright_available(),
        "chromium_installed": False,
        "browser_executable": None,
        "profile_dir": str(
            config.browser_profile_dir or config.local_data_dir / "browser-profiles"
        ),
    }
    if not result["playwright_installed"]:
        return result
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            executable = playwright.chromium.executable_path
            result["browser_executable"] = executable
            result["chromium_installed"] = Path(executable).exists()
    except Exception as exc:
        result["browser_error"] = str(exc)
    result["profile_available"] = Path(result["profile_dir"]).exists()
    try:
        from quant_recruiting.ats_capabilities import capability_report

        result["ats_capabilities"] = capability_report(config)
    except Exception:
        result["ats_capabilities"] = []
    return result


def install_browser() -> int:
    return subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])


def restart_browser(run_id: UUID, settings: Settings | None = None) -> dict[str, Any]:
    """Start a new execution attempt without overwriting prior browser history."""
    config = settings or get_settings()
    with get_local_session(config) as session:
        run = session.get(LocalBrowserRun, run_id)
        if run is None:
            raise BrowserAutomationError("browser run not found")
        if run.status == "submitted_observed":
            raise BrowserAutomationError("submitted browser runs are read-only")
        latest = session.scalar(
            select(LocalBrowserRunAttempt)
            .where(LocalBrowserRunAttempt.run_id == run.id)
            .order_by(LocalBrowserRunAttempt.attempt_number.desc())
        )
        number = (latest.attempt_number if latest else 0) + 1
        session.add(
            LocalBrowserRunAttempt(
                run_id=run.id, attempt_number=number, status="created", checkpoint="PRELOGIN"
            )
        )
        run.status = "created"
        run.current_step = "PRELOGIN"
        run.completed_at = None
        run.final_url = None
        run.metadata_ = {**(run.metadata_ or {}), "restart_count": number - 1}
        return {"run_id": str(run.id), "status": run.status, "attempt_number": number}


def record_parsed_values(
    run_id: UUID,
    parsed_values: dict[str, Any],
    settings: Settings | None = None,
    *,
    expected_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist ATS résumé-parser output as reviewable observations only."""
    config = settings or get_settings()
    expected = expected_values or {}
    with get_local_session(config) as session:
        run = session.get(LocalBrowserRun, run_id)
        if run is None:
            raise BrowserAutomationError("browser run not found")
        mismatches = 0
        for key, value in parsed_values.items():
            expected_value = expected.get(key)
            comparison = (
                "unknown"
                if expected_value is None
                else (
                    "matches_expected"
                    if str(value).strip() == str(expected_value).strip()
                    else "differs"
                )
            )
            mismatches += int(comparison == "differs")
            session.add(
                LocalBrowserParsedValue(
                    run_id=run.id,
                    field=key,
                    parsed_value=str(value) if value is not None else None,
                    expected_profile_value=(
                        str(expected_value) if expected_value is not None else None
                    ),
                    comparison_status=comparison,
                    approved=False,
                    metadata_={"canonical_profile_mutation": False},
                )
            )
        if mismatches:
            run.status = "needs_input"
            run.metadata_ = {**(run.metadata_ or {}), "parser_mismatch": True}
        return {"run_id": str(run.id), "parsed": len(parsed_values), "mismatches": mismatches}


def _run_directory_from_record(run: LocalBrowserRun) -> Path:
    return Path(run.screenshot_dir).parent


def run_diagnostics(run_id: UUID, settings: Settings | None = None) -> dict[str, Any]:
    """Create a sanitized, inspectable diagnostics index for one local run."""
    config = settings or get_settings()
    with get_local_session(config) as session:
        run = session.get(LocalBrowserRun, run_id)
        if run is None:
            raise BrowserAutomationError("browser run not found")
        attempts = list(
            session.scalars(
                select(LocalBrowserRunAttempt)
                .where(LocalBrowserRunAttempt.run_id == run.id)
                .order_by(LocalBrowserRunAttempt.attempt_number)
            )
        )
        metadata = {
            "run_id": str(run.id),
            "application_id": str(run.application_id),
            "status": run.status,
            "ats": run.detected_ats,
            "ats_confidence": run.ats_confidence,
            "current_step": run.current_step,
            "final_url": run.final_url,
            "mode": (run.metadata_ or {}).get("mode", "autofill"),
            "failure_category": (run.metadata_ or {}).get("failure_category"),
            "automatic_submit": False,
            "attempts": [
                {
                    "id": str(item.id),
                    "number": item.attempt_number,
                    "status": item.status,
                    "checkpoint": item.checkpoint,
                    "error_code": item.error_code,
                }
                for item in attempts
            ],
            "network_summary": "not captured; request bodies and credentials are never exported",
            "console_summary": "not captured in the default privacy-safe bundle",
        }
        directory = _run_directory_from_record(run)
        diagnostics = directory / "diagnostics"
        diagnostics.mkdir(parents=True, exist_ok=True)
        _write_json(diagnostics / "metadata.json", metadata)
        for name in ("form-snapshot.json", "validation.json", "fill-log.json"):
            source = directory / name
            if source.exists():
                shutil.copyfile(source, diagnostics / name)
        _write_json(
            diagnostics / "adapter-detection.json",
            {
                "provider": run.detected_ats,
                "confidence": run.ats_confidence,
                "reasons": (run.metadata_ or {}).get("detection_reasons", []),
            },
        )
        _write_json(
            diagnostics / "mapping.json", {"source": "fill-log.json", "values": "hashes only"}
        )
        _write_json(diagnostics / "console-summary.json", {"captured": False})
        _write_json(
            diagnostics / "network-summary.json", {"captured": False, "request_bodies": False}
        )
        sanitized_dom = diagnostics / "sanitized-dom.html"
        if not sanitized_dom.exists():
            snapshot_path = directory / "form-snapshot.json"
            excerpt = ["<main data-sanitized='true'>"]
            if snapshot_path.exists():
                try:
                    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
                    metadata["page_url"] = snapshot.get("url")
                    metadata["page_title"] = snapshot.get("title")
                    for field in snapshot.get("fields", []):
                        label = escape_html(str(field.get("original_label", "")))
                        field_type = escape_html(str(field.get("field_type", "unknown")))
                        selector_method = escape_html(str(field.get("selector_method", "unknown")))
                        excerpt.append(
                            f"<div data-field-type='{field_type}' "
                            f"data-selector-method='{selector_method}'>{label}</div>"
                        )
                except (OSError, ValueError, TypeError):
                    excerpt.append("<div>form snapshot could not be parsed</div>")
            excerpt.append("</main>\n")
            sanitized_dom.write_text("\n".join(excerpt), encoding="utf-8")
            _write_json(diagnostics / "metadata.json", metadata)
        validation_path = directory / "validation.json"
        if validation_path.exists():
            try:
                validation = json.loads(validation_path.read_text(encoding="utf-8"))
                metadata["visible_validation_messages"] = validation.get("errors", [])
                metadata["failed_selectors"] = validation.get("failed_selectors", [])
                _write_json(diagnostics / "metadata.json", metadata)
            except (OSError, ValueError, TypeError):
                pass
        return {"run_id": str(run.id), "diagnostics_dir": str(diagnostics), **metadata}


def privacy_check(run_id: UUID, settings: Settings | None = None) -> dict[str, Any]:
    """Best-effort local scan; it never claims perfect redaction."""
    result = run_diagnostics(run_id, settings)
    root = Path(str(result["diagnostics_dir"]))
    possible_leaks: list[str] = []
    email_pattern = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".json", ".html", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if email_pattern.search(text):
            possible_leaks.append(str(path.name))
    return {
        "run_id": str(run_id),
        "status": "warning" if possible_leaks else "passed",
        "possible_email_literals": possible_leaks,
        "note": "heuristic scan only; review screenshots separately",
    }


def export_diagnostics(
    run_id: UUID, settings: Settings | None = None, *, destination: Path | None = None
) -> Path:
    config = settings or get_settings()
    details = run_diagnostics(run_id, config)
    source = Path(str(details["diagnostics_dir"]))
    target = destination or config.local_data_dir / "exports" / f"browser-diagnostics-{run_id}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(source))
    return target


def _execute_run(
    run_id: UUID, settings: Settings, *, resume: bool = False, mode: str | None = None
) -> dict[str, Any]:
    if not _playwright_available():
        raise BrowserAutomationError(
            "Playwright is not installed; run `recruiting setup browser --install`"
        )
    from playwright.sync_api import sync_playwright

    with get_local_session(settings) as session:
        run = session.get(LocalBrowserRun, run_id)
        if run is None:
            raise BrowserAutomationError("browser run not found locally")
        application = session.get(Application, run.application_id)
        if application is None:
            raise BrowserAutomationError("application for browser run not found locally")
        manifest, payload = _assert_not_stale(session, run, application, settings)
        _add_local_form_values(session, payload, application.id)
        attempt = _current_attempt(session, run)
        run.status = "launching"
        run.started_at = run.started_at or _utcnow()
        attempt.status = "launching"
        attempt.started_at = attempt.started_at or _utcnow()
        selected_mode = mode or str((run.metadata_ or {}).get("mode", "autofill"))
        if selected_mode not in {"autofill", "assisted", "inspect"}:
            raise BrowserAutomationError(f"unsupported browser mode: {selected_mode}")
        run.metadata_ = {**(run.metadata_ or {}), "mode": selected_mode}
        session.flush()
        original_url = run.final_url or run.original_url
        session.commit()

    with sync_playwright() as playwright:
        browser = None
        context = None
        try:
            if settings.browser_profile_dir:
                Path(settings.browser_profile_dir).mkdir(parents=True, exist_ok=True)
                context = playwright.chromium.launch_persistent_context(
                    str(settings.browser_profile_dir),
                    headless=settings.browser_headless,
                    slow_mo=settings.browser_slow_mo_ms,
                )
            else:
                browser = playwright.chromium.launch(
                    headless=settings.browser_headless, slow_mo=settings.browser_slow_mo_ms
                )
                context = browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(settings.browser_timeout_seconds * 1000)
            page.goto(
                original_url,
                wait_until="domcontentloaded",
                timeout=settings.browser_timeout_seconds * 1000,
            )
            with get_local_session(settings) as session:
                run = session.get(LocalBrowserRun, run_id)
                application = session.get(Application, run.application_id) if run else None
                if run is None or application is None:
                    raise BrowserAutomationError("browser run disappeared")
                run.status = "inspecting"
                run.final_url = str(page.url)
                session.flush()
                adapter: ApplicationFormAdapter = adapter_for_page(page)
                detection = adapter.detect(page)
                run.detected_ats = detection.provider
                run.ats_confidence = detection.confidence
                run.metadata_ = {
                    **(run.metadata_ or {}),
                    "detection_reasons": list(detection.reasons),
                    "automatic_submit": False,
                }
                attempt = _current_attempt(session, run)
                attempt.status = "inspecting"
                blocker = _page_blocker(page)
                if blocker:
                    run.status = "needs_input"
                    run.metadata_ = {
                        **(run.metadata_ or {}),
                        "failure_category": (
                            "CAPTCHA_REQUIRED"
                            if "captcha" in blocker.lower()
                            else "AUTH_REQUIRED"
                            if "login" in blocker.lower() or "sign in" in blocker.lower()
                            else "HUMAN_GATE_REQUIRED"
                        ),
                    }
                    session.add(
                        LocalBrowserValidationError(
                            run_id=run.id,
                            message=blocker,
                            error_type="human_gate",
                            observed_at=_utcnow(),
                        )
                    )
                    _screenshot(page, run, application, settings, "001-human-gate")
                    session.commit()
                    return {"run_id": str(run.id), "status": run.status, "message": blocker}
                last_mappings: list[FieldMapping] = []
                for step_index in range(1, 9):
                    snapshot = adapter.inspect(page, step_index=step_index)
                    field_ids = _persist_snapshot(session, run, snapshot)
                    _screenshot(page, run, application, settings, f"{step_index:03d}-initial")
                    mapping = adapter.map_fields(snapshot, payload)
                    _persist_mappings(session, run, mapping, field_ids)
                    if mapping.unresolved_required:
                        run.status = "needs_input"
                        ambiguous = any(
                            item.confidence in {"medium", "low", "unmapped"}
                            for item in mapping.unresolved_required
                        )
                        run.metadata_ = {
                            **(run.metadata_ or {}),
                            "failure_category": (
                                "FIELD_MAPPING_AMBIGUOUS" if ambiguous else "UNKNOWN_REQUIRED_FIELD"
                            ),
                        }
                        last_mappings = list(mapping.mappings)
                        _write_run_files(
                            run, application, last_mappings, settings, snapshot=snapshot
                        )
                        session.commit()
                        return {
                            "run_id": str(run.id),
                            "status": run.status,
                            "unresolved": [
                                item.field.original_label for item in mapping.unresolved_required
                            ],
                        }
                    if str((run.metadata_ or {}).get("mode")) in {"inspect", "assisted"}:
                        run.status = (
                            "needs_input"
                            if str((run.metadata_ or {}).get("mode")) == "assisted"
                            else "needs_input"
                        )
                        run.current_step = (
                            "assisted-review"
                            if str((run.metadata_ or {}).get("mode")) == "assisted"
                            else f"inspect-{step_index}"
                        )
                        _write_run_files(
                            run, application, list(mapping.mappings), settings, snapshot=snapshot
                        )
                        attempt.checkpoint = (
                            "IDENTITY_COMPLETE"
                            if step_index == 1
                            else f"STEP_{step_index}_INSPECTED"
                        )
                        attempt.status = "needs_input"
                        session.commit()
                        return {
                            "run_id": str(run.id),
                            "status": run.status,
                            "mode": run.metadata_.get("mode"),
                            "field_count": len(snapshot.fields),
                        }
                    run.status = "filling"
                    attempt.checkpoint = (
                        "IDENTITY_COMPLETE" if step_index == 1 else f"STEP_{step_index}_INSPECTED"
                    )
                    filled = adapter.fill(page, mapping)
                    _persist_attempts(session, run, filled, field_ids)
                    upload_failures = _persist_uploads(
                        session, run, page, filled, manifest, field_ids
                    )
                    if upload_failures:
                        run.status = "verification_failed"
                        run.metadata_ = {
                            **(run.metadata_ or {}),
                            "failure_category": "UPLOAD_FAILED",
                        }
                        for label in upload_failures:
                            session.add(
                                LocalBrowserValidationError(
                                    run_id=run.id,
                                    message=f"Approved document upload was not verified: {label}",
                                    error_type="document_upload",
                                    observed_at=_utcnow(),
                                )
                            )
                        _write_run_files(run, application, filled, settings, snapshot=snapshot)
                        session.commit()
                        return {
                            "run_id": str(run.id),
                            "status": run.status,
                            "errors": upload_failures,
                        }
                    _screenshot(page, run, application, settings, f"{step_index:03d}-filled")
                    verified = adapter.verify(page, FieldMappingResult(tuple(filled)))
                    _persist_attempts(session, run, verified, field_ids)
                    last_mappings = verified
                    failures = [
                        item
                        for item in verified
                        if item.status in {"failed", "verification_failed"}
                    ]
                    if failures:
                        run.status = "verification_failed"
                        run.metadata_ = {
                            **(run.metadata_ or {}),
                            "failure_category": "VALIDATION_FAILED",
                        }
                        for item in failures:
                            session.add(
                                LocalBrowserValidationError(
                                    run_id=run.id,
                                    field_id=field_ids.get(item.field.field_key),
                                    message=item.reason,
                                    error_type="field_verification",
                                    observed_at=_utcnow(),
                                )
                            )
                        _write_run_files(
                            run, application, last_mappings, settings, snapshot=snapshot
                        )
                        session.commit()
                        return {
                            "run_id": str(run.id),
                            "status": run.status,
                            "errors": [item.reason for item in failures],
                        }
                    final_control = next(
                        (
                            button
                            for button in snapshot.navigation
                            if button.field_type == "final_submit"
                        ),
                        None,
                    )
                    if final_control:
                        try:
                            _guard_navigation("final_submit")
                        except HumanSubmissionRequired as exc:
                            run.status = RUN_READY
                            run.current_step = "final-review"
                            attempt.status = RUN_READY
                            attempt.checkpoint = "FINAL_REVIEW"
                            attempt.completed_at = _utcnow()
                            _write_run_files(
                                run, application, last_mappings, settings, snapshot=snapshot
                            )
                            session.commit()
                            return {
                                "run_id": str(run.id),
                                "status": run.status,
                                "message": str(exc),
                            }
                    continue_control = next(
                        (
                            button
                            for button in snapshot.navigation
                            if button.field_type in {"navigation_continue", "navigation_review"}
                        ),
                        None,
                    )
                    if continue_control:
                        run.current_step = f"click:{continue_control.original_label}"
                        session.flush()
                        page.get_by_role(
                            "button", name=continue_control.original_label, exact=True
                        ).first.click()
                        page.wait_for_timeout(250)
                        attempt.checkpoint = f"STEP_{step_index}_COMPLETE"
                        attempt.status = "running"
                        continue
                    run.status = "needs_input"
                    run.metadata_ = {
                        **(run.metadata_ or {}),
                        "failure_category": "SITE_CHANGED",
                    }
                    _write_run_files(run, application, last_mappings, settings, snapshot=snapshot)
                    session.commit()
                    return {
                        "run_id": str(run.id),
                        "status": run.status,
                        "message": "No safe navigation or final review control detected.",
                    }
                run.status = "failed"
                _write_run_files(run, application, last_mappings, settings)
                session.commit()
                return {
                    "run_id": str(run.id),
                    "status": run.status,
                    "message": "Maximum form steps exceeded.",
                }
        except HumanSubmissionRequired:
            raise
        except Exception as exc:
            with get_local_session(settings) as session:
                run = session.get(LocalBrowserRun, run_id)
                if run:
                    run.status = "failed"
                    run.metadata_ = {
                        **(run.metadata_ or {}),
                        "error": str(exc),
                        "failure_category": (
                            "BROWSER_CRASH" if "Target page" in str(exc) else "BROWSER_ERROR"
                        ),
                    }
                    attempt = _current_attempt(session, run)
                    attempt.status = "failed"
                    attempt.completed_at = _utcnow()
                    attempt.error_code = (
                        "BROWSER_CRASH" if "Target page" in str(exc) else "BROWSER_ERROR"
                    )
            raise BrowserAutomationError(str(exc)) from exc
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()


def run_browser(
    application_id: UUID,
    settings: Settings | None = None,
    *,
    mode: str = "autofill",
    dogfood: bool = False,
) -> dict[str, Any]:
    config = settings or get_settings()
    run_id = _create_run(application_id, config, mode=mode, dogfood=dogfood)
    return _execute_run(run_id, config, mode=mode)


def inspect_browser(
    application_id: UUID, settings: Settings | None = None, *, mode: str = "inspect"
) -> dict[str, Any]:
    """Open and snapshot a form without filling any field."""
    config = settings or get_settings()
    if not _playwright_available():
        raise BrowserAutomationError(
            "Playwright is not installed; run `recruiting setup browser --install`"
        )
    run_id = _create_run(application_id, config, mode=mode)
    from playwright.sync_api import sync_playwright

    with get_local_session(config) as session:
        run = session.get(LocalBrowserRun, run_id)
        application = session.get(Application, application_id)
        if run is None or application is None:
            raise BrowserAutomationError("browser run could not be created")
        run.status = "inspecting"
        session.commit()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=config.browser_headless, slow_mo=config.browser_slow_mo_ms
        )
        page = browser.new_page()
        try:
            page.set_default_timeout(config.browser_timeout_seconds * 1000)
            page.goto(
                run.original_url,
                wait_until="domcontentloaded",
                timeout=config.browser_timeout_seconds * 1000,
            )
            with get_local_session(config) as session:
                run = session.get(LocalBrowserRun, run_id)
                application = session.get(Application, application_id)
                if run is None or application is None:
                    raise BrowserAutomationError("browser run disappeared")
                adapter = adapter_for_page(page)
                detection = adapter.detect(page)
                run.detected_ats = detection.provider
                run.ats_confidence = detection.confidence
                snapshot = adapter.inspect(page, step_index=1)
                _persist_snapshot(session, run, snapshot)
                _screenshot(page, run, application, config, "001-initial")
                run.status = "needs_input"
                run.metadata_ = {
                    **(run.metadata_ or {}),
                    "inspection_only": True,
                    "detection_reasons": list(detection.reasons),
                }
                _write_run_files(run, application, [], config, snapshot=snapshot)
                session.commit()
                return {
                    "run_id": str(run_id),
                    "status": run.status,
                    "ats": detection.provider,
                    "field_count": len(snapshot.fields),
                }
        finally:
            browser.close()


def resume_browser(run_id: UUID, settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    with get_local_session(config) as session:
        run = session.get(LocalBrowserRun, run_id)
        if run is None:
            raise BrowserAutomationError("browser run not found locally")
        if run.status == "submitted_observed":
            raise BrowserAutomationError(
                "submitted browser runs are read-only and cannot be replayed"
            )
    return _execute_run(run_id, config, resume=True)


def browser_status(run_id: UUID, settings: Settings | None = None) -> dict[str, Any]:
    with get_local_session(settings or get_settings()) as session:
        run = session.get(LocalBrowserRun, run_id)
        if run is None:
            raise BrowserAutomationError("browser run not found")
        return {
            "run_id": str(run.id),
            "application_id": str(run.application_id),
            "status": run.status,
            "ats": run.detected_ats,
            "current_step": run.current_step,
            "screenshot_dir": run.screenshot_dir,
            "updated_at": run.updated_at.isoformat(),
            "dogfood": run.dogfood,
            "manual_intervention_count": run.manual_intervention_count,
            "feedback_status": run.feedback_status,
        }


def dogfood_report(settings: Settings | None = None) -> dict[str, Any]:
    """Summarize private dogfood runs without exposing field values."""
    config = settings or get_settings()
    with get_local_session(config) as session:
        runs = list(
            session.scalars(
                select(LocalBrowserRun)
                .where(LocalBrowserRun.dogfood.is_(True))
                .order_by(LocalBrowserRun.created_at)
            )
        )
    by_ats: dict[str, dict[str, int]] = {}
    failure_categories: dict[str, int] = {}
    for run in runs:
        provider = run.detected_ats or "unknown"
        bucket = by_ats.setdefault(provider, {"runs": 0, "ready": 0, "failed": 0})
        bucket["runs"] += 1
        bucket["ready"] += int(run.status == "ready_for_human_submission")
        bucket["failed"] += int(run.status in {"failed", "verification_failed"})
        category = str((run.metadata_ or {}).get("failure_category", "none"))
        if category != "none":
            failure_categories[category] = failure_categories.get(category, 0) + 1
    return {
        "runs": len(runs),
        "ready_for_submit": sum(run.status == "ready_for_human_submission" for run in runs),
        "median_manual_interventions": _median([run.manual_intervention_count for run in runs]),
        "ats": by_ats,
        "failure_categories": failure_categories,
        "privacy": "local-only; no automatic upload",
    }


def record_dogfood_feedback(
    run_id: UUID,
    feedback_status: str,
    note: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    allowed = {"worked_well", "minor_issue", "major_issue", "unusable"}
    if feedback_status not in allowed:
        raise BrowserAutomationError(f"feedback must be one of: {', '.join(sorted(allowed))}")
    config = settings or get_settings()
    with get_local_session(config) as session:
        run = session.get(LocalBrowserRun, run_id)
        if run is None:
            raise BrowserAutomationError("browser run not found")
        run.feedback_status = feedback_status
        run.feedback_note = note
        return {"run_id": str(run_id), "feedback_status": feedback_status}


def create_browser_issue(
    run_id: UUID,
    failure_category: str,
    description: str,
    *,
    priority: str = "P1",
    settings: Settings | None = None,
) -> dict[str, Any]:
    config = settings or get_settings()
    with get_local_session(config) as session:
        run = session.get(LocalBrowserRun, run_id)
        if run is None:
            raise BrowserAutomationError("browser run not found")
        issue = LocalBrowserIssue(
            provider=run.detected_ats,
            run_id=run.id,
            failure_category=failure_category,
            description=description,
            priority=priority,
        )
        session.add(issue)
        session.flush()
        return {"issue_id": str(issue.id), "run_id": str(run_id), "status": issue.status}


def _median(values: list[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def abort_browser(run_id: UUID, settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    with get_local_session(config) as session:
        run = session.get(LocalBrowserRun, run_id)
        if run is None:
            raise BrowserAutomationError("browser run not found")
        run.status = "aborted"
        run.completed_at = _utcnow()
        return {
            "run_id": str(run.id),
            "application_id": str(run.application_id),
            "status": run.status,
        }


def resolve_field(
    run_id: UUID,
    field_key: str,
    value: str,
    *,
    reusable: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    config = settings or get_settings()
    with get_local_session(config) as session:
        run = session.get(LocalBrowserRun, run_id)
        if run is None:
            raise BrowserAutomationError("browser run not found")
        field = session.scalar(
            select(LocalBrowserField)
            .where(LocalBrowserField.run_id == run.id, LocalBrowserField.field_key == field_key)
            .order_by(LocalBrowserField.created_at.desc())
        )
        if field is None:
            raise BrowserAutomationError("browser field not found")
        normalized_key = field.normalized_key or normalize_label(field.original_label)
        profile = session.scalar(select(CandidateProfile).order_by(CandidateProfile.created_at))
        if reusable and profile is not None:
            existing = session.scalar(
                select(LocalCandidateFormValue).where(
                    LocalCandidateFormValue.profile_id == profile.id,
                    LocalCandidateFormValue.normalized_key == normalized_key,
                )
            )
            if existing is None:
                session.add(
                    LocalCandidateFormValue(
                        profile_id=profile.id,
                        normalized_key=normalized_key,
                        original_question=field.original_label,
                        value=value,
                        sensitive=field.field_type == "sensitive",
                        reusable=True,
                        approved=True,
                    )
                )
            else:
                existing.value = value
                existing.approved = True
        else:
            session.add(
                LocalApplicationFormValue(
                    application_id=run.application_id,
                    normalized_key=normalized_key,
                    original_question=field.original_label,
                    value=value,
                    sensitive=field.field_type == "sensitive",
                    approved=True,
                )
            )
        run.status = "created"
        return {
            "run_id": str(run.id),
            "application_id": str(run.application_id),
            "field_key": field_key,
            "status": "saved",
            "reusable": reusable,
        }


def add_field_alias(
    label: str, normalized_key: str, settings: Settings | None = None
) -> dict[str, str]:
    config = settings or get_settings()
    normalized_label = normalize_label(label)
    with get_local_session(config) as session:
        existing = session.scalar(
            select(LocalBrowserFieldAlias).where(
                LocalBrowserFieldAlias.normalized_label == normalized_label,
                LocalBrowserFieldAlias.normalized_key == normalized_key,
            )
        )
        if existing is None:
            session.add(
                LocalBrowserFieldAlias(
                    label=label,
                    normalized_label=normalized_label,
                    normalized_key=normalized_key,
                    source="user",
                )
            )
    return {
        "label": label,
        "normalized_label": normalized_label,
        "normalized_key": normalized_key,
    }


def mark_submitted(run_id: UUID, settings: Settings | None = None) -> dict[str, Any]:
    """Record a user-observed submission; this function never clicks Submit."""
    from quant_recruiting.application_service import record_application_event

    config = settings or get_settings()
    with get_local_session(config) as session:
        run = session.get(LocalBrowserRun, run_id)
        if run is None:
            raise BrowserAutomationError("browser run not found")
        if run.status != RUN_READY:
            raise BrowserAutomationError(
                "only a ready-for-human-submission run can be marked submitted"
            )
        application = session.get(Application, run.application_id)
        if application is None:
            raise BrowserAutomationError("application not found")
        run.status = "submitted_observed"
        run.completed_at = _utcnow()
        record_application_event(
            session,
            application,
            event_type="submitted",
            source_type="local_browser_manual",
            new_status="applied",
            source_reference=str(run.id),
            notes="Submission observed after explicit human action.",
        )
        return {"run_id": str(run.id), "status": run.status, "application_id": str(application.id)}
