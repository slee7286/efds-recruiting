"""Local notification delivery with an optional Windows toast adapter."""

from __future__ import annotations

import importlib
from typing import Any, Protocol


class DesktopNotifier(Protocol):
    def notify(self, title: str, body: str) -> bool: ...


class WindowsToastNotifier:
    """Best-effort adapter; dashboard notifications remain the fallback."""

    def notify(self, title: str, body: str) -> bool:
        try:
            xml_module = importlib.import_module("winrt.windows.data.xml.dom")
            notification_module = importlib.import_module("winrt.windows.ui.notifications")
        except ImportError:
            return False
        try:
            xml = xml_module.XmlDocument()
            xml.load_xml(
                "<toast><visual><binding template='ToastGeneric'>"
                f"<text>{_xml_escape(title)}</text><text>{_xml_escape(body)}</text>"
                "</binding></visual></toast>"
            )
            notifier = notification_module.ToastNotificationManager.create_toast_notifier(
                "Recruiting Assistant"
            )
            notifier.show(notification_module.ToastNotification(xml))
            return True
        except Exception:  # noqa: BLE001 - desktop availability must not break local workflows.
            return False


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def notify_locally(title: str, body: str, *, notifier: Any | None = None) -> bool:
    """Try a local desktop notification and return whether it was delivered."""
    adapter = notifier or WindowsToastNotifier()
    return bool(adapter.notify(title, body))
