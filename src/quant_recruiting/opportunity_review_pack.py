"""Build a deterministic, provenance-bound EFDS review pack from saved evidence."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import shutil
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from quant_recruiting.opportunity_review import (
    _pack as _annotation_pack,
)
from quant_recruiting.opportunity_review import (
    _revision_id as _annotation_revision_id,
)
from quant_recruiting.opportunity_review import (
    _strict_json as _annotation_json,
)
from quant_recruiting.opportunity_review import (
    _validate_document as _validate_annotation_document,
)

SCHEMA_VERSION = "efds-opportunity-review-pack-v1"
PROVENANCE_SCHEMA_VERSION = "efds-reproducible-opportunity-provenance-v1"
COVERAGE_SCHEMA_VERSION = "efds-reproducible-opportunity-coverage-v1"
PACK_FILES = (
    "START-HERE.md",
    "opportunities.csv",
    "coverage-and-gaps.json",
    "provenance.json",
    "HUMAN_REVIEW.md",
)
VERIFICATION_FILES = (
    "capture-manifest.json",
    "request-ledger.json",
    "verification-observations.json",
)
RECONCILIATION_FILES = (
    "corrections.json",
    "corrected-review.json",
    "reconciliation-manifest.json",
)
CSV_FIELDS = (
    "review_id",
    "firm",
    "title",
    "location",
    "programme_type",
    "programme_year",
    "programme_year_basis",
    "application_url",
    "observed_listing_status",
    "apply_link_or_form_observed",
    "explicit_availability_statement",
    "deadline",
    "eligibility_evidence_summary",
    "original_batch",
    "digest_id",
    "source_id",
    "provider",
    "board_id",
    "record_id",
    "external_id",
    "historical_application_url",
    "capture_timestamp",
    "observation_timestamp",
    "evidence_references",
    "advisory_priority",
    "advisory_basis",
    "human_decision",
)


class OpportunityReviewPackError(ValueError):
    """Raised when saved evidence cannot be safely consolidated."""


def _strict_json(path: Path) -> Any:
    def pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OpportunityReviewPackError(f"duplicate JSON key {key!r}: {path}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, json.JSONDecodeError) as exc:
        raise OpportunityReviewPackError(f"invalid JSON {path}: {exc}") from exc


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
        raise OpportunityReviewPackError(f"value is not canonical JSON: {exc}") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise OpportunityReviewPackError(f"cannot hash {path}: {exc}") from exc


def _object(value: Any, context: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise OpportunityReviewPackError(f"{context} must be an object")
    return value


def _list(value: Any, context: str) -> list[Any]:
    if type(value) is not list:
        raise OpportunityReviewPackError(f"{context} must be an array")
    return value


def _string(value: Any, context: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise OpportunityReviewPackError(f"{context} must be a non-empty string")
    return value


def _under(root: Path, relative: str, context: str) -> Path:
    if type(relative) is not str or not relative or Path(relative).is_absolute():
        raise OpportunityReviewPackError(f"{context} must be a relative path")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise OpportunityReviewPackError(f"{context} escapes its input root") from exc
    if not candidate.is_file():
        raise OpportunityReviewPackError(f"{context} does not resolve to a file: {relative}")
    return candidate


def _validate_evidence_bytes(
    root: Path,
    file_name: str,
    evidence: dict[str, Any],
    declared_hashes: dict[str, str],
    context: str,
) -> Path:
    path = _under(root, file_name, context)
    expected = declared_hashes.get(file_name)
    if expected is None:
        raise OpportunityReviewPackError(f"{context} lacks a declared hash: {file_name}")
    if _sha256(path) != expected:
        raise OpportunityReviewPackError(f"{context} hash mismatch: {file_name}")
    quote = evidence.get("quote")
    content = path.read_bytes()
    normalized_content = html.unescape(content.decode("utf-8", errors="replace")).encode()
    if (
        isinstance(quote, str)
        and quote
        and quote.encode() not in content
        and quote.encode() not in normalized_content
    ):
        raise OpportunityReviewPackError(
            f"{context} quote is absent from saved bytes: {file_name}"
        )
    return path


def _hash_manifest(root: Path, relative_paths: list[str], context: str) -> dict[str, str]:
    return {
        relative: _sha256(_under(root, relative, context))
        for relative in sorted(relative_paths)
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise OpportunityReviewPackError(
                    "opportunities.csv has a missing or duplicate header"
                )
            required = {
                "review_id",
                "firm",
                "title",
                "location",
                "programme_type",
                "programme_year",
                "application_url",
                "source_id",
                "provider",
                "board_id",
                "record_id",
                "external_id",
            }
            if not required <= set(reader.fieldnames):
                raise OpportunityReviewPackError("opportunities.csv is missing required columns")
            rows: list[dict[str, str]] = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise OpportunityReviewPackError("opportunities.csv has a malformed row")
                rows.append({key: value for key, value in row.items() if key is not None})
            return rows
    except OSError as exc:
        raise OpportunityReviewPackError(f"cannot read {path}: {exc}") from exc


def _embedded_json(value: str, context: str) -> Any:
    try:
        return json.loads(
            value,
            object_pairs_hook=lambda pairs: _strict_pairs(pairs, context),
        )
    except (TypeError, json.JSONDecodeError) as exc:
        raise OpportunityReviewPackError(f"{context} is not valid JSON: {exc}") from exc


def _strict_pairs(pairs: list[tuple[str, Any]], context: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OpportunityReviewPackError(f"duplicate JSON key {key!r}: {context}")
        result[key] = value
    return result


def _load_pack(directory: str | Path) -> dict[str, Any]:
    root = Path(directory).resolve()
    if not root.is_dir():
        raise OpportunityReviewPackError(f"consolidated pack does not exist: {root}")
    file_hashes = {name: _sha256(_under(root, name, "pack file")) for name in PACK_FILES}
    provenance = _object(_strict_json(root / "provenance.json"), "pack provenance")
    coverage = _object(_strict_json(root / "coverage-and-gaps.json"), "pack coverage")
    if provenance.get("schema_version") != "efds-consolidated-opportunity-provenance-v1":
        raise OpportunityReviewPackError("unsupported consolidated provenance schema")
    if coverage.get("schema_version") != "efds-consolidated-opportunity-coverage-v1":
        raise OpportunityReviewPackError("unsupported consolidated coverage schema")
    pack_id = _string(provenance.get("pack_id"), "provenance.pack_id")
    if coverage.get("pack_id") != pack_id:
        raise OpportunityReviewPackError("pack provenance and coverage IDs differ")
    rows = _read_csv(root / "opportunities.csv")
    provenance_rows = {
        item.get("review_id"): item
        for item in _list(provenance.get("rows"), "provenance.rows")
        if type(item) is dict
    }
    if len(provenance_rows) != len(rows) or any(not key for key in provenance_rows):
        raise OpportunityReviewPackError("pack rows and provenance rows do not reconcile")
    row_map: dict[str, dict[str, str]] = {}
    for row in rows:
        review_id = _string(row.get("review_id"), "opportunities.review_id")
        if review_id in row_map or review_id not in provenance_rows:
            raise OpportunityReviewPackError(f"duplicate or missing provenance for {review_id}")
        source = provenance_rows[review_id]
        for field in ("source_id", "provider", "board_id", "record_id", "external_id"):
            if source.get(field) != row.get(field):
                raise OpportunityReviewPackError(f"pack identity mismatch for {review_id}: {field}")
        _embedded_json(row.get("evidence_references", "[]"), f"evidence_references[{review_id}]")
        row_map[review_id] = row
    if set(row_map) != set(provenance_rows):
        raise OpportunityReviewPackError("pack review IDs are not identical to provenance IDs")
    return {
        "root": root,
        "pack_id": pack_id,
        "file_hashes": file_hashes,
        "provenance": provenance,
        "coverage": coverage,
        "rows": row_map,
        "provenance_rows": provenance_rows,
    }


def _load_verification(directory: str | Path, pack: dict[str, Any]) -> dict[str, Any]:
    root = Path(directory).resolve()
    if not root.is_dir():
        raise OpportunityReviewPackError(f"verification run does not exist: {root}")
    files = {name: _sha256(_under(root, name, "verification file")) for name in VERIFICATION_FILES}
    observations_doc = _object(
        _strict_json(root / "verification-observations.json"),
        "verification observations",
    )
    capture_manifest = _object(_strict_json(root / "capture-manifest.json"), "capture manifest")
    ledger = _object(_strict_json(root / "request-ledger.json"), "verification request ledger")
    run_id = _string(observations_doc.get("run_id"), "verification.run_id")
    if observations_doc.get("schema_version") != "efds-opportunity-verification-observations-v2":
        raise OpportunityReviewPackError("unsupported verification observation schema")
    if observations_doc.get("source_pack_id") != pack["pack_id"]:
        raise OpportunityReviewPackError("verification run is bound to another pack")
    if (
        capture_manifest.get("source_pack_id") != pack["pack_id"]
        or capture_manifest.get("run_id") != run_id
    ):
        raise OpportunityReviewPackError("verification capture manifest identity mismatch")
    if ledger.get("source_pack_id") != pack["pack_id"] or ledger.get("run_id") != run_id:
        raise OpportunityReviewPackError("verification ledger identity mismatch")
    evidence_hashes: dict[str, str] = {}
    for entry in _list(capture_manifest.get("response_entries"), "capture response entries"):
        response_entry = _object(entry, "capture response entry")
        for field in ("raw_file", "decoded_file"):
            file_name = _string(response_entry.get(field), f"capture {field}")
            hash_field = "raw_sha256" if field == "raw_file" else "decoded_sha256"
            expected = _string(response_entry.get(hash_field), f"capture {hash_field}")
            previous = evidence_hashes.get(file_name)
            if previous is not None and previous != expected:
                raise OpportunityReviewPackError(
                    f"verification evidence hash declarations conflict: {file_name}"
                )
            evidence_hashes[file_name] = expected
            if _sha256(_under(root, file_name, "verification evidence")) != expected:
                raise OpportunityReviewPackError(
                    f"verification evidence hash mismatch: {file_name}"
                )
    observations = _list(observations_doc.get("observations"), "verification.observations")
    if len(observations) != observations_doc.get("count"):
        raise OpportunityReviewPackError("verification observation count mismatch")
    by_id: dict[str, dict[str, Any]] = {}
    for item in observations:
        observation = _object(item, "verification observation")
        review_id = _string(observation.get("review_id"), "verification.review_id")
        if review_id in by_id or review_id not in pack["rows"]:
            raise OpportunityReviewPackError(f"verification ID does not reconcile: {review_id}")
        raw_file_name = _string(
            observation.get("response_body_file"), "response_body_file"
        )
        raw_file = _under(
            root,
            raw_file_name,
            "response body",
        )
        if evidence_hashes.get(raw_file_name) != observation.get("response_sha256"):
            raise OpportunityReviewPackError(
                f"verification raw response is not capture-manifest bound: {review_id}"
            )
        if _sha256(raw_file) != observation.get("response_sha256"):
            raise OpportunityReviewPackError(f"verification response hash mismatch: {review_id}")
        for evidence in _list(
            observation.get("evidence", []), f"verification evidence {review_id}"
        ):
            item_evidence = _object(evidence, "verification evidence")
            evidence_file = _string(
                item_evidence.get("file"), f"verification evidence file {review_id}"
            )
            _validate_evidence_bytes(
                root,
                evidence_file,
                item_evidence,
                evidence_hashes,
                f"verification evidence {review_id}",
            )
        by_id[review_id] = observation
    if set(by_id) != set(pack["rows"]):
        raise OpportunityReviewPackError("verification observations do not cover every pack row")
    return {
        "root": root,
        "file_hashes": files,
        "evidence_hashes": evidence_hashes,
        "run_id": run_id,
        "observations": by_id,
        "manifest": capture_manifest,
        "ledger": ledger,
    }


def _evidence_root(
    file_name: str, verification: dict[str, Any], reconciliation: Path
) -> tuple[Path, str]:
    if file_name.startswith("gsa-discovery/"):
        return reconciliation, "reconciliation"
    if file_name.startswith("responses/"):
        return verification["root"], "verification"
    raise OpportunityReviewPackError(f"unsupported evidence root: {file_name}")


def _load_reconciliation(
    directory: str | Path, pack: dict[str, Any], verification: dict[str, Any]
) -> dict[str, Any]:
    root = Path(directory).resolve()
    if not root.is_dir():
        raise OpportunityReviewPackError(f"reconciliation directory does not exist: {root}")
    files = {
        name: _sha256(_under(root, name, "reconciliation file"))
        for name in RECONCILIATION_FILES
    }
    manifest = _object(
        _strict_json(root / "reconciliation-manifest.json"),
        "reconciliation manifest",
    )
    corrections_doc = _object(_strict_json(root / "corrections.json"), "corrections")
    corrected_doc = _object(_strict_json(root / "corrected-review.json"), "corrected review")
    if manifest.get("source_pack_id") != pack["pack_id"]:
        raise OpportunityReviewPackError("reconciliation manifest is bound to another pack")
    if (
        corrections_doc.get("source_pack_id") != pack["pack_id"]
        or corrections_doc.get("verification_run_id") != verification["run_id"]
    ):
        raise OpportunityReviewPackError("corrections identity mismatch")
    if corrections_doc.get("all_human_decisions") != "unreviewed":
        raise OpportunityReviewPackError("reconciliation corrections contain human decisions")
    if (
        corrected_doc.get("source_pack_id") != pack["pack_id"]
        or corrected_doc.get("verification_run_id") != verification["run_id"]
    ):
        raise OpportunityReviewPackError("corrected review identity mismatch")
    _verify_declared_hashes(
        manifest, "original_consolidated_pack", pack["root"], "reconciliation input"
    )
    _verify_declared_hashes(
        manifest,
        "verification_run_selected_files",
        verification["root"],
        "reconciliation input",
    )
    _verify_declared_hashes(manifest, "output_files", root, "reconciliation output")
    evidence_hashes = _object(
        manifest.get("evidence_file_sha256"), "reconciliation evidence hashes"
    )
    for file_name, expected in evidence_hashes.items():
        relative = _string(file_name, "reconciliation evidence file")
        declared = _string(expected, f"reconciliation evidence hash {relative}")
        if _sha256(_under(root, relative, "reconciliation evidence")) != declared:
            raise OpportunityReviewPackError(
                f"reconciliation evidence hash mismatch: {relative}"
            )
    gsa_ledger = _object(
        _strict_json(root / "gsa-discovery" / "request-ledger.json"),
        "GSA discovery ledger",
    )
    gsa_metadata: dict[str, dict[str, Any]] = {}
    for attempt in _list(gsa_ledger.get("attempts"), "GSA discovery attempts"):
        attempt_object = _object(attempt, "GSA discovery attempt")
        file_name = _string(attempt_object.get("response_body_file"), "GSA response file")
        gsa_metadata[f"gsa-discovery/{file_name}"] = _object(
            attempt_object.get("response_headers", {}), "GSA response headers"
        )
    corrections = _list(corrections_doc.get("corrections"), "corrections.corrections")
    correction_map: dict[str, dict[str, Any]] = {}
    for item in corrections:
        correction = _object(item, "correction")
        review_id = _string(correction.get("review_id"), "correction.review_id")
        if review_id in correction_map or review_id not in pack["rows"]:
            raise OpportunityReviewPackError(f"correction ID does not reconcile: {review_id}")
        correction_map[review_id] = correction
    corrected = _list(corrected_doc.get("opportunities"), "corrected-review.opportunities")
    if len(corrected) != corrected_doc.get("count") or len(corrected) != len(pack["rows"]):
        raise OpportunityReviewPackError("corrected review count mismatch")
    corrected_map: dict[str, dict[str, Any]] = {}
    for item in corrected:
        row = _object(item, "corrected opportunity")
        review_id = _string(row.get("review_id"), "corrected.review_id")
        if review_id in corrected_map or review_id not in pack["rows"]:
            raise OpportunityReviewPackError(f"corrected review ID does not reconcile: {review_id}")
        historical = _object(
            row.get("historical_source_identity"),
            f"historical source identity {review_id}",
        )
        source = pack["provenance_rows"][review_id]
        for field in ("source_id", "record_id", "external_id", "digest_id", "original_batch"):
            if historical.get(field) != source.get(field):
                raise OpportunityReviewPackError(
                    f"historical identity mismatch for {review_id}: {field}"
                )
        evidence_list = _list(row.get("evidence"), f"corrected evidence {review_id}")
        nested_evidence: list[Any] = []
        for claim in _list(
            row.get("graduation_or_education_evidence", []),
            f"graduation evidence {review_id}",
        ):
            claim_object = _object(claim, "graduation evidence claim")
            if "evidence" in claim_object:
                nested_evidence.append(claim_object["evidence"])
        for evidence in [*evidence_list, *nested_evidence]:
            item_evidence = _object(evidence, "corrected evidence")
            file_name = _string(item_evidence.get("file"), "corrected evidence.file")
            evidence_root, _kind = _evidence_root(file_name, verification, root)
            if evidence_root == verification["root"]:
                expected_hash = verification["evidence_hashes"].get(file_name)
            else:
                expected_hash = evidence_hashes.get(file_name)
            if item_evidence.get("locator") == "HTTP Location":
                _validate_evidence_bytes(
                    evidence_root,
                    file_name,
                    {"quote": None},
                    {file_name: expected_hash} if expected_hash is not None else {},
                    f"corrected evidence {review_id}",
                )
                if item_evidence.get("quote") != gsa_metadata.get(file_name, {}).get("location"):
                    raise OpportunityReviewPackError(
                        f"corrected evidence metadata does not match saved headers: {file_name}"
                    )
            else:
                _validate_evidence_bytes(
                    evidence_root,
                    file_name,
                    item_evidence,
                    {file_name: expected_hash} if expected_hash is not None else {},
                    f"corrected evidence {review_id}",
                )
            _string(item_evidence.get("locator"), "corrected evidence.locator")
        matched_correction: dict[str, Any] | None = None
        for candidate in corrections:
            if isinstance(candidate, dict) and candidate.get("review_id") == review_id:
                matched_correction = candidate
                break
        if (
            matched_correction is not None
            and matched_correction.get("kind") == "source_link_reconciliation"
        ):
            canonical_url = _string(
                matched_correction.get("canonical_url"), f"canonical URL {review_id}"
            )
            if row.get("observed_final_url") != canonical_url:
                raise OpportunityReviewPackError(
                    f"corrected URL does not match identity correction: {review_id}"
                )
            if not any(canonical_url in str(item.get("quote")) for item in evidence_list):
                raise OpportunityReviewPackError(
                    f"corrected URL lacks canonical identity evidence: {review_id}"
                )
            if not any(
                str(item.get("file", "")).startswith("gsa-discovery/")
                for item in evidence_list
            ):
                raise OpportunityReviewPackError(
                    f"corrected URL lacks official GSA evidence: {review_id}"
                )
            if not any(
                item.get("locator") in {"html.title", "html.h1"}
                and _string(item.get("quote"), "identity title evidence")
                and str(row.get("title")) in str(item.get("quote"))
                for item in evidence_list
            ):
                raise OpportunityReviewPackError(
                    f"corrected URL lacks title identity evidence: {review_id}"
                )
            if row.get("historical_application_url") != matched_correction.get("historical_url"):
                raise OpportunityReviewPackError(
                    f"corrected URL lacks historical URL linkage: {review_id}"
                )
        if (
            matched_correction is not None
            and matched_correction.get("kind") == "new_detail_evidence_not_historical_rewrite"
        ):
            if row.get("programme_year") != matched_correction.get("observed_programme_year"):
                raise OpportunityReviewPackError(
                    f"programme-year correction is not represented: {review_id}"
                )
            correction_evidence = _object(
                matched_correction.get("evidence"), "correction evidence"
            )
            if correction_evidence not in evidence_list:
                raise OpportunityReviewPackError(
                    f"programme-year correction lacks its evidence: {review_id}"
                )
        if (
            matched_correction is not None
            and matched_correction.get("kind") == "graduation_year_not_programme_year"
        ):
            if row.get("programme_year") != matched_correction.get("corrected_programme_year"):
                raise OpportunityReviewPackError(
                    f"graduation correction changed programme year: {review_id}"
                )
            graduation_evidence = _list(
                row.get("graduation_or_education_evidence", []),
                f"graduation evidence {review_id}",
            )
            for item in _list(
                matched_correction.get("graduation_evidence"), "graduation correction evidence"
            ):
                evidence = _object(item.get("evidence"), "graduation correction evidence")
                if not any(
                    isinstance(claim, dict) and claim.get("evidence") == evidence
                    for claim in graduation_evidence
                ):
                    raise OpportunityReviewPackError(
                        f"graduation correction lacks its evidence: {review_id}"
                    )
        if row.get("human_decision") != "unreviewed":
            raise OpportunityReviewPackError("reconciliation contains a human decision")
        corrected_map[review_id] = row
    if set(corrected_map) != set(pack["rows"]):
        raise OpportunityReviewPackError("corrected review does not cover every pack row")
    return {
        "root": root,
        "file_hashes": files,
        "manifest": manifest,
        "corrections": correction_map,
        "corrected": corrected_map,
        "gsa_ledger": gsa_ledger,
    }


def _verify_declared_hashes(manifest: dict[str, Any], key: str, root: Path, context: str) -> None:
    declared = manifest.get("input_hashes", {}).get(key)
    if key == "output_files":
        declared = manifest.get("output_files")
    if type(declared) is not dict:
        raise OpportunityReviewPackError(f"{context} hash map missing: {key}")
    for relative, expected in declared.items():
        path = _under(root, relative, context)
        actual = _sha256(path)
        if actual != expected:
            raise OpportunityReviewPackError(f"{context} hash mismatch: {relative}")


def _review_annotations(
    pack: dict[str, Any], review_revision: str | Path | None
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if review_revision is None:
        return {"status": "not_supplied", "revision_id": None}, {}
    root = Path(review_revision).resolve()
    if not root.is_dir():
        raise OpportunityReviewPackError("review revision must be a directory")
    annotations_path = root / "annotations.json"
    document = _annotation_json(annotations_path)
    annotation_pack = _annotation_pack(pack["root"])
    normalized = _validate_annotation_document(annotation_pack, document)
    revision_id = normalized.get("revision_id")
    if type(revision_id) is not str or revision_id != _annotation_revision_id(normalized):
        raise OpportunityReviewPackError("review revision ID does not match its contents")
    manifest_path = root / "review-manifest.json"
    if manifest_path.is_file():
        review_manifest = _object(_annotation_json(manifest_path), "review manifest")
        if (
            review_manifest.get("revision_id") != revision_id
            or review_manifest.get("pack_identity") != annotation_pack["pack_identity"]
        ):
            raise OpportunityReviewPackError("review manifest identity mismatch")
    annotations = {item["review_id"]: item for item in normalized["annotations"]}
    return {"status": "supplied", "revision_id": revision_id}, annotations


def _observation_timestamp(
    review_id: str,
    corrected: dict[str, Any],
    verification: dict[str, Any],
    reconciliation: dict[str, Any],
) -> str | None:
    if any(
        str(item.get("file", "")).startswith("gsa-discovery/")
        for item in corrected.get("evidence", [])
    ):
        times: list[str] = []
        for attempt in _list(
            reconciliation["gsa_ledger"].get("attempts", []), "GSA ledger attempts"
        ):
            rel = f"gsa-discovery/{attempt.get('response_body_file', '')}"
            if any(item.get("file") == rel for item in corrected.get("evidence", [])):
                if isinstance(attempt.get("finished_at_utc"), str):
                    times.append(attempt["finished_at_utc"])
        if times:
            return max(times)
    value = verification["observations"][review_id].get("retrieval_timestamp_utc")
    return value if isinstance(value, str) else None


def _evidence_records(
    review_id: str,
    corrected: dict[str, Any],
    verification: dict[str, Any],
    reconciliation: dict[str, Any],
) -> list[dict[str, Any]]:
    refs = []
    items: list[Any] = list(corrected.get("evidence", []))
    for claim in corrected.get("graduation_or_education_evidence", []):
        if isinstance(claim, dict) and isinstance(claim.get("evidence"), dict):
            items.append(claim["evidence"])
    items.extend(verification["observations"][review_id].get("evidence", []))
    for item in items:
        evidence = deepcopy(_object(item, "evidence"))
        file_name = _string(evidence.get("file"), "evidence.file")
        root, kind = _evidence_root(file_name, verification, reconciliation["root"])
        path = _under(root, file_name, "evidence file")
        evidence["input"] = kind
        evidence["sha256"] = _sha256(path)
        refs.append(evidence)
    return sorted(
        refs,
        key=lambda item: (
            item["input"],
            item["file"],
            item["locator"],
            item.get("quote") or "",
        ),
    )


def _claims(corrected: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "graduation_or_education": deepcopy(corrected.get("graduation_or_education_evidence", [])),
        "sponsorship_work_authorization": deepcopy(
            observation.get("sponsorship_work_authorization_statements", [])
        ),
    }


def _csv_value(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "true" if value else "false"
    if not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _md(value: Any) -> str:
    text = "unknown" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _render_start(
    pack: dict[str, Any],
    verification: dict[str, Any],
    reconciliation: dict[str, Any],
    pack_id: str,
    count: int,
) -> str:
    return "\n".join(
        [
            "# START HERE — reproducible EFDS opportunity review pack",
            "",
            "This pack was produced from explicitly supplied saved evidence only. It is not "
            "a live availability check, a human eligibility decision, or a market-complete "
            "opportunity list.",
            "",
            f"- **Pack:** `{pack_id}`",
            f"- **Opportunities:** {count}",
            f"- **Input consolidated pack:** `{pack['pack_id']}`",
            f"- **Verification run:** `{verification['run_id']}`",
            f"- **Reconciliation:** `{reconciliation['manifest'].get('schema_version')}`",
            "- **Human decisions:** all rows remain `unreviewed` unless a separately supplied "
            "valid review revision is bound.",
            "",
            "## Read next",
            "",
            "1. `HUMAN_REVIEW.md` for the grouped shortlist and explicit unknowns.",
            "2. `opportunities.csv` for spreadsheet review; canonical values and full evidence "
            "remain in JSON provenance.",
            "3. `coverage-and-gaps.json` for observed source coverage, including Optiver's "
            "partial result.",
            "4. `provenance.json` for historical URLs, corrected observations, response hashes, "
            "and evidence paths.",
            "",
            "No network, database, credentials, models, Factory execution, scheduling, or "
            "external publication was used.",
            "",
        ]
    )


def _render_human(rows: list[dict[str, Any]], coverage: dict[str, Any], pack_id: str) -> str:
    lines = [
        "# EFDS opportunity review",
        "",
        "This is a deterministic offline review aid. `matching listing retrieved` and "
        "`Apply/form observed` are machine observations, not decisions that a role is open, "
        "suitable, or eligible for any individual.",
        "",
        f"- Pack: `{pack_id}`",
        f"- Opportunities: {len(rows)}",
        "- Human decision: all rows are `unreviewed` unless a valid review revision was "
        "explicitly supplied.",
        "",
        "## Coverage",
        "",
        "| Firm/source | Raw | Included | Excluded | Status | Gap |",
        "|---|---:|---:|---:|---|---|",
    ]
    for source in coverage["source_rows"]:
        gap = "; ".join(source.get("outstanding_gaps", [])) or "captured source only"
        lines.append(
            f"| {_md(source.get('firm'))} ({_md(source.get('source_id'))}) | "
            f"{source.get('raw_record_count', 'unknown')} | "
            f"{source.get('included_record_count', 'unknown')} | "
            f"{source.get('excluded_record_count', 'unknown')} | "
            f"{_md(source.get('reported_status'))} | {_md(gap)} |"
        )
    lines.extend(
        [
            "",
            "## Shortlist",
            "",
        "Review each row against the saved evidence named in `provenance.json`. Unknown "
        "deadlines and absent availability statements remain unknown.",
            "",
        ]
    )
    for firm in sorted({row["firm"] for row in rows}, key=str.casefold):
        lines.extend([f"## {_md(firm)}", ""])
        for row in sorted(
            (item for item in rows if item["firm"] == firm),
            key=lambda item: (item["title"].casefold(), item["review_id"]),
        ):
            eligibility = row["eligibility_evidence_summary"]
            grad = eligibility.get("graduation_or_education", [])
            sponsor = eligibility.get("sponsorship_work_authorization", [])
            requirements = []
            for claim in [*grad, *sponsor]:
                if isinstance(claim, dict):
                    requirements.append(str(claim.get("quote") or claim.get("detail") or claim))
            questions = _md(
                "; ".join(row["unresolved_questions"])
                if row["unresolved_questions"]
                else "none recorded"
            )
            lines.extend(
                [
                    f"### {_md(row['title'])}",
                    "",
                    f"- Review ID: `{row['review_id']}`",
                    f"- Location: {_md(row['location'])}",
                    f"- Programme: {_md(row['programme_type'])} / {_md(row['programme_year'])}",
                    f"- Programme evidence basis: {_md(row['programme_year_basis'])}",
                    f"- Application URL: {row['application_url']}",
                    f"- Observed listing state: {_md(row['observed_listing_status'])}",
                    f"- Apply/form surface observed: {_md(row['apply_link_or_form_observed'])}",
                    f"- Explicit availability: {_md(row['explicit_availability_statement'])}",
                    f"- Deadline: {_md(row['deadline'])}",
                    f"- Eligibility/education statements: "
                    f"{_md(' '.join(requirements) if requirements else 'unknown')}",
                    f"- Capture timestamp: `{row['capture_timestamp']}`; additional "
                    f"observation: `{row['observation_timestamp'] or 'unknown'}`",
                    f"- Advisory triage: **{row['advisory_priority']}** — "
                    f"{_md(row['advisory_basis'])}",
                    f"- Human decision: **{row['human_decision']}**",
                    f"- Outstanding questions: {questions}",
                    f"- Evidence: see `provenance.json` row `{row['review_id']}`.",
                    "",
                ]
            )
    lines.extend(
        [
            "## Boundaries",
            "",
            "GSA corrected application URLs are supported by official-page links, redirect "
            "records, and matching canonical ATS title/identity evidence; historical broken URLs "
            "remain in provenance. DRW detail-page programme years are later observations, not "
            "rewrites of the board capture. Jane Street graduation years remain eligibility "
            "evidence, not programme years. Optiver remains partial at 16/166 and contributes "
            "no included row.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_outputs(
    temporary: Path,
    pack: dict[str, Any],
    verification: dict[str, Any],
    reconciliation: dict[str, Any],
    pack_id: str,
    rows: list[dict[str, Any]],
    provenance: dict[str, Any],
    review_info: dict[str, Any],
) -> None:
    coverage = deepcopy(pack["coverage"])
    coverage["schema_version"] = COVERAGE_SCHEMA_VERSION
    coverage["pack_id"] = pack_id
    coverage["basis"] = (
        "explicit saved consolidated pack, verification run, and reconciliation evidence; "
        "offline only"
    )
    source_observations: dict[str, Counter[str]] = {}
    for observation in verification["observations"].values():
        source_id = pack["provenance_rows"][observation["review_id"]]["source_id"]
        source_observations.setdefault(source_id, Counter())[
            observation.get("listing_status", "unknown")
        ] += 1
    for source in coverage.get("source_rows", []):
        source_id = source.get("source_id")
        source["verification_observations"] = dict(
            sorted(source_observations.get(source_id, Counter()).items())
        )
    coverage["aggregate"] = {
        **coverage.get("aggregate", {}),
        "reviewed_row_count": len(rows),
        "human_decision_counts": dict(
            sorted(Counter(row["human_decision"] for row in rows).items())
        ),
        "optiver_partial_preserved": any(
            source.get("source_id") == "optiver-official"
            and source.get("capture_status") != "complete"
            for source in coverage.get("source_rows", [])
        ),
    }
    coverage["verification_run"] = {
        "run_id": verification["run_id"],
        "status": verification["manifest"].get("status"),
        "observation_count": len(verification["observations"]),
    }
    coverage["reconciliation"] = {
        "schema_version": reconciliation["manifest"].get("schema_version"),
        "correction_count": len(reconciliation["corrections"]),
        "human_decisions": "unreviewed in reconciliation input",
    }
    (temporary / "coverage-and-gaps.json").write_bytes(_canonical(coverage) + b"\n")

    with (temporary / "opportunities.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=CSV_FIELDS,
            lineterminator="\n",
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in CSV_FIELDS})

    (temporary / "HUMAN_REVIEW.md").write_text(
        _render_human(rows, coverage, pack_id), encoding="utf-8"
    )
    (temporary / "START-HERE.md").write_text(
        _render_start(pack, verification, reconciliation, pack_id, len(rows)), encoding="utf-8"
    )

    provenance["review_revision"] = review_info
    (temporary / "provenance.json").write_bytes(_canonical(provenance) + b"\n")
    output_hashes = {
        name: _sha256(temporary / name)
        for name in (
            "START-HERE.md",
            "opportunities.csv",
            "HUMAN_REVIEW.md",
            "coverage-and-gaps.json",
            "provenance.json",
        )
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "pack_id": pack_id,
        "input_pack_id": pack["pack_id"],
        "verification_run_id": verification["run_id"],
        "reconciliation_schema_version": reconciliation["manifest"].get("schema_version"),
        "input_hashes": provenance["input_hashes"],
        "code_identity": provenance["code_identity"],
        "opportunity_count": len(rows),
        "human_decision_counts": dict(
            sorted(Counter(row["human_decision"] for row in rows).items())
        ),
        "output_file_sha256": output_hashes,
    }
    (temporary / "review-pack-manifest.json").write_bytes(_canonical(manifest) + b"\n")


def build_review_pack(
    pack_dir: str | Path,
    verification_dir: str | Path,
    reconciliation_dir: str | Path,
    output_dir: str | Path,
    *,
    review_revision: str | Path | None = None,
) -> Path:
    """Build a new deterministic review pack from explicit saved inputs."""

    pack = _load_pack(pack_dir)
    verification = _load_verification(verification_dir, pack)
    reconciliation = _load_reconciliation(reconciliation_dir, pack, verification)
    review_info, annotations = _review_annotations(pack, review_revision)
    output = Path(output_dir).resolve()
    input_roots = (pack["root"], verification["root"], reconciliation["root"])
    if output.exists():
        raise OpportunityReviewPackError(f"output directory already exists: {output}")
    for root in input_roots:
        if output == root or output.is_relative_to(root) or root.is_relative_to(output):
            raise OpportunityReviewPackError(
                "output directory must be separate from all input directories"
            )
    if review_revision is not None:
        review_root = Path(review_revision).resolve()
        if (
            output == review_root
            or output.is_relative_to(review_root)
            or review_root.is_relative_to(output)
        ):
            raise OpportunityReviewPackError(
                "output directory must be separate from review revision"
            )

    source_rows = []
    provenance_rows = []
    for review_id in sorted(pack["rows"]):
        original = pack["rows"][review_id]
        corrected = reconciliation["corrected"][review_id]
        observation = verification["observations"][review_id]
        evidence = _evidence_records(review_id, corrected, verification, reconciliation)
        app_url = (
            corrected.get("observed_final_url")
            if corrected.get("matching_listing_observed")
            and corrected.get("apply_link_or_form_observed")
            else None
        )
        if not isinstance(app_url, str) or not app_url:
            app_url = original.get("application_url")
        annotation = annotations.get(review_id)
        human_decision = "unreviewed"
        if annotation is not None and any(
            annotation[field]["status"] != "unreviewed"
            for field in ("availability", "relevance", "deadline", "eligibility")
        ):
            human_decision = "recorded"
        claims = _claims(corrected, observation)
        row = {
            "review_id": review_id,
            "firm": corrected.get("firm"),
            "title": corrected.get("title"),
            "location": corrected.get("location"),
            "programme_type": corrected.get("programme_type"),
            "programme_year": corrected.get("programme_year") or "unknown",
            "programme_year_basis": corrected.get("programme_year_basis") or "unknown",
            "application_url": app_url,
            "observed_listing_status": corrected.get("observed_listing_status") or "unknown",
            "apply_link_or_form_observed": bool(corrected.get("apply_link_or_form_observed")),
            "explicit_availability_statement": corrected.get("explicit_availability_statement"),
            "deadline": corrected.get("deadline") or "unknown",
            "eligibility_evidence_summary": claims,
            "original_batch": original.get("original_batch"),
            "digest_id": original.get("digest_id"),
            "source_id": original.get("source_id"),
            "provider": original.get("provider"),
            "board_id": original.get("board_id"),
            "record_id": original.get("record_id"),
            "external_id": original.get("external_id"),
            "historical_application_url": corrected.get("historical_application_url")
            or original.get("application_url"),
            "capture_timestamp": original.get("capture_timestamp"),
            "observation_timestamp": _observation_timestamp(
                review_id, corrected, verification, reconciliation
            ),
            "evidence_references": evidence,
            "advisory_priority": original.get("advisory_priority", "standard-review"),
            "advisory_basis": original.get("advisory_basis", "advisory triage only"),
            "human_decision": human_decision,
            "unresolved_questions": sorted(set(corrected.get("unresolved_questions", []))),
        }
        source_rows.append(row)
        provenance_rows.append(
            {
                "review_id": review_id,
                "historical_pack_row": deepcopy(original),
                "historical_source_identity": deepcopy(pack["provenance_rows"][review_id]),
                "corrected_observation": deepcopy(corrected),
                "verification_observation": deepcopy(observation),
                "correction": deepcopy(reconciliation["corrections"].get(review_id)),
                "evidence_references": evidence,
                "human_annotation": deepcopy(annotation) if annotation is not None else None,
                "human_decision": human_decision,
            }
        )

    stable_pack_id = _sha256_bytes(
        _canonical(
            {
                "input_pack_id": pack["pack_id"],
                "verification_run_id": verification["run_id"],
                "reconciliation_manifest_sha256": reconciliation["file_hashes"][
                    "reconciliation-manifest.json"
                ],
                "review_revision_id": review_info.get("revision_id"),
            }
        )
    )
    provenance = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "pack_id": stable_pack_id,
        "basis": "explicit saved consolidated pack, verification run, and "
        "reconciliation evidence; no live collection",
        "input_pack": {
            "directory_name": pack["root"].name,
            "pack_id": pack["pack_id"],
            "file_sha256": pack["file_hashes"],
        },
        "verification_run": {
            "directory_name": verification["root"].name,
            "run_id": verification["run_id"],
            "file_sha256": verification["file_hashes"],
        },
        "reconciliation": {
            "directory_name": reconciliation["root"].name,
            "file_sha256": reconciliation["file_hashes"],
        },
        "input_hashes": {
            "pack": pack["file_hashes"],
            "verification": verification["file_hashes"],
            "reconciliation": reconciliation["file_hashes"],
        },
        "code_identity": {
            "module": "quant_recruiting.opportunity_review_pack",
            "module_sha256": _sha256(Path(__file__).resolve()),
            "schema_version": SCHEMA_VERSION,
        },
        "human_review_boundary": "Human decisions remain unreviewed unless a separately "
        "supplied, valid review revision is bound to the unchanged pack identity.",
        "rows": provenance_rows,
        "commands": {
            "offline": "quant-recruiting research opportunity-review-pack PACK_DIR "
            "VERIFICATION_DIR RECONCILIATION_DIR OUTPUT_DIR [--review-revision REVIEW_DIR]",
            "network_requests": 0,
            "database_calls": 0,
        },
    }

    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=parent))
    try:
        _write_outputs(
            temporary,
            pack,
            verification,
            reconciliation,
            stable_pack_id,
            source_rows,
            provenance,
            review_info,
        )
        os.replace(temporary, output)
    except (OSError, ValueError) as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        if isinstance(exc, OpportunityReviewPackError):
            raise
        raise OpportunityReviewPackError(f"could not publish review pack: {exc}") from exc
    return output
