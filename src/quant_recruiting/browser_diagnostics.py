"""Privacy-safe inspect-only fixture capture for adapter development."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

from quant_recruiting.browser_forms import adapter_for_page
from quant_recruiting.config import Settings, get_settings

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017


def sanitize_dom(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    secret_words = re.compile(r"token|csrf|auth|session|password|secret|cookie", re.I)
    for element in soup.find_all(True):
        for attribute in list(element.attrs):
            value = str(element.attrs.get(attribute, ""))
            if attribute.lower() in {"value", "data-value", "content"}:
                del element.attrs[attribute]
            elif secret_words.search(attribute) or secret_words.search(value):
                del element.attrs[attribute]
        if element.name == "textarea":
            element.clear()
        if element.name == "input" and str(element.get("type", "")).lower() == "password":
            element.clear()
    return str(soup)


def capture_fixture(
    url: str, settings: Settings | None = None, *, source_kind: str = "sanitized_capture"
) -> dict[str, Any]:
    """Capture structure only; this function never fills or submits a page."""
    config = settings or get_settings()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed; run `recruiting setup browser --install`"
        ) from exc
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=config.browser_headless)
        page = browser.new_page()
        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=int(config.browser_timeout_seconds * 1000),
            )
            adapter = adapter_for_page(page)
            detection = adapter.detect(page)
            snapshot = adapter.inspect(page, step_index=1)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            root = config.local_data_dir / "cache" / "ats-fixtures" / detection.provider / stamp
            root.mkdir(parents=True, exist_ok=False)
            (root / "sanitized-dom.html").write_text(sanitize_dom(page.content()), encoding="utf-8")
            (root / "form-snapshot.json").write_text(
                json.dumps(asdict(snapshot), indent=2, ensure_ascii=False, default=str) + "\n",
                encoding="utf-8",
            )
            metadata = {
                "fixture_schema_version": 1,
                "source_kind": source_kind,
                "contains_private_data": False,
                "url": url,
                "title": page.title(),
                "provider": detection.provider,
                "confidence": detection.confidence,
                "reasons": list(detection.reasons),
                "captured_at": datetime.now(UTC).isoformat(),
                "fill_performed": False,
                "submit_performed": False,
                "path": str(root),
            }
            (root / "metadata.json").write_text(
                json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
            )
            return metadata
        finally:
            browser.close()
