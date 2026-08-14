"""Process helpers for the loopback Recruiting Assistant server."""

from __future__ import annotations

import os
import webbrowser
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from quant_recruiting.companion_app import create_companion_app
from quant_recruiting.config import Settings, get_settings


@contextmanager
def server_lock(data_dir: Path) -> Generator[None]:
    lock_path = data_dir / "app.lock"
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        with lock_path.open("x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError as exc:
        raise RuntimeError(f"local app appears to be running: {lock_path}") from exc
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def app_url(
    settings: Settings | None = None, *, host: str | None = None, port: int | None = None
) -> str:
    config = settings or get_settings()
    return f"http://{host or config.local_host}:{port or config.local_port}"


def serve_companion(
    settings: Settings | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    open_browser: bool | None = None,
) -> None:
    config = settings or get_settings()
    selected_host = host or config.local_host
    selected_port = port or config.local_port
    url = app_url(config, host=selected_host, port=selected_port)
    if open_browser if open_browser is not None else config.auto_open_browser:
        webbrowser.open(url)
    with server_lock(config.local_data_dir):
        uvicorn.run(
            create_companion_app(config),
            host=selected_host,
            port=selected_port,
            log_level="info",
        )
