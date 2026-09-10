"""Offline, provenance-bound annotations for consolidated EFDS opportunities.

The module intentionally uses only the standard library.  It reads a frozen
review pack, validates a complete annotation document, and publishes a new
revision without changing the pack or an earlier review revision.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "efds-opportunity-review-v1"
ANNOTATION_SCHEMA_VERSION = "efds-opportunity-annotation-v1"
REVIEWER_NOTICE = (
    "Reviewer identity is an operator-supplied attribution claim; this offline "
    "workflow does not authenticate it."
)
PACK_FILES = (
    "START-HERE.md",
    "opportunities.csv",
    "coverage-and-gaps.json",
    "provenance.json",
    "HUMAN_REVIEW.md",
)
AVAILABILITY = {"unreviewed", "unknown", "open", "closed"}
RELEVANCE = {"unreviewed", "relevant", "not_relevant", "uncertain"}
DEADLINE = {"unreviewed", "unknown", "confirmed"}
ELIGIBILITY = {
    "unreviewed",
    "unknown",
    "confirmed_eligible",
    "confirmed_ineligible",
    "conditional",
}
DECISION_KEYS = {
    "availability": {"status", "checked_at", "references", "note"},
    "relevance": {"status", "checked_at", "references", "note"},
    "deadline": {"status", "value", "precision", "timezone", "checked_at", "references", "note"},
    "eligibility": {"status", "subject", "checked_at", "references", "note"},
}
ANNOTATION_KEYS = {
    "review_id",
    "opportunity_snapshot",
    "source_identity",
    "availability",
    "relevance",
    "deadline",
    "eligibility",
    "unresolved_questions",
    "review_notes",
    "reviewer",
    "reviewed_at",
}
TOP_LEVEL_KEYS = {
    "schema_version",
    "pack_id",
    "pack_identity",
    "pack_file_hashes",
    "input_file_hashes",
    "parent_revision",
    "reviewer_notice",
    "annotations",
    "revision_id",
}
REVISION_RE = re.compile(r"[0-9a-f]{64}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
LEGACY_PROVENANCE_SCHEMA = "efds-consolidated-opportunity-provenance-v1"
REPRODUCIBLE_PROVENANCE_SCHEMA = "efds-reproducible-opportunity-provenance-v1"
SOURCE_IDENTITY_FIELDS = (
    "review_id",
    "source_id",
    "provider",
    "board_id",
    "record_id",
    "external_id",
)


class OpportunityReviewError(ValueError):
    """Raised for an invalid pack, annotation document, or output path."""


def _strict_json(path: Path) -> Any:
    def pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OpportunityReviewError(f"duplicate JSON key {key!r}: {path}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, json.JSONDecodeError) as exc:
        raise OpportunityReviewError(f"invalid JSON {path}: {exc}") from exc


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise OpportunityReviewError(f"value is not canonical JSON: {exc}") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise OpportunityReviewError(f"cannot hash {path}: {exc}") from exc


def _object(value: Any, context: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise OpportunityReviewError(f"{context} must be an object")
    return value


def _string(value: Any, context: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise OpportunityReviewError(f"{context} must be a non-empty string")
    return value


def _nullable_string(value: Any, context: str) -> str | None:
    if value is None:
        return None
    return _string(value, context)


def _exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        detail = []
        if missing:
            detail.append(f"missing {', '.join(missing)}")
        if unknown:
            detail.append(f"unknown {', '.join(unknown)}")
        raise OpportunityReviewError(f"{context}: {'; '.join(detail)}")


def _required_keys(value: dict[str, Any], required: set[str], context: str) -> None:
    missing = sorted(required - set(value))
    if missing:
        raise OpportunityReviewError(f"{context}: missing {', '.join(missing)}")


def _list_of_strings(value: Any, context: str) -> list[str]:
    if type(value) is not list or any(type(item) is not str or not item.strip() for item in value):
        raise OpportunityReviewError(f"{context} must be an array of non-empty strings")
    return sorted(value)


def _hash(value: Any, context: str) -> str:
    text = _string(value, context)
    if HASH_RE.fullmatch(text) is None:
        raise OpportunityReviewError(f"{context} must be a lowercase SHA-256")
    return text


def _hash_map(value: Any, context: str) -> dict[str, str]:
    mapping = _object(value, context)
    result: dict[str, str] = {}
    for key, digest in mapping.items():
        name = _string(key, f"{context} key")
        result[name] = _hash(digest, f"{context}.{name}")
    if not result:
        raise OpportunityReviewError(f"{context} must not be empty")
    return result


def _hash_tree(
    value: Any, context: str, *, allow_empty: bool = False
) -> dict[str, dict[str, str]]:
    tree = _object(value, context)
    result: dict[str, dict[str, str]] = {}
    for group, mapping in tree.items():
        name = _string(group, f"{context} group")
        result[name] = _hash_map(mapping, f"{context}.{name}")
    if not result and not allow_empty:
        raise OpportunityReviewError(f"{context} must not be empty")
    return result


def _validate_identity_projection(
    source: dict[str, Any],
    row: dict[str, str],
    context: str,
    *,
    require_hashes: bool = True,
) -> None:
    for field in SOURCE_IDENTITY_FIELDS:
        if source.get(field) != row[field]:
            raise OpportunityReviewError(f"{context} identity mismatch: {field}")
    if require_hashes:
        for field in ("raw_payload_sha256", "normalized_facts_sha256"):
            _hash(source.get(field), f"{context}.{field}")


def _validate_evidence_references(value: Any, context: str) -> None:
    references = value
    if type(references) is not list:
        raise OpportunityReviewError(f"{context} must be an array")
    for index, reference in enumerate(references):
        item = _object(reference, f"{context}[{index}]")
        if "file" in item:
            for field in ("file", "locator", "sha256"):
                _string(item.get(field), f"{context}[{index}].{field}")
            _hash(item["sha256"], f"{context}[{index}].sha256")
            if "input" in item:
                _string(item["input"], f"{context}[{index}].input")
        else:
            _string(item.get("locator"), f"{context}[{index}].locator")
            for field in ("field", "record_id", "source_id", "reason"):
                if field in item and item[field] is not None:
                    _string(item[field], f"{context}[{index}].{field}")
        if "quote" in item and item["quote"] is not None:
            _string(item["quote"], f"{context}[{index}].quote", allow_empty=True)


def _validate_legacy_provenance(
    provenance: dict[str, Any], rows: list[dict[str, str]]
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    _required_keys(
        provenance,
        {"input_file_sha256", "pack_id", "rows", "schema_version"},
        "legacy provenance",
    )
    if "input_hashes" in provenance:
        raise OpportunityReviewError("mixed provenance schemas are not supported")
    input_hashes = _hash_tree(
        provenance["input_file_sha256"], "provenance.input_file_sha256", allow_empty=True
    )
    raw_rows = provenance["rows"]
    if type(raw_rows) is not list or not raw_rows:
        raise OpportunityReviewError("provenance.rows must be a non-empty array")
    provenance_rows: dict[str, Any] = {}
    for source in raw_rows:
        item = _object(source, "legacy provenance row")
        review_id = _string(item.get("review_id"), "legacy provenance row.review_id")
        if review_id in provenance_rows:
            raise OpportunityReviewError(f"duplicate provenance review ID: {review_id}")
        provenance_rows[review_id] = item
    if len(provenance_rows) != len(rows):
        raise OpportunityReviewError("pack opportunity/provenance row counts do not match")
    row_ids = {row["review_id"] for row in rows}
    if len(row_ids) != len(rows) or row_ids != set(provenance_rows):
        raise OpportunityReviewError("pack review IDs are not unique or not provenance-complete")
    for row in rows:
        source = provenance_rows[row["review_id"]]
        _validate_identity_projection(source, row, f"legacy provenance {row['review_id']}")
        if type(source.get("evidence_references")) is not list:
            raise OpportunityReviewError(
                f"legacy provenance {row['review_id']}.evidence_references must be an array"
            )
    return LEGACY_PROVENANCE_SCHEMA, input_hashes, provenance_rows


def _validate_reproducible_provenance(
    provenance: dict[str, Any], rows: list[dict[str, str]]
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    expected_keys = {
        "basis",
        "code_identity",
        "commands",
        "human_review_boundary",
        "input_hashes",
        "input_pack",
        "pack_id",
        "reconciliation",
        "review_revision",
        "rows",
        "schema_version",
        "verification_run",
    }
    _exact_keys(provenance, expected_keys, "reproducible provenance")
    if "input_file_sha256" in provenance:
        raise OpportunityReviewError("mixed provenance schemas are not supported")
    input_hashes = _hash_tree(provenance["input_hashes"], "provenance.input_hashes")
    code_identity = _object(provenance["code_identity"], "provenance.code_identity")
    _exact_keys(code_identity, {"module", "module_sha256", "schema_version"}, "code identity")
    _string(code_identity["module"], "code_identity.module")
    _hash(code_identity["module_sha256"], "code_identity.module_sha256")
    _string(code_identity["schema_version"], "code_identity.schema_version")
    _string(provenance["basis"], "provenance.basis")
    _string(provenance["human_review_boundary"], "provenance.human_review_boundary")
    commands = _object(provenance["commands"], "provenance.commands")
    _exact_keys(commands, {"database_calls", "network_requests", "offline"}, "commands")
    if type(commands["database_calls"]) is not int or type(commands["network_requests"]) is not int:
        raise OpportunityReviewError("commands call counts must be integers")
    _string(commands["offline"], "commands.offline")
    for name in ("input_pack", "reconciliation"):
        item = _object(provenance[name], f"provenance.{name}")
        expected = (
            {"directory_name", "file_sha256", "pack_id"}
            if name == "input_pack"
            else {"directory_name", "file_sha256"}
        )
        _exact_keys(item, expected, f"{name} binding")
        _string(item["directory_name"], f"{name}.directory_name")
        _hash_map(item["file_sha256"], f"{name}.file_sha256")
        if name == "input_pack":
            _string(item["pack_id"], "input_pack.pack_id")
    verification = _object(provenance["verification_run"], "provenance.verification_run")
    _exact_keys(verification, {"directory_name", "file_sha256", "run_id"}, "verification binding")
    _string(verification["directory_name"], "verification_run.directory_name")
    _hash_map(verification["file_sha256"], "verification_run.file_sha256")
    _string(verification["run_id"], "verification_run.run_id")
    revision = _object(provenance["review_revision"], "provenance.review_revision")
    _exact_keys(revision, {"revision_id", "status"}, "review revision binding")
    if revision["revision_id"] is not None:
        _revision_reference(revision["revision_id"], "review_revision.revision_id")
    _string(revision["status"], "review_revision.status")

    raw_rows = provenance["rows"]
    if type(raw_rows) is not list or not raw_rows:
        raise OpportunityReviewError("provenance.rows must be a non-empty array")
    row_map: dict[str, Any] = {}
    expected_row_keys = {
        "corrected_observation",
        "correction",
        "evidence_references",
        "historical_pack_row",
        "historical_source_identity",
        "human_annotation",
        "human_decision",
        "review_id",
        "verification_observation",
    }
    for raw in raw_rows:
        item = _object(raw, "reproducible provenance row")
        _exact_keys(item, expected_row_keys, "reproducible provenance row")
        review_id = _string(item["review_id"], "reproducible provenance row.review_id")
        if review_id in row_map:
            raise OpportunityReviewError(f"duplicate provenance review ID: {review_id}")
        row_map[review_id] = item
    if len(row_map) != len(rows):
        raise OpportunityReviewError("pack opportunity/provenance row counts do not match")
    row_ids = {row["review_id"] for row in rows}
    if len(row_ids) != len(rows) or row_ids != set(row_map):
        raise OpportunityReviewError("pack review IDs are not unique or not provenance-complete")
    for row in rows:
        review_id = row["review_id"]
        item = row_map[review_id]
        historical = _object(item["historical_pack_row"], f"historical pack row {review_id}")
        historical_source = _object(
            item["historical_source_identity"], f"historical source identity {review_id}"
        )
        _validate_identity_projection(
            historical, row, f"historical pack row {review_id}", require_hashes=False
        )
        _validate_identity_projection(
            historical_source, row, f"historical source identity {review_id}"
        )
        _hash(
            historical_source.get("digest_id"),
            f"historical source identity {review_id}.digest_id",
        )
        _string(
            historical_source.get("original_batch"),
            f"historical source identity {review_id}.original_batch",
        )
        _validate_evidence_references(
            historical_source.get("evidence_references"),
            f"historical source identity {review_id}.evidence_references",
        )
        _validate_evidence_references(
            item["evidence_references"],
            f"provenance row {review_id}.evidence_references",
        )
        corrected = _object(item["corrected_observation"], f"corrected observation {review_id}")
        if corrected.get("review_id") != review_id:
            raise OpportunityReviewError(f"corrected observation identity mismatch: {review_id}")
        observation = _object(
            item["verification_observation"], f"verification observation {review_id}"
        )
        if observation.get("review_id") != review_id:
            raise OpportunityReviewError(f"verification observation identity mismatch: {review_id}")
        if item["correction"] is not None:
            correction = _object(item["correction"], f"correction {review_id}")
            if correction.get("review_id") != review_id:
                raise OpportunityReviewError(f"correction identity mismatch: {review_id}")
        if item["human_annotation"] is not None:
            _object(item["human_annotation"], f"human annotation {review_id}")
        if _string(item["human_decision"], f"human decision {review_id}") != row.get(
            "human_decision"
        ):
            raise OpportunityReviewError(f"human decision identity mismatch: {review_id}")
    return REPRODUCIBLE_PROVENANCE_SCHEMA, input_hashes, row_map


def _iso_timestamp(value: Any, context: str, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    text = _string(value, context)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OpportunityReviewError(f"{context} must be ISO-8601: {exc}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OpportunityReviewError(f"{context} must include a timezone")
    return text


def _revision_reference(value: Any, context: str) -> str:
    text = _string(value, context)
    if REVISION_RE.fullmatch(text) is None:
        raise OpportunityReviewError(f"{context} must be a lowercase SHA-256 revision ID")
    return text


def _path_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _assert_output_safe(pack_dir: Path, source_file: Path | None, output_dir: Path) -> None:
    pack = pack_dir.resolve()
    output = output_dir.resolve()
    if output == pack or _path_inside(output, pack) or _path_inside(pack, output):
        raise OpportunityReviewError("output directory must be separate from the input pack")
    if source_file is not None and source_file.resolve() == output:
        raise OpportunityReviewError("annotation file cannot be the output directory")
    if output.exists():
        raise OpportunityReviewError(f"output directory already exists: {output}")


def _pack_file_hashes(pack_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in PACK_FILES:
        path = pack_dir / name
        if not path.is_file():
            raise OpportunityReviewError(f"pack is missing required file: {name}")
        hashes[name] = _sha256(path)
    return hashes


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if not header or len(header) != len(set(header)):
                raise OpportunityReviewError("opportunities.csv has a missing or duplicate header")
            required = {
                "review_id",
                "firm",
                "title",
                "location",
                "programme_type",
                "programme_year",
                "deadline",
                "application_url",
                "source_id",
                "provider",
                "board_id",
                "record_id",
                "external_id",
            }
            if not required <= set(header):
                raise OpportunityReviewError("opportunities.csv is missing required columns")
            rows = []
            for values in reader:
                if len(values) != len(header):
                    raise OpportunityReviewError("opportunities.csv has a malformed row")
                rows.append(dict(zip(header, values, strict=True)))
            return rows
    except OSError as exc:
        raise OpportunityReviewError(f"cannot read {path}: {exc}") from exc


def _pack(pack_dir: str | Path) -> dict[str, Any]:
    directory = Path(pack_dir).resolve()
    if not directory.is_dir():
        raise OpportunityReviewError(f"pack directory does not exist: {directory}")
    file_hashes = _pack_file_hashes(directory)
    provenance = _object(_strict_json(directory / "provenance.json"), "provenance")
    pack_id = _string(provenance.get("pack_id"), "provenance.pack_id")
    rows = _read_csv(directory / "opportunities.csv")
    schema = provenance.get("schema_version")
    if schema == LEGACY_PROVENANCE_SCHEMA:
        provenance_schema, input_hashes, provenance_rows = _validate_legacy_provenance(
            provenance, rows
        )
    elif schema == REPRODUCIBLE_PROVENANCE_SCHEMA:
        provenance_schema, input_hashes, provenance_rows = _validate_reproducible_provenance(
            provenance, rows
        )
    else:
        raise OpportunityReviewError("unsupported opportunity pack provenance schema")
    identity_basis = {
        "pack_id": pack_id,
        "pack_file_hashes": file_hashes,
        "input_file_hashes": input_hashes,
    }
    pack_identity = _sha256_bytes(_canonical(identity_basis))
    for row in rows:
        source = provenance_rows[row["review_id"]]
        if provenance_schema == LEGACY_PROVENANCE_SCHEMA:
            source_record_id = source.get("record_id")
            source_id = source.get("source_id")
        else:
            historical_source = source["historical_source_identity"]
            source_record_id = historical_source.get("record_id")
            source_id = historical_source.get("source_id")
        if source_record_id != row["record_id"] or source_id != row["source_id"]:
            raise OpportunityReviewError(f"pack source identity mismatch: {row['review_id']}")
    return {
        "directory": directory,
        "pack_id": pack_id,
        "pack_identity": pack_identity,
        "pack_file_hashes": file_hashes,
        "input_file_hashes": input_hashes,
        "provenance_schema": provenance_schema,
        "rows": {row["review_id"]: row for row in rows},
        "provenance_rows": provenance_rows,
    }


def _snapshot(row: dict[str, str]) -> dict[str, str]:
    return {
        key: row[key]
        for key in (
            "review_id",
            "firm",
            "title",
            "location",
            "programme_type",
            "programme_year",
            "deadline",
            "application_url",
            "source_id",
            "provider",
            "board_id",
            "record_id",
            "external_id",
        )
    }


def _source_identity(pack: dict[str, Any], review_id: str) -> dict[str, Any]:
    source = pack["provenance_rows"][review_id]
    if pack["provenance_schema"] == REPRODUCIBLE_PROVENANCE_SCHEMA:
        return {
            "provenance_schema": REPRODUCIBLE_PROVENANCE_SCHEMA,
            "provenance_row": source,
        }
    return {
        key: source.get(key)
        for key in (
            "original_batch",
            "digest_id",
            "source_id",
            "provider",
            "board_id",
            "record_id",
            "external_id",
            "raw_payload_sha256",
            "normalized_facts_sha256",
            "evidence_references",
        )
    }


def _blank_dimension(status: str = "unreviewed") -> dict[str, Any]:
    return {"status": status, "checked_at": None, "references": [], "note": ""}


def _blank_deadline() -> dict[str, Any]:
    return {
        "status": "unreviewed",
        "value": None,
        "precision": None,
        "timezone": None,
        "checked_at": None,
        "references": [],
        "note": "",
    }


def _blank_eligibility() -> dict[str, Any]:
    return {
        "status": "unreviewed",
        "subject": None,
        "checked_at": None,
        "references": [],
        "note": "",
    }


def _template_annotation(pack: dict[str, Any], review_id: str) -> dict[str, Any]:
    return {
        "review_id": review_id,
        "opportunity_snapshot": _snapshot(pack["rows"][review_id]),
        "source_identity": _source_identity(pack, review_id),
        "availability": _blank_dimension(),
        "relevance": _blank_dimension(),
        "deadline": _blank_deadline(),
        "eligibility": _blank_eligibility(),
        "unresolved_questions": [],
        "review_notes": "",
        "reviewer": None,
        "reviewed_at": None,
    }


def _revision_basis(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "revision_id"}


def _revision_id(document: dict[str, Any]) -> str:
    return _sha256_bytes(_canonical(_revision_basis(document)))


def _validate_references(value: Any, context: str) -> list[str]:
    return _list_of_strings(value, context)


def _validate_dimension(value: Any, name: str, allowed: set[str]) -> dict[str, Any]:
    item = _object(value, name)
    _exact_keys(item, DECISION_KEYS[name], name)
    status = _string(item["status"], f"{name}.status")
    if status not in allowed:
        raise OpportunityReviewError(f"unsupported {name} status: {status}")
    checked_at = _iso_timestamp(item["checked_at"], f"{name}.checked_at", required=False)
    refs = _validate_references(item["references"], f"{name}.references")
    note = _string(item["note"], f"{name}.note", allow_empty=True)
    if status in {"open", "closed"} and (checked_at is None or not refs):
        raise OpportunityReviewError(f"{name}={status} requires checked_at and references")
    return {"status": status, "checked_at": checked_at, "references": refs, "note": note}


def _validate_deadline(value: Any) -> dict[str, Any]:
    item = _object(value, "deadline")
    _exact_keys(item, DECISION_KEYS["deadline"], "deadline")
    status = _string(item["status"], "deadline.status")
    if status not in DEADLINE:
        raise OpportunityReviewError(f"unsupported deadline status: {status}")
    checked_at = _iso_timestamp(item["checked_at"], "deadline.checked_at", required=False)
    refs = _validate_references(item["references"], "deadline.references")
    note = _string(item["note"], "deadline.note", allow_empty=True)
    value_text = _nullable_string(item["value"], "deadline.value")
    precision = item["precision"]
    timezone = item["timezone"]
    if precision is not None:
        precision = _string(precision, "deadline.precision")
    if timezone is not None:
        timezone = _string(timezone, "deadline.timezone")
    if status == "confirmed":
        if (
            value_text is None
            or precision not in {"date", "datetime"}
            or not refs
            or checked_at is None
        ):
            raise OpportunityReviewError(
                "confirmed deadline requires value, precision, checked_at, and references"
            )
        if precision == "date":
            if timezone is not None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value_text):
                raise OpportunityReviewError("date deadline requires YYYY-MM-DD and no timezone")
        elif timezone is None or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})", value_text
        ):
            raise OpportunityReviewError("datetime deadline requires an explicit timezone")
    elif any(item_value is not None for item_value in (value_text, precision, timezone)):
        raise OpportunityReviewError(
            "unconfirmed deadline cannot contain a value, precision, or timezone"
        )
    return {
        "status": status,
        "value": value_text,
        "precision": precision,
        "timezone": timezone,
        "checked_at": checked_at,
        "references": refs,
        "note": note,
    }


def _validate_eligibility(value: Any) -> dict[str, Any]:
    item = _object(value, "eligibility")
    _exact_keys(item, DECISION_KEYS["eligibility"], "eligibility")
    status = _string(item["status"], "eligibility.status")
    if status not in ELIGIBILITY:
        raise OpportunityReviewError(f"unsupported eligibility status: {status}")
    subject = _nullable_string(item["subject"], "eligibility.subject")
    checked_at = _iso_timestamp(item["checked_at"], "eligibility.checked_at", required=False)
    refs = _validate_references(item["references"], "eligibility.references")
    note = _string(item["note"], "eligibility.note", allow_empty=True)
    if status != "unreviewed" and (subject is None or not subject.strip()):
        raise OpportunityReviewError(
            "eligibility decisions require an explicit subject or audience"
        )
    if status in {"confirmed_eligible", "confirmed_ineligible", "conditional"} and (
        checked_at is None or not refs
    ):
        raise OpportunityReviewError(f"eligibility={status} requires checked_at and references")
    return {
        "status": status,
        "subject": subject,
        "checked_at": checked_at,
        "references": refs,
        "note": note,
    }


def _validate_annotation(pack: dict[str, Any], value: Any) -> dict[str, Any]:
    item = _object(value, "annotation")
    _exact_keys(item, ANNOTATION_KEYS, "annotation")
    review_id = _string(item["review_id"], "annotation.review_id")
    if review_id not in pack["rows"]:
        raise OpportunityReviewError(f"unknown review ID: {review_id}")
    if item["opportunity_snapshot"] != _snapshot(pack["rows"][review_id]):
        raise OpportunityReviewError(f"opportunity facts changed: {review_id}")
    if item["source_identity"] != _source_identity(pack, review_id):
        raise OpportunityReviewError(f"source evidence identity changed: {review_id}")
    availability = _validate_dimension(item["availability"], "availability", AVAILABILITY)
    relevance = _validate_dimension(item["relevance"], "relevance", RELEVANCE)
    deadline = _validate_deadline(item["deadline"])
    eligibility = _validate_eligibility(item["eligibility"])
    questions = _list_of_strings(item["unresolved_questions"], "unresolved_questions")
    notes = _string(item["review_notes"], "review_notes", allow_empty=True)
    reviewer = _nullable_string(item["reviewer"], "reviewer")
    reviewed_at = _iso_timestamp(item["reviewed_at"], "reviewed_at", required=False)
    recorded = any(
        decision["status"] != "unreviewed"
        for decision in (availability, relevance, deadline, eligibility)
    )
    if recorded and (reviewer is None or reviewed_at is None):
        raise OpportunityReviewError("recorded decisions require reviewer and reviewed_at")
    if not recorded and (reviewer is not None or reviewed_at is not None):
        raise OpportunityReviewError("unreviewed annotation cannot claim reviewer metadata")
    return {
        "review_id": review_id,
        "opportunity_snapshot": _snapshot(pack["rows"][review_id]),
        "source_identity": _source_identity(pack, review_id),
        "availability": availability,
        "relevance": relevance,
        "deadline": deadline,
        "eligibility": eligibility,
        "unresolved_questions": questions,
        "review_notes": notes,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
    }


def _validate_document(pack: dict[str, Any], value: Any) -> dict[str, Any]:
    document = _object(value, "annotation document")
    _exact_keys(document, TOP_LEVEL_KEYS, "annotation document")
    if document["schema_version"] != ANNOTATION_SCHEMA_VERSION:
        raise OpportunityReviewError("unsupported annotation schema version")
    if document["pack_id"] != pack["pack_id"]:
        raise OpportunityReviewError("annotation is bound to a different pack")
    if document["pack_file_hashes"] != pack["pack_file_hashes"]:
        raise OpportunityReviewError("pack file hashes changed")
    if document["input_file_hashes"] != pack["input_file_hashes"]:
        raise OpportunityReviewError("relevant input file hashes changed")
    if document["pack_identity"] != pack["pack_identity"]:
        raise OpportunityReviewError("annotation is bound to a different pack")
    if document["reviewer_notice"] != REVIEWER_NOTICE:
        raise OpportunityReviewError("reviewer attribution notice changed")
    parent = document["parent_revision"]
    if parent is not None:
        _revision_reference(parent, "parent_revision")
    annotations = document["annotations"]
    if type(annotations) is not list or not annotations:
        raise OpportunityReviewError("annotations must be a non-empty array")
    raw_ids = [item.get("review_id") if type(item) is dict else None for item in annotations]
    if any(type(review_id) is not str or not review_id.strip() for review_id in raw_ids):
        raise OpportunityReviewError("annotation.review_id must be a non-empty string")
    if len(raw_ids) != len(set(raw_ids)):
        raise OpportunityReviewError("duplicate annotation review ID")
    normalized = [_validate_annotation(pack, item) for item in annotations]
    ids = [item["review_id"] for item in normalized]
    if len(ids) != len(set(ids)):
        raise OpportunityReviewError("duplicate annotation review ID")
    if set(ids) != set(pack["rows"]):
        raise OpportunityReviewError(
            "annotation document must contain every pack opportunity exactly once"
        )
    normalized.sort(key=lambda item: item["review_id"])
    result = {
        "schema_version": ANNOTATION_SCHEMA_VERSION,
        "pack_id": pack["pack_id"],
        "pack_identity": pack["pack_identity"],
        "pack_file_hashes": pack["pack_file_hashes"],
        "input_file_hashes": pack["input_file_hashes"],
        "parent_revision": parent,
        "reviewer_notice": REVIEWER_NOTICE,
        "annotations": normalized,
        "revision_id": document.get("revision_id"),
    }
    supplied = result["revision_id"]
    if supplied is not None:
        _revision_reference(supplied, "revision_id")
    return result


def _new_document(pack: dict[str, Any], *, parent_revision: str | None = None) -> dict[str, Any]:
    document = {
        "schema_version": ANNOTATION_SCHEMA_VERSION,
        "pack_id": pack["pack_id"],
        "pack_identity": pack["pack_identity"],
        "pack_file_hashes": pack["pack_file_hashes"],
        "input_file_hashes": pack["input_file_hashes"],
        "parent_revision": parent_revision,
        "reviewer_notice": REVIEWER_NOTICE,
        "annotations": [
            _template_annotation(pack, review_id) for review_id in sorted(pack["rows"])
        ],
        "revision_id": None,
    }
    document["revision_id"] = _revision_id(document)
    return document


def _summary(document: dict[str, Any]) -> str:
    annotations = document["annotations"]
    by_status = {
        field: Counter(annotation[field]["status"] for annotation in annotations)
        for field in ("availability", "relevance", "deadline", "eligibility")
    }
    lines = [
        "# EFDS opportunity review revision",
        "",
        "This file-based review is bound to the immutable consolidated pack. It records "
        "operator-supplied human assertions only; it does not authenticate the reviewer "
        "or independently verify current web facts.",
        "",
        f"- Pack: `{document['pack_id']}`",
        f"- Pack identity: `{document['pack_identity']}`",
        f"- Revision: `{document['revision_id']}`",
        f"- Parent revision: `{document['parent_revision'] or 'none'}`",
        f"- Reviewer attribution: {document['reviewer_notice']}",
        "",
        "## Decision counts",
        "",
        "| Dimension | Counts |",
        "|---|---|",
    ]
    for field in ("availability", "relevance", "deadline", "eligibility"):
        counts = ", ".join(f"{key}={value}" for key, value in sorted(by_status[field].items()))
        lines.append(f"| {field} | {counts} |")
    lines.extend(["", "## Opportunities", ""])
    for annotation in annotations:
        snapshot = annotation["opportunity_snapshot"]
        lines.extend(
            [
                f"### {snapshot['firm']} — {snapshot['title']}",
                "",
                f"- Review ID: `{annotation['review_id']}`",
                f"- Location/programme: {snapshot['location']} / "
                f"{snapshot['programme_type']} / {snapshot['programme_year']}",
                f"- Availability: `{annotation['availability']['status']}`",
                f"- Relevance: `{annotation['relevance']['status']}`",
                f"- Deadline confirmation: `{annotation['deadline']['status']}`",
                f"- Eligibility confirmation: `{annotation['eligibility']['status']}`",
                f"- Eligibility subject: {annotation['eligibility']['subject'] or 'not supplied'}",
                f"- Application URL (source fact): {snapshot['application_url']}",
                f"- Human decision: `{'recorded' if annotation['reviewer'] else 'unreviewed'}`",
                f"- Unresolved questions: "
                f"{'; '.join(annotation['unresolved_questions']) or 'none recorded'}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def _manifest(document: dict[str, Any]) -> dict[str, Any]:
    annotations = document["annotations"]
    recorded = [item for item in annotations if item["reviewer"] is not None]
    return {
        "schema_version": SCHEMA_VERSION,
        "pack_id": document["pack_id"],
        "pack_identity": document["pack_identity"],
        "parent_revision": document["parent_revision"],
        "revision_id": document["revision_id"],
        "annotation_schema_version": document["schema_version"],
        "annotation_sha256": _sha256_bytes(_canonical(document)),
        "opportunity_count": len(annotations),
        "recorded_decision_count": len(recorded),
        "unreviewed_count": len(annotations) - len(recorded),
        "reviewer_attribution_notice": REVIEWER_NOTICE,
        "input_file_hashes": document["input_file_hashes"],
    }


def _publish(directory: Path, document: dict[str, Any]) -> Path:
    if directory.exists():
        raise OpportunityReviewError(f"output directory already exists: {directory}")
    parent = directory.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{directory.name}.", dir=parent))
    try:
        (temporary / "annotations.json").write_bytes(_canonical(document) + b"\n")
        (temporary / "review-summary.md").write_text(_summary(document), encoding="utf-8")
        (temporary / "review-manifest.json").write_bytes(_canonical(_manifest(document)) + b"\n")
        os.replace(temporary, directory)
    except (OSError, ValueError) as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        raise OpportunityReviewError(f"could not publish review revision: {exc}") from exc
    return directory


def create_review_template(pack_dir: str | Path, output_dir: str | Path) -> Path:
    """Create a new all-unreviewed annotation revision for a verified pack."""

    pack = _pack(pack_dir)
    output = Path(output_dir).resolve()
    _assert_output_safe(pack["directory"], None, output)
    return _publish(output, _new_document(pack))


def apply_review_annotations(
    pack_dir: str | Path,
    annotations_path: str | Path,
    output_dir: str | Path,
) -> Path:
    """Validate and publish a complete human-edited annotation revision."""

    pack = _pack(pack_dir)
    source = Path(annotations_path).resolve()
    output = Path(output_dir).resolve()
    _assert_output_safe(pack["directory"], source, output)
    source_document = _strict_json(source)
    document = _validate_document(pack, source_document)
    parent_revision = source_document.get("revision_id")
    if parent_revision is None:
        raise OpportunityReviewError("applied annotations must link to a parent revision")
    _revision_reference(parent_revision, "revision_id")
    document["parent_revision"] = parent_revision
    document["revision_id"] = None
    document["revision_id"] = _revision_id(document)
    return _publish(output, document)
