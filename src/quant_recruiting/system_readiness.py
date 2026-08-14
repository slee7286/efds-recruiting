"""Local operational readiness checks with no secret/value logging."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any

import httpx

from quant_recruiting import __version__
from quant_recruiting.config import Settings, get_settings
from quant_recruiting.local_db import local_diagnostics
from quant_recruiting.local_ops import cloud_sync_warnings
from quant_recruiting.secrets import SecretStoreUnavailable, get_secret_store
from quant_recruiting.windows_scheduler import task_status


def _check(name: str, ready: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "status": "READY" if ready else "NOT_READY", "detail": detail}


def system_readiness(settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    checks: list[dict[str, Any]] = []
    try:
        db = local_diagnostics(config)
        checks.append(
            _check(
                "Local SQLite",
                db["integrity"] == "ok" and bool(db["foreign_keys"]) and bool(db["fts5"]),
                f"{db['path']}; WAL={db['journal_mode']}",
            )
        )
    except Exception as exc:
        checks.append(_check("Local SQLite", False, str(exc)))
    api_detail = "not configured"
    api_ready = not config.shared_enabled or not config.shared_api_url
    if config.shared_enabled and config.shared_api_url and not config.offline_mode:
        try:
            response = httpx.get(f"{config.shared_api_url.rstrip('/')}/api/v1/health", timeout=3)
            api_ready = response.is_success
            api_detail = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            api_ready = False
            api_detail = f"offline: {type(exc).__name__}"
    checks.append(_check("Shared API", api_ready, api_detail))
    try:
        store = get_secret_store(config)
        account = store.get("gmail.oauth.account")
        checks.append(_check("Gmail", bool(account), account or "not connected"))
    except SecretStoreUnavailable as exc:
        checks.append(_check("Gmail", False, str(exc)))
    playwright_ready = importlib.util.find_spec("playwright") is not None
    chromium_detail = "not checked"
    chromium_ready = False
    if playwright_ready:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                executable = playwright.chromium.executable_path
            chromium_ready = bool(executable and Path(executable).exists())
            chromium_detail = executable
        except Exception as exc:
            chromium_detail = str(exc)
    checks.append(_check("Playwright", playwright_ready))
    checks.append(_check("Chromium", chromium_ready, chromium_detail))
    tex = shutil.which(config.tex_engine)
    checks.append(_check("MiKTeX/TeX", bool(tex), tex or f"{config.tex_engine} not found"))
    scheduler = task_status()
    checks.append(
        _check(
            "Task Scheduler",
            bool(scheduler.get("installed")),
            "installed"
            if scheduler.get("installed")
            else str(scheduler.get("error", "not installed")),
        )
    )
    checks.append(_check("Windows notifications", True, "dashboard fallback available"))
    return {
        "product_version": __version__,
        "checks": checks,
        "cloud_sync_warnings": cloud_sync_warnings(config.local_data_dir),
        "private_push_enabled": False,
        "offline_mode": config.offline_mode,
    }
