"""Pure, deterministic opportunity digests for local synthetic captures.

This module deliberately does not import configuration, database, network, ATS,
browser, credential, or Factory code.  Its input is a strict inline capture
manifest and its output is an in-memory representation rendered as JSON and
Markdown by the same functions.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SCHEMA_VERSION = "efds-opportunity-capture-v1"
DIGEST_SCHEMA_VERSION = "efds-opportunity-digest-v1"
ADVISORY_RUBRIC_ID = "efds-opportunity-advisory-v1"
_SOURCE_STATUSES = {"complete", "failed", "partial", "truncated"}
_RECORD_STATUSES = {"included", "irrelevant", "unsupported", "malformed"}
_FACT_FIELDS = (
    "firm",
    "role",
    "location",
    "deadline",
    "eligibility",
    "job_url",
    "application_url",
)
_SOURCE_KEYS = {
    "source_id",
    "provider",
    "board_id",
    "source_url",
    "observed_at_utc",
    "capture_status",
    "records",
    "error",
}
_RECORD_KEYS = {
    "record_id",
    "record_status",
    "external_id",
    "raw_payload",
    "facts",
    "exclusion_reason",
}
_CLAIM_KEYS = {"value", "evidence"}
_EVIDENCE_KEYS = {"source_id", "record_id", "field", "locator", "quote"}


class DigestInputError(ValueError):
    """Raised when a capture manifest cannot safely enter the digest boundary."""


class _MalformedFact(DigestInputError):
    """Raised for a source claim that is structurally present but malformed."""


def _object(value: Any, context: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise DigestInputError(f"{context} must be an object")
    return value


def _string(value: Any, context: str) -> str:
    if type(value) is not str or not value.strip():
        raise DigestInputError(f"{context} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, context: str) -> str | None:
    if value is None:
        return None
    return _string(value, context)


def _list(value: Any, context: str) -> list[Any]:
    if type(value) is not list:
        raise DigestInputError(f"{context} must be an array")
    return value


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DigestInputError(f"value is not canonical JSON: {exc}") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DigestInputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _resolve_json_pointer(document: Any, pointer: str, context: str) -> Any:
    if type(pointer) is not str or not pointer.startswith("/"):
        raise DigestInputError(f"{context} must be a JSON Pointer")
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if type(current) is dict:
            if part not in current:
                raise DigestInputError(f"{context} does not resolve")
            current = current[part]
        elif type(current) is list and part.isdigit():
            index = int(part)
            if index >= len(current):
                raise DigestInputError(f"{context} does not resolve")
            current = current[index]
        else:
            raise DigestInputError(f"{context} does not resolve")
    return current


def _check_keys(value: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DigestInputError(f"{context} has unknown field(s): {', '.join(unknown)}")


def _canonical_url(value: Any, context: str) -> str:
    raw = _string(value, context)
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise DigestInputError(f"{context} must be an absolute http(s) URL")
        if parsed.username or parsed.password:
            raise DigestInputError(f"{context} must not contain user information")
        hostname = parsed.hostname
        if not hostname:
            raise DigestInputError(f"{context} must contain a hostname")
        port = parsed.port
    except DigestInputError:
        raise
    except ValueError as exc:
        raise DigestInputError(f"{context} is malformed: {exc}") from exc
    netloc = hostname.lower()
    if ":" in netloc and not netloc.startswith("["):
        netloc = f"[{netloc}]"
    default_port = (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    )
    if port is not None and not default_port:
        netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


def _timestamp(value: Any, context: str) -> str:
    raw = _string(value, context)
    if not raw.endswith("Z"):
        raise DigestInputError(f"{context} must use an explicit UTC Z suffix")
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00")
    except ValueError as exc:
        raise DigestInputError(f"{context} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo != UTC:
        raise DigestInputError(f"{context} must be UTC")
    return parsed.isoformat().replace("+00:00", "Z")


def _eligibility(value: Any, context: str) -> dict[str, str]:
    try:
        item = _object(value, context)
    except DigestInputError as exc:
        raise _MalformedFact(str(exc)) from exc
    if set(item) - {"dimension", "status", "detail"}:
        raise _MalformedFact(f"{context} has unknown fields")
    dimension = _string(item.get("dimension"), f"{context}.dimension")
    status = _string(item.get("status"), f"{context}.status")
    if dimension not in {"work_authorization", "sponsorship", "graduation"}:
        raise _MalformedFact(f"{context}.dimension is unsupported")
    if status not in {"required", "not_required", "eligible", "ineligible", "unknown"}:
        raise _MalformedFact(f"{context}.status is unsupported")
    result = {"dimension": dimension, "status": status}
    if "detail" in item:
        result["detail"] = _string(item["detail"], f"{context}.detail")
    return result


def _claim_value(value: Any, field: str, context: str) -> Any:
    if field == "eligibility":
        return _eligibility(value, context)
    result = _string(value, context)
    if field == "deadline":
        try:
            parsed = date.fromisoformat(result)
        except ValueError as exc:
            raise _MalformedFact(f"{context} must be an ISO date") from exc
        if parsed.isoformat() != result:
            raise _MalformedFact(f"{context} must be an ISO date")
    if field.endswith("_url") or field == "job_url":
        result = _canonical_url(result, context)
    return result


def _claim_text(value: Any) -> str:
    if type(value) is str:
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _validate_evidence(
    value: Any,
    *,
    source_id: str,
    record_id: str,
    field: str,
    claim_value: Any,
    raw_payload: dict[str, Any],
) -> list[dict[str, str]]:
    refs = _list(value, f"evidence for {record_id}.{field}")
    if not refs:
        raise DigestInputError(f"evidence for {record_id}.{field} must not be empty")
    normalized: list[dict[str, str]] = []
    for index, raw_ref in enumerate(refs):
        ref = _object(raw_ref, f"evidence {record_id}.{field}[{index}]")
        _check_keys(ref, _EVIDENCE_KEYS, f"evidence {record_id}.{field}[{index}]")
        if set(ref) - {"source_id", "record_id", "field", "locator", "quote"}:
            raise DigestInputError(f"invalid evidence fields for {record_id}.{field}")
        ref_source = _string(ref.get("source_id"), "evidence source_id")
        ref_record = _string(ref.get("record_id"), "evidence record_id")
        ref_field = _string(ref.get("field"), "evidence field")
        locator = _string(ref.get("locator"), "evidence locator")
        if (ref_source, ref_record, ref_field) != (source_id, record_id, field):
            raise DigestInputError(f"evidence identity does not match {record_id}.{field}")
        actual_value = _resolve_json_pointer(
            raw_payload, locator, f"evidence locator for {record_id}.{field}"
        )
        if field.endswith("_url") or field == "job_url":
            actual_value = _canonical_url(actual_value, f"evidence {record_id}.{field}")
        elif field == "eligibility":
            actual_value = _eligibility(actual_value, f"evidence {record_id}.{field}")
        else:
            actual_value = _string(actual_value, f"evidence {record_id}.{field}")
        if _canonical_bytes(actual_value) != _canonical_bytes(claim_value):
            raise DigestInputError(f"evidence value does not support {record_id}.{field}")
        if "quote" not in ref or _string(ref["quote"], "evidence quote") != _claim_text(
            claim_value
        ):
            raise DigestInputError(f"evidence quote does not support {record_id}.{field}")
        item = {
            "source_id": ref_source,
            "record_id": ref_record,
            "field": ref_field,
            "locator": locator,
        }
        item["quote"] = _string(ref["quote"], "evidence quote")
        normalized.append(item)
    return sorted(normalized, key=lambda item: _canonical_bytes(item))


def _validate_facts(
    value: Any,
    *,
    source_id: str,
    record_id: str,
    raw_payload: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    facts = _object(value, f"facts for {record_id}")
    _check_keys(facts, set(_FACT_FIELDS), f"facts for {record_id}")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for field, raw_claims in facts.items():
        claims = _list(raw_claims, f"claims for {record_id}.{field}")
        normalized_claims: list[dict[str, Any]] = []
        for index, raw_claim in enumerate(claims):
            claim = _object(raw_claim, f"claim {record_id}.{field}[{index}]")
            _check_keys(claim, _CLAIM_KEYS, f"claim {record_id}.{field}[{index}]")
            claim_value = _claim_value(
                claim.get("value"), field, f"claim value {record_id}.{field}[{index}]"
            )
            evidence = _validate_evidence(
                claim.get("evidence"),
                source_id=source_id,
                record_id=record_id,
                field=field,
                claim_value=claim_value,
                raw_payload=raw_payload,
            )
            normalized_claims.append({"value": claim_value, "evidence": evidence})
        normalized[field] = sorted(normalized_claims, key=lambda item: _canonical_bytes(item))
    return normalized


def _validate_source(source: Any, expected_source_ids: set[str]) -> dict[str, Any]:
    item = _object(source, "source")
    _check_keys(item, _SOURCE_KEYS, "source")
    source_id = _string(item.get("source_id"), "source_id")
    if source_id not in expected_source_ids:
        raise DigestInputError(f"source {source_id} is not listed in expected_sources")
    provider = _string(item.get("provider"), f"provider for {source_id}")
    board_id = _string(item.get("board_id"), f"board_id for {source_id}")
    source_url = _canonical_url(item.get("source_url"), f"source_url for {source_id}")
    observed_at = _timestamp(item.get("observed_at_utc"), f"observed_at_utc for {source_id}")
    capture_status = _string(item.get("capture_status"), f"capture_status for {source_id}")
    if capture_status not in _SOURCE_STATUSES:
        raise DigestInputError(f"unsupported capture_status for {source_id}: {capture_status}")
    records = _list(item.get("records"), f"records for {source_id}")
    error = _optional_string(item.get("error"), f"error for {source_id}")
    if capture_status == "complete" and error is not None:
        raise DigestInputError(f"complete source {source_id} cannot contain an error")
    if capture_status != "complete" and error is None:
        raise DigestInputError(f"incomplete source {source_id} requires an error")
    normalized_records: list[dict[str, Any]] = []
    record_ids: set[str] = set()
    for raw_record in records:
        record = _object(raw_record, f"record in {source_id}")
        _check_keys(record, _RECORD_KEYS, f"record in {source_id}")
        record_id = _string(record.get("record_id"), f"record_id in {source_id}")
        if record_id in record_ids:
            raise DigestInputError(f"duplicate record_id {record_id} in source {source_id}")
        record_ids.add(record_id)
        record_status = _string(record.get("record_status"), f"record_status {record_id}")
        if record_status not in _RECORD_STATUSES:
            raise DigestInputError(f"unsupported record_status for {record_id}: {record_status}")
        normalized_record: dict[str, Any] = {
            "record_id": record_id,
            "record_status": record_status,
        }
        external_id = _optional_string(record.get("external_id"), f"external_id for {record_id}")
        if external_id is not None:
            normalized_record["external_id"] = external_id
        if record_status in {"irrelevant", "unsupported", "malformed"}:
            normalized_record["exclusion_reason"] = _string(
                record.get("exclusion_reason"), f"exclusion_reason for {record_id}"
            )
            normalized_record["facts"] = {}
            normalized_record["raw_payload_sha256"] = _sha256(record.get("raw_payload", record))
            normalized_record["normalized_sha256"] = _sha256(normalized_record)
        else:
            if "raw_payload" not in record:
                raise DigestInputError(f"included record {record_id} requires raw_payload")
            raw_payload = _object(record["raw_payload"], f"raw_payload for {record_id}")
            normalized_record["raw_payload_sha256"] = _sha256(raw_payload)
            try:
                normalized_record["facts"] = _validate_facts(
                    record.get("facts"),
                    source_id=source_id,
                    record_id=record_id,
                    raw_payload=raw_payload,
                )
            except _MalformedFact as exc:
                normalized_record["record_status"] = "malformed"
                normalized_record["exclusion_reason"] = str(exc)
                normalized_record["facts"] = {}
            normalized_record["normalized_sha256"] = _sha256(
                {
                    "external_id": external_id,
                    "facts": normalized_record["facts"],
                }
            )
        normalized_records.append(normalized_record)
    return {
        "source_id": source_id,
        "provider": provider,
        "board_id": board_id,
        "source_url": source_url,
        "observed_at_utc": observed_at,
        "capture_status": capture_status,
        "error": error,
        "records": normalized_records,
    }


def validate_capture_manifest(manifest: Any) -> dict[str, Any]:
    """Validate and normalize an inline capture manifest without side effects."""

    item = _object(manifest, "capture manifest")
    allowed = {"schema_version", "parser_version", "policy_id", "expected_sources", "sources"}
    _check_keys(item, allowed, "capture manifest")
    if _string(item.get("schema_version"), "schema_version") != SCHEMA_VERSION:
        raise DigestInputError("unsupported capture schema_version")
    parser_version = _string(item.get("parser_version"), "parser_version")
    policy_id = _string(item.get("policy_id"), "policy_id")
    expected = _list(item.get("expected_sources"), "expected_sources")
    expected_ids = [_string(value, "expected source_id") for value in expected]
    if not expected_ids:
        raise DigestInputError("expected_sources must not be empty")
    if len(set(expected_ids)) != len(expected_ids):
        raise DigestInputError("expected_sources must contain unique source IDs")
    sources = _list(item.get("sources"), "sources")
    if len(sources) > len(expected_ids):
        raise DigestInputError("sources cannot exceed expected_sources")
    normalized_sources = [_validate_source(source, set(expected_ids)) for source in sources]
    actual_ids = [source["source_id"] for source in normalized_sources]
    if len(set(actual_ids)) != len(actual_ids) or not set(actual_ids).issubset(set(expected_ids)):
        raise DigestInputError("sources contain duplicate or unexpected source IDs")
    normalized_sources.sort(key=lambda source: source["source_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "parser_version": parser_version,
        "policy_id": policy_id,
        "expected_sources": sorted(expected_ids),
        "sources": normalized_sources,
    }


def _evidence_key(value: dict[str, Any]) -> bytes:
    return _canonical_bytes(value)


def _unique_evidence(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {_evidence_key(value): value for value in values}
    return [unique[key] for key in sorted(unique)]


def _source_reference(source: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source["source_id"],
        "record_id": record["record_id"],
        "provider": source["provider"],
        "board_id": source["board_id"],
        "source_url": source["source_url"],
        "observed_at_utc": source["observed_at_utc"],
        "raw_payload_sha256": record["raw_payload_sha256"],
        "normalized_facts_sha256": record["normalized_sha256"],
    }


def _identity(
    provider: str, board_id: str, external_id: str | None, job_url: str | None
) -> tuple[str, ...]:
    if external_id is not None:
        return (provider, board_id, "external", external_id)
    if job_url is not None:
        return (provider, board_id, "url", job_url)
    raise DigestInputError("included record has no external_id or job_url identity")


def _identity_text(identity: tuple[str, ...]) -> str:
    return json.dumps(list(identity), ensure_ascii=False, separators=(",", ":"))


def _merged_facts(records: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for field in _FACT_FIELDS:
        values: dict[bytes, dict[str, Any]] = {}
        for _source, record in records:
            for claim in record["facts"].get(field, []):
                key = _canonical_bytes(claim["value"])
                if key not in values:
                    values[key] = {"value": claim["value"], "evidence": []}
                values[key]["evidence"].extend(claim["evidence"])
        if not values:
            facts[field] = {
                "status": "unknown",
                "value": None,
                "reason": "not_reported",
                "evidence": [],
            }
        elif len(values) == 1:
            item = next(iter(values.values()))
            facts[field] = {
                "status": "known",
                "value": item["value"],
                "evidence": _unique_evidence(item["evidence"]),
            }
        else:
            claims = [
                {
                    "value": values[key]["value"],
                    "evidence": _unique_evidence(values[key]["evidence"]),
                }
                for key in sorted(values)
            ]
            facts[field] = {
                "status": "conflict",
                "value": None,
                "claims": claims,
            }
    return facts


def _advisory(opportunity: dict[str, Any]) -> dict[str, Any]:
    score = 0
    reasons: list[str] = []
    for field in ("firm", "role", "location", "deadline", "application_url"):
        status = opportunity["facts"][field]["status"]
        if status == "known":
            score += 1
            reasons.append(f"{field}:known")
        elif status == "conflict":
            reasons.append(f"{field}:conflict")
        else:
            reasons.append(f"{field}:unknown")
    return {"identity": opportunity["identity"], "score": score, "reasons": reasons}


def build_opportunity_digest(manifest: Any) -> dict[str, Any]:
    """Build a deterministic, evidence-linked digest from a local manifest."""

    normalized = validate_capture_manifest(manifest)
    source_errors: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    groups: dict[tuple[str, ...], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    complete_sources = 0
    for source in normalized["sources"]:
        if source["capture_status"] == "complete":
            complete_sources += 1
        else:
            source_errors.append(
                {
                    "source_id": source["source_id"],
                    "code": f"capture_{source['capture_status']}",
                    "message": source["error"],
                }
            )
        for record in source["records"]:
            status = record["record_status"]
            if status != "included":
                exclusions.append(
                    {
                        "source_id": source["source_id"],
                        "record_id": record["record_id"],
                        "reason": record["exclusion_reason"],
                        "raw_payload_sha256": record["raw_payload_sha256"],
                    }
                )
                if status == "malformed":
                    source_errors.append(
                        {
                            "source_id": source["source_id"],
                            "record_id": record["record_id"],
                            "code": "malformed_record",
                            "message": record["exclusion_reason"],
                        }
                    )
                continue
            if source["capture_status"] != "complete":
                exclusions.append(
                    {
                        "source_id": source["source_id"],
                        "record_id": record["record_id"],
                        "reason": "incomplete_source_record",
                        "raw_payload_sha256": record["raw_payload_sha256"],
                    }
                )
                continue
            facts = record["facts"]
            if not facts.get("firm") or not facts.get("role"):
                exclusions.append(
                    {
                        "source_id": source["source_id"],
                        "record_id": record["record_id"],
                        "reason": "missing_core_fact",
                        "raw_payload_sha256": record["raw_payload_sha256"],
                    }
                )
                continue
            job_url_claims = facts.get("job_url", [])
            job_urls = {claim["value"] for claim in job_url_claims}
            if len(job_urls) > 1:
                exclusions.append(
                    {
                        "source_id": source["source_id"],
                        "record_id": record["record_id"],
                        "reason": "conflicting_identity_url",
                    }
                )
                continue
            job_url = next(iter(job_urls), None)
            try:
                identity = _identity(
                    source["provider"],
                    source["board_id"],
                    record.get("external_id"),
                    job_url,
                )
            except DigestInputError:
                exclusions.append(
                    {
                        "source_id": source["source_id"],
                        "record_id": record["record_id"],
                        "reason": "missing_identity",
                    }
                )
                continue
            groups.setdefault(identity, []).append((source, record))

    for expected_source in normalized["expected_sources"]:
        if expected_source not in {source["source_id"] for source in normalized["sources"]}:
            source_errors.append(
                {
                    "source_id": expected_source,
                    "code": "missing_expected_source",
                    "message": "expected source was not supplied",
                }
            )

    opportunities: list[dict[str, Any]] = []
    for identity in sorted(groups):
        records = groups[identity]
        _, first_record = records[0]
        merged = {
            "identity": _identity_text(identity),
            "provider": identity[0],
            "board_id": identity[1],
            "external_id": first_record.get("external_id"),
            "facts": _merged_facts(records),
            "source_references": sorted(
                [_source_reference(source, record) for source, record in records],
                key=lambda value: _canonical_bytes(value),
            ),
        }
        merged["content_sha256"] = _sha256(
            {
                "identity": merged["identity"],
                "facts": merged["facts"],
                "source_references": merged["source_references"],
            }
        )
        opportunities.append(merged)

    source_errors.sort(key=lambda value: _canonical_bytes(value))
    exclusions.sort(key=lambda value: _canonical_bytes(value))
    coverage = {
        "expected_source_count": len(normalized["expected_sources"]),
        "supplied_source_count": len(normalized["sources"]),
        "complete_source_count": complete_sources,
        "included_record_count": sum(len(records) for records in groups.values()),
        "excluded_record_count": len(exclusions),
        "source_ids": normalized["expected_sources"],
    }
    result: dict[str, Any] = {
        "schema_version": DIGEST_SCHEMA_VERSION,
        "parser_version": normalized["parser_version"],
        "policy_id": normalized["policy_id"],
        "status": "complete" if not source_errors else "incomplete",
        "review_status": "pending",
        "coverage": coverage,
        "opportunities": opportunities,
        "exclusions": exclusions,
        "source_errors": source_errors,
        "advisory_ranking": {
            "rubric_id": ADVISORY_RUBRIC_ID,
            "candidate_specific_fit_assessed": False,
            "items": [],
        },
    }
    result["advisory_ranking"]["items"] = sorted(
        [_advisory(opportunity) for opportunity in opportunities],
        key=lambda value: (-value["score"], value["identity"]),
    )
    digest_basis = dict(result)
    result["digest_id"] = _sha256(digest_basis)
    return result


def render_digest_json(result: dict[str, Any]) -> str:
    """Render the canonical machine-readable digest."""

    return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _markdown_value(fact: dict[str, Any]) -> str:
    if fact["status"] == "known":
        return str(fact["value"])
    if fact["status"] == "unknown":
        return f"unknown ({fact['reason']})"
    claims = "; ".join(str(claim["value"]) for claim in fact["claims"])
    return f"conflict ({claims})"


def render_digest_markdown(result: dict[str, Any]) -> str:
    """Render the same canonical result as a human-reviewable Markdown digest."""

    lines = [
        "# EFDS opportunity digest",
        "",
        f"- Digest: `{result['digest_id']}`",
        f"- Status: `{result['status']}`",
        f"- Review status: `{result['review_status']}`",
        "- Sources: "
        f"{result['coverage']['complete_source_count']}/"
        f"{result['coverage']['expected_source_count']} complete",
        "",
        "## Opportunities",
        "",
    ]
    if not result["opportunities"]:
        lines.append("No opportunities were admitted.")
        lines.append("")
    for opportunity in result["opportunities"]:
        lines.extend(
            [
                f"### `{opportunity['identity']}`",
                "",
                f"- Provider/board: `{opportunity['provider']}` / `{opportunity['board_id']}`",
                f"- External ID: `{opportunity.get('external_id') or 'unknown'}`",
            ]
        )
        for field in _FACT_FIELDS:
            fact = opportunity["facts"][field]
            lines.append(f"- {field}: {_markdown_value(fact)}")
            for evidence in fact.get("evidence", []):
                lines.append(
                    "  - evidence: "
                    f"`{evidence['source_id']}/{evidence['record_id']}#{evidence['locator']}`"
                )
            for claim in fact.get("claims", []):
                for evidence in claim["evidence"]:
                    lines.append(
                        "  - conflict evidence: "
                        f"`{evidence['source_id']}/{evidence['record_id']}#{evidence['locator']}`"
                    )
        lines.append("- Source references:")
        for reference in opportunity["source_references"]:
            lines.append(
                f"  - `{reference['source_id']}/{reference['record_id']}` "
                f"raw `{reference['raw_payload_sha256']}` "
                f"normalized `{reference['normalized_facts_sha256']}`"
            )
        lines.append("")

    lines.extend(["## Exclusions", ""])
    if result["exclusions"]:
        lines.extend(
            f"- `{item['source_id']}/{item['record_id']}`: `{item['reason']}`"
            for item in result["exclusions"]
        )
    else:
        lines.append("None.")
    lines.extend(["", "## Source errors", ""])
    if result["source_errors"]:
        lines.extend(
            f"- `{item['source_id']}` `{item['code']}`: {item['message']}"
            for item in result["source_errors"]
        )
    else:
        lines.append("None.")
    lines.extend(
        [
            "",
            "## Advisory ranking",
            "",
            "Facts and evidence above are source-derived; this section is advisory only.",
            "",
        ]
    )
    for item in result["advisory_ranking"]["items"]:
        lines.append(f"- `{item['identity']}` score {item['score']}: {', '.join(item['reasons'])}")
    lines.append("")
    return "\n".join(lines)


def write_digest_outputs(
    result: dict[str, Any], output_dir: str | Path, *, overwrite: bool = False
) -> tuple[Path, Path]:
    """Write both deterministic outputs, refusing collisions by default."""

    directory = Path(output_dir)
    if directory.exists() and not directory.is_dir():
        raise DigestInputError(f"output path is not a directory: {directory}")
    json_path = directory / "opportunity-digest.json"
    markdown_path = directory / "opportunity-digest.md"
    if not overwrite and (json_path.exists() or markdown_path.exists()):
        raise DigestInputError("output files already exist; pass --overwrite to replace them")
    directory.mkdir(parents=True, exist_ok=True)
    json_text = render_digest_json(result)
    markdown_text = render_digest_markdown(result)
    temporary_paths: list[Path] = []
    backups: dict[Path, Path] = {}
    installed: list[Path] = []
    try:
        for name, text in (
            ("opportunity-digest.json", json_text),
            ("opportunity-digest.md", markdown_text),
        ):
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=directory,
                prefix=f".{name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_paths.append(Path(handle.name))
        if overwrite:
            for target in (json_path, markdown_path):
                if target.exists():
                    backup_fd, backup_name = tempfile.mkstemp(
                        dir=directory, prefix=f".{target.name}."
                    )
                    os.close(backup_fd)
                    backup = Path(backup_name)
                    temporary_paths.append(backup)
                    backup.unlink()
                    os.replace(target, backup)
                    backups[target] = backup
            for temporary, target in zip(temporary_paths, (json_path, markdown_path), strict=True):
                os.replace(temporary, target)
                installed.append(target)
        else:
            for temporary, target in zip(temporary_paths, (json_path, markdown_path), strict=True):
                os.link(temporary, target)
                installed.append(target)
                os.unlink(temporary)
    except (OSError, ValueError) as exc:
        for target in installed:
            try:
                target.unlink()
            except OSError:
                pass
        for target, backup in backups.items():
            try:
                if backup.exists():
                    os.replace(backup, target)
            except OSError:
                pass
        raise DigestInputError(f"could not publish digest outputs: {exc}") from exc
    finally:
        for temporary in temporary_paths:
            try:
                temporary.unlink()
            except OSError:
                pass
        for backup in backups.values():
            try:
                backup.unlink()
            except OSError:
                pass
    return json_path, markdown_path


def run_fixture_digest(
    input_path: str | Path, output_dir: str | Path, *, overwrite: bool = False
) -> tuple[Path, Path, dict[str, Any]]:
    """Load one local JSON manifest and write its deterministic digest outputs."""

    path = Path(input_path)
    if path.suffix.lower() != ".json":
        raise DigestInputError("fixture input must be a local JSON file")
    try:
        manifest = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except OSError as exc:
        raise DigestInputError(f"cannot read fixture input: {exc}") from exc
    except DigestInputError:
        raise
    except json.JSONDecodeError as exc:
        raise DigestInputError(f"fixture input is not valid JSON: {exc.msg}") from exc
    result = build_opportunity_digest(manifest)
    json_path, markdown_path = write_digest_outputs(result, output_dir, overwrite=overwrite)
    return json_path, markdown_path, result
