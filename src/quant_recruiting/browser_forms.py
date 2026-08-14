"""Conservative, provider-neutral form inspection and field mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

from quant_recruiting.ats_capabilities import ATSAdapterRegistry

FIELD_TYPES = {
    "identity",
    "contact",
    "address",
    "education",
    "experience",
    "documents",
    "short_text",
    "long_text",
    "numeric",
    "date",
    "single_select",
    "multi_select",
    "radio",
    "checkbox",
    "sensitive",
    "legal_attestation",
    "consent",
    "unknown",
    "navigation",
    "final_submit",
}

SENSITIVE_TERMS = (
    "sponsorship",
    "work authorization",
    "work authorisation",
    "citizenship",
    "nationality",
    "race",
    "ethnicity",
    "gender",
    "sexual orientation",
    "disability",
    "veteran",
    "criminal",
    "salary expectation",
    "conflict of interest",
    "relocation",
)
LEGAL_TERMS = (
    "i certify",
    "i confirm",
    "i acknowledge",
    "i agree",
    "i consent",
    "by checking",
    "accurate and complete",
)
FINAL_SUBMIT_TERMS = (
    "submit application",
    "submit",
    "send application",
    "finish application",
    "complete application",
    "apply now",
)
CONTINUE_TERMS = ("next", "continue", "save and continue", "review application", "review")


def normalize_label(value: str) -> str:
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).replace("_", " ").strip().lower()
    return re.sub(r"\s+", " ", value)


def compact_key(value: str) -> str:
    return normalize_label(value).replace(" ", "_")


def sensitive_key(value: str) -> str:
    normalized = normalize_label(value)
    aliases = (
        ("sponsorship", "visa_sponsorship"),
        ("work authorization", "work_authorization"),
        ("work authorisation", "work_authorization"),
        ("citizenship", "citizenship"),
        ("nationality", "nationality"),
        ("race", "race_ethnicity"),
        ("ethnicity", "race_ethnicity"),
        ("gender", "gender"),
        ("sexual orientation", "sexual_orientation"),
        ("disability", "disability"),
        ("veteran", "veteran_status"),
        ("criminal", "criminal_history"),
        ("salary expectation", "salary_expectations"),
        ("conflict of interest", "conflicts_of_interest"),
        ("relocation", "relocation_commitment"),
    )
    for term, key in aliases:
        if term in normalized:
            return key
    return compact_key(value)


@dataclass(frozen=True)
class FormField:
    field_key: str
    selector: str
    original_label: str
    field_type: str
    input_type: str | None = None
    html_name: str | None = None
    html_id: str | None = None
    aria_label: str | None = None
    placeholder: str | None = None
    required: bool = False
    visible: bool = True
    disabled: bool = False
    options: tuple[str, ...] = ()
    current_value: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FormSnapshot:
    url: str
    title: str
    step_index: int
    fields: tuple[FormField, ...]
    navigation: tuple[FormField, ...] = ()


@dataclass(frozen=True)
class DetectionResult:
    provider: str
    confidence: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class FieldMapping:
    field: FormField
    normalized_key: str | None
    source_key: str | None
    value: Any = None
    method: str = "unmapped"
    confidence: str = "unmapped"
    reason: str = "No approved deterministic mapping found."
    status: str = "needs_input"
    sensitive: bool = False
    actual_value: Any = None


@dataclass(frozen=True)
class FieldMappingResult:
    mappings: tuple[FieldMapping, ...]

    @property
    def unresolved_required(self) -> tuple[FieldMapping, ...]:
        return tuple(
            mapping
            for mapping in self.mappings
            if mapping.field.required and mapping.status in {"needs_input", "failed"}
        )


class ApplicationFormAdapter(Protocol):
    provider: str

    def detect(self, page: Any) -> DetectionResult: ...

    def inspect(self, page: Any, *, step_index: int = 0) -> FormSnapshot: ...

    def map_fields(self, snapshot: FormSnapshot, payload: dict[str, Any]) -> FieldMappingResult: ...

    def fill(self, page: Any, mapping: FieldMappingResult) -> list[FieldMapping]: ...

    def verify(self, page: Any, mapping: FieldMappingResult) -> list[FieldMapping]: ...

    def classify_navigation_action(self, label: str) -> str: ...


def _identity(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("identity", {}) if isinstance(payload.get("identity"), dict) else {}


def _documents(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("documents", {}) if isinstance(payload.get("documents"), dict) else {}


def _sensitive(payload: dict[str, Any]) -> dict[str, Any]:
    return (
        payload.get("sensitive_fields", {})
        if isinstance(payload.get("sensitive_fields"), dict)
        else {}
    )


def _question_value(label: str, payload: dict[str, Any]) -> tuple[str | None, Any]:
    normalized = normalize_label(label)
    for question in payload.get("questions", []):
        if not isinstance(question, dict):
            continue
        original = str(question.get("original_question", ""))
        if original and normalize_label(original) == normalized:
            return f"question:{question.get('application_question_id')}", question.get("answer")
    return None, None


def _value_for_key(key: str, payload: dict[str, Any]) -> tuple[str | None, Any]:
    identity = _identity(payload)
    documents = _documents(payload)
    sensitive = _sensitive(payload)
    direct: dict[str, tuple[str, Any]] = {
        "first_name": ("identity.first_name", identity.get("first_name")),
        "last_name": ("identity.last_name", identity.get("last_name")),
        "full_name": ("identity.name", identity.get("name")),
        "name": ("identity.name", identity.get("name")),
        "email": ("identity.email", identity.get("email")),
        "phone": ("identity.phone", identity.get("phone")),
        "linkedin": ("identity.linkedin", identity.get("linkedin")),
        "github": ("identity.github", identity.get("github")),
        "website": ("identity.website", identity.get("website")),
        "university": (
            "education[0].university",
            (payload.get("education") or [{}])[0].get("university"),
        ),
        "school": (
            "education[0].university",
            (payload.get("education") or [{}])[0].get("university"),
        ),
        "degree": ("education[0].degree", (payload.get("education") or [{}])[0].get("degree")),
        "field_of_study": (
            "education[0].subject",
            (payload.get("education") or [{}])[0].get("subject"),
        ),
        "subject": ("education[0].subject", (payload.get("education") or [{}])[0].get("subject")),
        "graduation_date": (
            "education[0].graduation_date",
            (payload.get("education") or [{}])[0].get("graduation_date"),
        ),
        "resume": ("documents.cv", documents.get("cv")),
        "cv": ("documents.cv", documents.get("cv")),
        "cover_letter": ("documents.cover_letter", documents.get("cover_letter")),
    }
    if key in direct:
        source, value = direct[key]
        return source, value
    if key in sensitive:
        return f"sensitive_fields.{key}", sensitive.get(key)
    return None, None


ALIASES: dict[str, tuple[str, str]] = {
    "first name": ("first_name", "identity"),
    "given name": ("first_name", "identity"),
    "legal first name": ("first_name", "identity"),
    "forename": ("first_name", "identity"),
    "full name": ("full_name", "identity"),
    "name": ("full_name", "identity"),
    "last name": ("last_name", "identity"),
    "surname": ("last_name", "identity"),
    "family name": ("last_name", "identity"),
    "email": ("email", "contact"),
    "email address": ("email", "contact"),
    "phone": ("phone", "contact"),
    "phone number": ("phone", "contact"),
    "mobile number": ("phone", "contact"),
    "linkedin": ("linkedin", "contact"),
    "linkedin url": ("linkedin", "contact"),
    "github": ("github", "contact"),
    "personal website": ("website", "contact"),
    "website": ("website", "contact"),
    "school": ("school", "education"),
    "university": ("university", "education"),
    "institution": ("university", "education"),
    "degree": ("degree", "education"),
    "field of study": ("field_of_study", "education"),
    "major": ("field_of_study", "education"),
    "graduation date": ("graduation_date", "education"),
    "expected graduation date": ("graduation_date", "education"),
    "resume": ("resume", "documents"),
    "résumé": ("resume", "documents"),
    "cv": ("cv", "documents"),
    "curriculum vitae": ("cv", "documents"),
    "cover letter": ("cover_letter", "documents"),
}


def _classify(label: str, input_type: str | None, tag: str) -> tuple[str, bool]:
    normalized = normalize_label(label)
    sensitive = any(term in normalized for term in SENSITIVE_TERMS)
    legal = any(term in normalized for term in LEGAL_TERMS)
    if sensitive:
        return "sensitive", True
    if legal:
        return "legal_attestation", False
    if tag == "input" and input_type == "file":
        return "documents", False
    if tag == "textarea":
        return "long_text", False
    if tag == "select":
        return "multi_select" if input_type == "multiple" else "single_select", False
    if input_type == "checkbox":
        return (
            "consent" if "privacy" in normalized or "marketing" in normalized else "checkbox",
            False,
        )
    if input_type == "radio":
        return "radio", False
    if input_type in {"date", "month", "datetime-local"}:
        return "date", False
    if input_type in {"number", "range"}:
        return "numeric", False
    if any(
        term in normalized for term in ("address", "city", "postcode", "postal code", "country")
    ):
        return "address", False
    if any(
        term in normalized for term in ("school", "university", "degree", "graduation", "education")
    ):
        return "education", False
    if any(
        term in normalized
        for term in ("company", "employer", "organization", "job title", "experience")
    ):
        return "experience", False
    return "short_text", False


class GenericHTMLFormAdapter:
    provider = "generic"

    def detect(self, page: Any) -> DetectionResult:
        hostname = urlparse(page.url).hostname or ""
        return DetectionResult(
            self.provider, 0.35, (f"generic public form on {hostname or 'unknown host'}",)
        )

    def inspect(self, page: Any, *, step_index: int = 0) -> FormSnapshot:
        fields: list[FormField] = []
        count = page.locator("input, textarea, select").count()
        for index in range(count):
            locator = page.locator("input, textarea, select").nth(index)
            info = locator.evaluate(
                """el => {
                  const id = el.id || null;
                  const label = id ? document.querySelector(
                    `label[for="${CSS.escape(id)}"]`
                  ) : null;
                  const parent = el.closest('label, fieldset, p, div');
                  const text = label?.innerText || el.getAttribute('aria-label') ||
                    el.getAttribute('placeholder') || parent?.innerText || el.name || id || '';
                  return {tag: el.tagName.toLowerCase(), id, name: el.name || null,
                    type: el.type || null, aria: el.getAttribute('aria-label'),
                    placeholder: el.getAttribute('placeholder'), label: text.trim(),
                    required: !!el.required, disabled: !!el.disabled,
                    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
                    accept: el.getAttribute('accept'),
                    value: el.type === 'file' ? null : (el.value || ''),
                    options: el.tagName.toLowerCase() === 'select' ?
                      Array.from(el.options).map(o => o.textContent.trim()) : []};
                }"""
            )
            label = str(
                info.get("label") or info.get("name") or info.get("id") or f"field {index + 1}"
            )
            field_type, _ = _classify(label, info.get("type"), info.get("tag", ""))
            selector = (
                f"#{info['id']}"
                if info.get("id")
                else (
                    f"[name='{info['name']}']"
                    if info.get("name")
                    else f"input:nth-of-type({index + 1})"
                )
            )
            selector_method = (
                "stable_id"
                if info.get("id")
                else "html_name"
                if info.get("name")
                else "aria_label"
                if info.get("aria")
                else "label_or_structure"
            )
            fields.append(
                FormField(
                    field_key=f"field-{index + 1}",
                    selector=selector,
                    original_label=label,
                    field_type=field_type,
                    input_type=info.get("type"),
                    html_name=info.get("name"),
                    html_id=info.get("id"),
                    aria_label=info.get("aria"),
                    placeholder=info.get("placeholder"),
                    required=bool(info.get("required")),
                    visible=bool(info.get("visible", True)),
                    disabled=bool(info.get("disabled")),
                    options=tuple(str(item) for item in info.get("options", [])),
                    current_value=info.get("value"),
                    metadata={
                        "tag": info.get("tag"),
                        "accept": info.get("accept"),
                        "selector_method": selector_method,
                        "frame_url": str(page.url),
                    },
                )
            )
        buttons = []
        button_count = page.locator("button, input[type='submit'], input[type='button']").count()
        for index in range(button_count):
            button = page.locator("button, input[type='submit'], input[type='button']").nth(index)
            label = (
                button.inner_text()
                if button.evaluate("el => el.tagName.toLowerCase() === 'button'")
                else button.get_attribute("value")
            ) or ""
            label = str(label).strip()
            action = self.classify_navigation_action(label)
            buttons.append(
                FormField(f"button-{index + 1}", "", label, action, metadata={"action": action})
            )
        return FormSnapshot(
            str(page.url), str(page.title()), step_index, tuple(fields), tuple(buttons)
        )

    def map_fields(self, snapshot: FormSnapshot, payload: dict[str, Any]) -> FieldMappingResult:
        mappings: list[FieldMapping] = []
        for form_field in snapshot.fields:
            label_key = normalize_label(form_field.original_label)
            if form_field.field_type in {"legal_attestation", "consent"}:
                mappings.append(
                    FieldMapping(
                        form_field,
                        None,
                        None,
                        method="manual_gate",
                        confidence="low",
                        reason="Human review is required for legal or consent controls.",
                        status="needs_input",
                    )
                )
                continue
            if form_field.field_type == "sensitive":
                key = sensitive_key(label_key)
                source_key, value = _value_for_key(key, payload)
                if value is None:
                    mappings.append(
                        FieldMapping(
                            form_field,
                            key,
                            source_key,
                            method="sensitive_gate",
                            confidence="unmapped",
                            reason="No explicitly approved local sensitive value exists.",
                            status="needs_input",
                            sensitive=True,
                        )
                    )
                else:
                    mappings.append(
                        FieldMapping(
                            form_field,
                            key,
                            source_key,
                            value,
                            "approved_sensitive_value",
                            "exact",
                            "Explicit approved local sensitive value.",
                            "mapped",
                            True,
                        )
                    )
                continue
            key_and_method = ALIASES.get(label_key)
            application_values = payload.get("_application_form_values", {})
            if isinstance(application_values, dict) and label_key in application_values:
                source_key = f"application_form_values.{label_key}"
                value = application_values[label_key]
                mappings.append(
                    FieldMapping(
                        form_field,
                        label_key,
                        source_key,
                        value,
                        "local_application_override",
                        "exact",
                        "Explicit local application-only value.",
                        "mapped",
                    )
                )
                continue
            custom_aliases = payload.get("_field_aliases", {})
            custom_key = custom_aliases.get(label_key) if isinstance(custom_aliases, dict) else None
            if custom_key:
                source_key, value = _value_for_key(str(custom_key), payload)
                status = (
                    "mapped"
                    if value is not None
                    else ("needs_input" if form_field.required else "skipped_optional")
                )
                mappings.append(
                    FieldMapping(
                        form_field,
                        str(custom_key),
                        source_key,
                        value,
                        "user_alias",
                        "exact",
                        "Explicit local field alias.",
                        status,
                    )
                )
                continue
            if key_and_method is None:
                question_source, question_value = _question_value(
                    form_field.original_label, payload
                )
                if question_source is not None:
                    mappings.append(
                        FieldMapping(
                            form_field,
                            question_source,
                            question_source,
                            question_value,
                            "exact_question",
                            "exact",
                            "Exact original application question match.",
                            "mapped" if question_value is not None else "needs_input",
                        )
                    )
                    continue
                if form_field.required:
                    mappings.append(
                        FieldMapping(
                            form_field,
                            None,
                            None,
                            method="unmapped",
                            confidence="unmapped",
                            status="needs_input",
                        )
                    )
                else:
                    mappings.append(
                        FieldMapping(
                            form_field,
                            None,
                            None,
                            method="unmapped",
                            confidence="unmapped",
                            reason="Optional field was intentionally not guessed.",
                            status="skipped_optional",
                        )
                    )
                continue
            key, method_group = key_and_method
            source_key, value = _value_for_key(key, payload)
            if value is None:
                status = "needs_input" if form_field.required else "skipped_optional"
                mappings.append(
                    FieldMapping(
                        form_field,
                        key,
                        source_key,
                        method=f"alias:{method_group}",
                        confidence="high",
                        reason="Known field alias but no approved value is available.",
                        status=status,
                    )
                )
            else:
                mappings.append(
                    FieldMapping(
                        form_field,
                        key,
                        source_key,
                        value,
                        f"alias:{method_group}",
                        "exact",
                        "Explicit deterministic field alias.",
                        "mapped",
                    )
                )
        return FieldMappingResult(tuple(mappings))

    def fill(self, page: Any, mapping: FieldMappingResult) -> list[FieldMapping]:
        updated: list[FieldMapping] = []
        for item in mapping.mappings:
            if item.status != "mapped" or item.field.field_type in {
                "legal_attestation",
                "consent",
                "final_submit",
            }:
                updated.append(item)
                continue
            locator = page.locator(item.field.selector)
            try:
                if item.field.field_type == "documents":
                    locator.set_input_files(str(item.value))
                elif (
                    item.field.field_type in {"single_select", "multi_select", "sensitive"}
                    and item.field.metadata.get("tag") == "select"
                ):
                    values = item.value if isinstance(item.value, list) else [item.value]
                    locator.select_option(
                        label=[str(value) for value in values]
                        if item.field.field_type == "multi_select"
                        else str(values[0])
                    )
                elif item.field.field_type in {"checkbox", "radio"}:
                    if bool(item.value) and not locator.is_checked():
                        locator.check()
                else:
                    locator.fill(str(item.value))
            except Exception as exc:  # Playwright exceptions vary by browser version.
                updated.append(
                    FieldMapping(
                        item.field,
                        item.normalized_key,
                        item.source_key,
                        item.value,
                        item.method,
                        item.confidence,
                        str(exc),
                        "failed",
                        item.sensitive,
                    )
                )
            else:
                updated.append(item)
        return updated

    def verify(self, page: Any, mapping: FieldMappingResult) -> list[FieldMapping]:
        verified: list[FieldMapping] = []
        for item in mapping.mappings:
            if item.status != "mapped" or item.field.field_type in {
                "documents",
                "legal_attestation",
                "consent",
            }:
                verified.append(item)
                continue
            actual: Any = None
            try:
                actual = page.locator(item.field.selector).input_value()
                expected = str(item.value)
                status = "verified" if actual == expected else "verification_failed"
                reason = (
                    item.reason
                    if status == "verified"
                    else "Browser value differs from approved value."
                )
            except Exception as exc:
                status, reason = "verification_failed", str(exc)
            verified.append(
                FieldMapping(
                    item.field,
                    item.normalized_key,
                    item.source_key,
                    item.value,
                    item.method,
                    item.confidence,
                    reason,
                    status,
                    item.sensitive,
                    actual,
                )
            )
        return verified

    def classify_navigation_action(self, label: str) -> str:
        normalized = normalize_label(label)
        if any(term == normalized or term in normalized for term in FINAL_SUBMIT_TERMS):
            return "final_submit"
        if any(term in normalized for term in CONTINUE_TERMS):
            return "navigation_review" if "review" in normalized else "navigation_continue"
        if "back" in normalized:
            return "navigation_back"
        return "unknown_action"


class GreenhouseFormAdapter(GenericHTMLFormAdapter):
    provider = "greenhouse"

    def detect(self, page: Any) -> DetectionResult:
        host = (urlparse(page.url).hostname or "").lower()
        reasons = []
        if "greenhouse" in host:
            reasons.append("Greenhouse hostname match")
        if page.locator("#application_form, form#application_form").count():
            reasons.append("Greenhouse application form marker")
        return DetectionResult(
            self.provider,
            min(0.99, 0.9 + 0.04 * len(reasons)) if reasons else 0.1,
            tuple(reasons) or ("No Greenhouse marker detected",),
        )


class LeverFormAdapter(GenericHTMLFormAdapter):
    provider = "lever"

    def detect(self, page: Any) -> DetectionResult:
        host = (urlparse(page.url).hostname or "").lower()
        reasons = ("Lever hostname match",) if "lever.co" in host else ("No Lever marker detected",)
        return DetectionResult(self.provider, 0.98 if "lever.co" in host else 0.1, reasons)


class AshbyFormAdapter(GenericHTMLFormAdapter):
    provider = "ashby"

    def detect(self, page: Any) -> DetectionResult:
        host = (urlparse(page.url).hostname or "").lower()
        reasons = (
            ("Ashby hostname match",) if "ashbyhq.com" in host else ("No Ashby marker detected",)
        )
        return DetectionResult(self.provider, 0.98 if "ashbyhq.com" in host else 0.1, reasons)


class ProviderHTMLFormAdapter(GenericHTMLFormAdapter):
    """Conservative provider wrapper around the generic accessible form reader."""

    provider = "generic"
    host_markers: tuple[str, ...] = ()
    dom_markers: tuple[str, ...] = ()

    def detect(self, page: Any) -> DetectionResult:
        host = (urlparse(str(page.url)).hostname or "").lower()
        reasons: list[str] = []
        if any(marker in host for marker in self.host_markers):
            reasons.append(f"{self.provider} hostname match")
        for marker in self.dom_markers:
            try:
                if page.locator(marker).count():
                    reasons.append(f"{self.provider} DOM marker: {marker}")
            except Exception:
                continue
        if not reasons:
            reasons.append(f"No {self.provider} marker detected")
        confidence = 0.98 if len(reasons) >= 2 else (0.94 if reasons[0].endswith("match") else 0.1)
        return DetectionResult(self.provider, confidence, tuple(reasons))


class WorkdayFormAdapter(ProviderHTMLFormAdapter):
    provider = "workday"
    host_markers = ("myworkdayjobs.com", "workday.com")
    dom_markers = (
        "[data-automation-id='jobApplicationPage']",
        "[data-automation-id='applyManually']",
    )


class SmartRecruitersFormAdapter(ProviderHTMLFormAdapter):
    provider = "smartrecruiters"
    host_markers = ("smartrecruiters.com",)
    dom_markers = ("[data-testid*='application']",)


class ICIMSFormAdapter(ProviderHTMLFormAdapter):
    provider = "icims"
    host_markers = ("icims.com", "jobs.icims.com")
    dom_markers = ("[id*='iCIMS']",)


class WorkableFormAdapter(ProviderHTMLFormAdapter):
    provider = "workable"
    host_markers = ("workable.com",)
    dom_markers = ("[data-ui='application-form']",)


class BambooHRFormAdapter(ProviderHTMLFormAdapter):
    provider = "bamboohr"
    host_markers = ("bamboohr.com",)
    dom_markers = ("[data-testid*='application']",)


class SuccessFactorsFormAdapter(ProviderHTMLFormAdapter):
    provider = "successfactors"
    host_markers = ("successfactors.com", "jobs.sap.com")
    dom_markers = ("[data-automation-id='application-form']",)


class TaleoFormAdapter(ProviderHTMLFormAdapter):
    provider = "taleo"
    host_markers = ("taleo.net",)
    dom_markers = ()


def adapter_for_page(page: Any, provider: str | None = None) -> ApplicationFormAdapter:
    adapters: dict[str, ApplicationFormAdapter] = {
        "greenhouse": GreenhouseFormAdapter(),
        "lever": LeverFormAdapter(),
        "ashby": AshbyFormAdapter(),
        "workday": WorkdayFormAdapter(),
        "smartrecruiters": SmartRecruitersFormAdapter(),
        "icims": ICIMSFormAdapter(),
        "workable": WorkableFormAdapter(),
        "bamboohr": BambooHRFormAdapter(),
        "successfactors": SuccessFactorsFormAdapter(),
        "taleo": TaleoFormAdapter(),
        "generic": GenericHTMLFormAdapter(),
    }
    if provider and provider.lower() in adapters:
        return adapters[provider.lower()]
    detections = [
        adapter.detect(page) for adapter in adapters.values() if adapter.provider != "generic"
    ]
    if detections:
        best = max(detections, key=lambda result: result.confidence)
        if best.confidence >= 0.7:
            return adapters[best.provider]
    return adapters["generic"]


def adapter_registry() -> ATSAdapterRegistry:
    """Return the locally available adapter registry for diagnostics/UI."""
    registry = ATSAdapterRegistry()
    for provider in (
        "greenhouse",
        "lever",
        "ashby",
        "workday",
        "smartrecruiters",
        "icims",
        "workable",
        "bamboohr",
        "successfactors",
        "taleo",
        "generic",
    ):
        registry.register(provider, adapter_for_provider(provider))
    return registry


def adapter_for_provider(provider: str) -> ApplicationFormAdapter:
    adapters: dict[str, ApplicationFormAdapter] = {
        "greenhouse": GreenhouseFormAdapter(),
        "lever": LeverFormAdapter(),
        "ashby": AshbyFormAdapter(),
        "workday": WorkdayFormAdapter(),
        "smartrecruiters": SmartRecruitersFormAdapter(),
        "icims": ICIMSFormAdapter(),
        "workable": WorkableFormAdapter(),
        "bamboohr": BambooHRFormAdapter(),
        "successfactors": SuccessFactorsFormAdapter(),
        "taleo": TaleoFormAdapter(),
        "generic": GenericHTMLFormAdapter(),
    }
    return adapters.get(provider.lower(), adapters["generic"])
