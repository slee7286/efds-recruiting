"""Private local data diagnostics, backup, restore, export, and cleanup."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_recruiting.config import Settings, get_settings
from quant_recruiting.local_db import get_local_engine, local_diagnostics, upgrade_local

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017 - Python 3.10 compatibility


def cloud_sync_warnings(path: Path) -> list[str]:
    """Warn, without blocking, when private data is under common sync folders."""
    parts = {part.casefold() for part in path.resolve().parts}
    matches = {
        "onedrive": "OneDrive",
        "dropbox": "Dropbox",
        "google drive": "Google Drive",
        "icloud": "iCloud",
    }
    return [
        f"private path appears under {label}; cloud synchronization may copy sensitive data"
        for token, label in matches.items()
        if any(token in part for part in parts)
    ]


def _safe_restore_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if candidate != root.resolve() and root.resolve() not in candidate.parents:
        raise ValueError(f"unsafe backup path: {relative}")
    return candidate


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_doctor(settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    result = local_diagnostics(config)
    from quant_recruiting.browser_engine import browser_diagnostics

    browser = browser_diagnostics(config)
    from quant_recruiting.windows_scheduler import task_status

    try:
        from quant_recruiting.secrets import SecretStoreUnavailable, get_secret_store

        gmail_account = get_secret_store(config).get("gmail.oauth.account")
        gmail_status = "connected" if gmail_account else "not connected"
    except SecretStoreUnavailable:
        gmail_status = "secret store unavailable"
    result.update(
        {
            "data_dir_exists": config.local_data_dir.exists(),
            "database_exists": (config.local_data_dir / "recruiting.db").exists(),
            "writeable": _is_writeable(config.local_data_dir),
            "private_push_enabled": False,
            "shared_configured": bool(
                config.shared_enabled
                and (
                    (config.shared_transport == "api" and config.shared_api_url)
                    or config.shared_database_url
                )
            ),
            "shared_transport": config.shared_transport,
            "browser_profiles": str(config.local_data_dir / "browser-profiles"),
            "background_lock": str(config.local_data_dir / "cache" / "background-run.lock"),
            "task_scheduler": task_status(),
            "gmail_oauth": gmail_status,
            "cloud_sync_warnings": cloud_sync_warnings(config.local_data_dir),
            **browser,
        }
    )
    return result


def _is_writeable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def backup_local(
    settings: Settings | None = None,
    *,
    destination: Path | None = None,
    include_browser_state: bool = False,
) -> Path:
    config = settings or get_settings()
    upgrade_local(config)
    engine = get_local_engine(config)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    engine.dispose()
    target = destination or (
        config.local_data_dir.parent
        / f"recruiting-backup-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.zip"
    )
    if target.exists():
        raise FileExistsError(target)
    manifest: list[dict[str, str]] = []
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in config.local_data_dir.rglob("*"):
            if not file.is_file():
                continue
            relative = file.relative_to(config.local_data_dir)
            if not include_browser_state and (
                "browser-profiles" in relative.parts or "screenshots" in relative.parts
            ):
                continue
            archive.write(file, Path("recruiting-assistant") / relative)
            manifest.append({"path": str(relative), "sha256": _file_hash(file)})
        archive.writestr(
            "recruiting-assistant/backup-manifest.json",
            json.dumps(
                {"version": 1, "created_at": datetime.now(UTC).isoformat(), "files": manifest},
                indent=2,
            )
            + "\n",
        )
    return target


def restore_local(
    backup: Path, settings: Settings | None = None, *, destination: Path | None = None
) -> Path:
    config = settings or get_settings()
    target = destination or (
        config.local_data_dir.parent / f"restored-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    if target.exists():
        raise FileExistsError(target)
    with zipfile.ZipFile(backup) as archive:
        names = archive.namelist()
        manifest_name = "recruiting-assistant/backup-manifest.json"
        if manifest_name not in names:
            raise ValueError("backup manifest is missing")
        manifest = json.loads(archive.read(manifest_name))
        if manifest.get("version") != 1:
            raise ValueError("unsupported backup version")
        entries: list[tuple[dict[str, str], str, Path]] = []
        for item in manifest["files"]:
            member = f"recruiting-assistant/{item['path']}"
            if member not in names:
                raise ValueError(f"backup member is missing: {item['path']}")
            destination_path = _safe_restore_path(target, item["path"])
            entries.append((item, member, destination_path))
        target.mkdir(parents=True)
        for item, member, destination_path in entries:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination_path.open("wb") as output:
                shutil.copyfileobj(source, output)
            if _file_hash(destination_path) != item["sha256"]:
                raise ValueError(f"backup hash mismatch: {item['path']}")
    return target


def export_local(settings: Settings | None = None, *, destination: Path | None = None) -> Path:
    config = settings or get_settings()
    target = destination or (
        config.local_data_dir.parent
        / f"recruiting-export-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(
        config.local_data_dir,
        target,
        ignore=shutil.ignore_patterns("browser-profiles", "*.db-shm", "*.db-wal"),
    )
    return target


def cleanup_local(
    settings: Settings | None = None,
    *,
    cache: bool = False,
    browser_screenshots: bool = False,
    temp: bool = False,
    old_ai_exports: bool = False,
) -> list[str]:
    config = settings or get_settings()
    targets: list[Path] = []
    if cache:
        targets.extend([config.local_data_dir / "cache", config.local_data_dir / "research-cache"])
    if browser_screenshots:
        targets.extend(config.local_data_dir.glob("applications/*/browser/screenshots"))
    if temp:
        targets.extend(config.local_data_dir.glob("applications/*/browser/temp"))
    if old_ai_exports:
        targets.extend(config.local_data_dir.glob("applications/*/ai/*/raw"))
    removed = []
    for target in targets:
        if target.exists() and target.is_dir():
            shutil.rmtree(target)
            removed.append(str(target))
    return removed


def wipe_local(settings: Settings | None = None, *, confirmation: str) -> str:
    config = settings or get_settings()
    if confirmation != "WIPE LOCAL RECRUITING DATA":
        raise ValueError("strong confirmation phrase required")
    if not config.local_data_dir.exists():
        return "nothing to wipe"
    shutil.rmtree(config.local_data_dir)
    return str(config.local_data_dir)
