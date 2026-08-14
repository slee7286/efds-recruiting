"""Explicit, conservative ATS capability metadata.

Detection and autofill support are deliberately separate.  A provider can be
recognized reliably while still being unsafe to automate beyond inspection.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

SUPPORTED = "SUPPORTED"
PARTIAL = "PARTIAL"
EXPERIMENTAL = "EXPERIMENTAL"
DETECTED_ONLY = "DETECTED_ONLY"
UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class ATSProviderCapabilities:
    provider: str
    detection: str
    inspection: str
    identity: str
    education: str
    experience: str
    documents: str
    custom_questions: str
    dynamic_fields: str
    multi_step_navigation: str
    account_required: str
    verification: str
    final_submit_detection: str
    notes: str = ""
    fixture_count: int = 0
    real_world_fixture_count: int = 0
    last_verified: str | None = None
    known_limitations: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_CAPABILITIES: dict[str, ATSProviderCapabilities] = {
    "greenhouse": ATSProviderCapabilities(
        "greenhouse",
        SUPPORTED,
        SUPPORTED,
        SUPPORTED,
        PARTIAL,
        PARTIAL,
        SUPPORTED,
        SUPPORTED,
        PARTIAL,
        SUPPORTED,
        PARTIAL,
        SUPPORTED,
        SUPPORTED,
        "Fixture-backed conservative autofill with a mandatory submit gate.",
    ),
    "lever": ATSProviderCapabilities(
        "lever",
        SUPPORTED,
        SUPPORTED,
        SUPPORTED,
        PARTIAL,
        PARTIAL,
        SUPPORTED,
        SUPPORTED,
        PARTIAL,
        SUPPORTED,
        PARTIAL,
        SUPPORTED,
        SUPPORTED,
        "Fixture-backed conservative autofill with custom-question preservation.",
    ),
    "ashby": ATSProviderCapabilities(
        "ashby",
        SUPPORTED,
        SUPPORTED,
        SUPPORTED,
        PARTIAL,
        PARTIAL,
        SUPPORTED,
        SUPPORTED,
        PARTIAL,
        SUPPORTED,
        PARTIAL,
        SUPPORTED,
        SUPPORTED,
        "Fixture-backed conservative autofill for common Ashby forms.",
    ),
    "workday": ATSProviderCapabilities(
        "workday",
        SUPPORTED,
        SUPPORTED,
        PARTIAL,
        EXPERIMENTAL,
        EXPERIMENTAL,
        SUPPORTED,
        PARTIAL,
        EXPERIMENTAL,
        PARTIAL,
        PARTIAL,
        PARTIAL,
        SUPPORTED,
        "Manual login, parser mismatch review, and repeaters remain human-gated.",
    ),
    "smartrecruiters": ATSProviderCapabilities(
        "smartrecruiters",
        SUPPORTED,
        SUPPORTED,
        PARTIAL,
        EXPERIMENTAL,
        EXPERIMENTAL,
        SUPPORTED,
        PARTIAL,
        PARTIAL,
        PARTIAL,
        PARTIAL,
        PARTIAL,
        SUPPORTED,
        "Conservative common-form support; employer customizations may pause.",
    ),
    "icims": ATSProviderCapabilities(
        "icims",
        SUPPORTED,
        SUPPORTED,
        PARTIAL,
        EXPERIMENTAL,
        EXPERIMENTAL,
        PARTIAL,
        EXPERIMENTAL,
        EXPERIMENTAL,
        PARTIAL,
        PARTIAL,
        EXPERIMENTAL,
        SUPPORTED,
        "Iframe/session-heavy flows are experimental and may require assisted mode.",
    ),
    "workable": ATSProviderCapabilities(
        "workable",
        SUPPORTED,
        SUPPORTED,
        PARTIAL,
        EXPERIMENTAL,
        EXPERIMENTAL,
        SUPPORTED,
        PARTIAL,
        PARTIAL,
        PARTIAL,
        PARTIAL,
        PARTIAL,
        SUPPORTED,
        "Basic public application forms only.",
    ),
    "bamboohr": ATSProviderCapabilities(
        "bamboohr",
        SUPPORTED,
        SUPPORTED,
        PARTIAL,
        EXPERIMENTAL,
        EXPERIMENTAL,
        PARTIAL,
        EXPERIMENTAL,
        EXPERIMENTAL,
        PARTIAL,
        PARTIAL,
        EXPERIMENTAL,
        SUPPORTED,
        "Detection and conservative standard fields; custom employer fields pause.",
    ),
    "successfactors": ATSProviderCapabilities(
        "successfactors",
        SUPPORTED,
        SUPPORTED,
        EXPERIMENTAL,
        EXPERIMENTAL,
        EXPERIMENTAL,
        PARTIAL,
        EXPERIMENTAL,
        EXPERIMENTAL,
        EXPERIMENTAL,
        PARTIAL,
        EXPERIMENTAL,
        SUPPORTED,
        "Detection is reliable; tenant-specific flows vary.",
    ),
    "taleo": ATSProviderCapabilities(
        "taleo",
        SUPPORTED,
        PARTIAL,
        DETECTED_ONLY,
        DETECTED_ONLY,
        DETECTED_ONLY,
        DETECTED_ONLY,
        DETECTED_ONLY,
        DETECTED_ONLY,
        DETECTED_ONLY,
        PARTIAL,
        DETECTED_ONLY,
        SUPPORTED,
        "Detection only until tenant fixtures prove safe filling.",
    ),
    "generic": ATSProviderCapabilities(
        "generic",
        PARTIAL,
        PARTIAL,
        PARTIAL,
        DETECTED_ONLY,
        DETECTED_ONLY,
        PARTIAL,
        PARTIAL,
        PARTIAL,
        PARTIAL,
        PARTIAL,
        PARTIAL,
        SUPPORTED,
        "Accessible, high-confidence fields only; unsupported controls remain manual.",
    ),
}


def capabilities_for(provider: str) -> ATSProviderCapabilities:
    """Return capability metadata, defaulting to the conservative generic level."""
    return _CAPABILITIES.get(provider.lower(), _CAPABILITIES["generic"])


def all_capabilities() -> tuple[ATSProviderCapabilities, ...]:
    return tuple(_CAPABILITIES.values())


def capability_report(settings: Any | None = None) -> list[dict[str, Any]]:
    """Return capability metadata plus evidence discovered locally.

    Counts are derived from fixture metadata when available.  Missing metadata
    remains zero; the report never invents real-world verification.
    """
    import json
    from pathlib import Path

    roots: list[Path] = [Path("tests") / "fixtures" / "ats"]
    if settings is not None:
        roots.append(Path(settings.local_data_dir) / "cache" / "ats-fixtures")
    evidence: dict[str, list[tuple[bool, str | None]]] = {}
    for root in roots:
        if not root.exists():
            continue
        for metadata_path in root.glob("**/metadata.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            provider = str(metadata.get("provider", metadata_path.parent.parent.name)).lower()
            evidence.setdefault(provider, []).append(
                (metadata.get("source_kind") == "real_sanitized", metadata.get("captured_at"))
            )
    report: list[dict[str, Any]] = []
    for capability in all_capabilities():
        records = evidence.get(capability.provider, [])
        dates = [value for _, value in records if isinstance(value, str)]
        last_verified = max(dates) if dates else capability.last_verified
        limitations = capability.known_limitations or (
            (capability.notes,) if capability.notes else ()
        )
        report.append(
            {
                **capability.as_dict(),
                "fixture_count": len(records),
                "real_world_fixture_count": sum(1 for real, _ in records if real),
                "last_verified": last_verified,
                "known_limitations": list(limitations),
            }
        )
    return report


class ATSAdapterRegistry:
    """Small registry used by the browser layer and local diagnostics."""

    def __init__(self) -> None:
        self._adapters: dict[str, Any] = {}

    def register(self, provider: str, adapter: Any) -> None:
        self._adapters[provider.lower()] = adapter

    def get(self, provider: str) -> Any | None:
        return self._adapters.get(provider.lower())

    def capabilities(self) -> list[dict[str, Any]]:
        return [
            {**capability.as_dict(), "adapter_registered": name in self._adapters}
            for name, capability in ((item.provider, item) for item in all_capabilities())
        ]
