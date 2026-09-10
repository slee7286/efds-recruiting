from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_recruiting.cli import app
from quant_recruiting.opportunity_review import create_review_template
from quant_recruiting.opportunity_review_pack import (
    OpportunityReviewPackError,
    build_review_pack,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _pack(tmp_path: Path) -> Path:
    root = tmp_path / "pack"
    root.mkdir()
    rows = [
        {
            "review_id": "review-a",
            "firm": "Example Quant",
            "title": "Quant Intern",
            "location": "London",
            "programme_type": "internship",
            "programme_year": "unknown",
            "eligibility_evidence_summary": "[]",
            "deadline": "unknown",
            "application_url": "https://example.invalid/old-a",
            "original_batch": "batch-a",
            "digest_id": "digest-a",
            "source_id": "source-a",
            "provider": "provider-a",
            "board_id": "board-a",
            "record_id": "record-a",
            "external_id": "external-a",
            "capture_timestamp": "2026-09-09T00:00:00Z",
            "evidence_references": "[]",
            "advisory_priority": "review-first",
            "advisory_basis": "synthetic",
            "human_decision": "unreviewed",
        },
        {
            "review_id": "review-b",
            "firm": "Example Tech",
            "title": "Software Intern",
            "location": "London",
            "programme_type": "internship",
            "programme_year": "2027",
            "eligibility_evidence_summary": "[]",
            "deadline": "unknown",
            "application_url": "https://example.invalid/old-b",
            "original_batch": "batch-b",
            "digest_id": "digest-b",
            "source_id": "source-b",
            "provider": "provider-b",
            "board_id": "board-b",
            "record_id": "record-b",
            "external_id": "external-b",
            "capture_timestamp": "2026-09-09T00:00:00Z",
            "evidence_references": "[]",
            "advisory_priority": "standard-review",
            "advisory_basis": "synthetic",
            "human_decision": "unreviewed",
        },
    ]
    with (root / "opportunities.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    provenance_rows = [
        {
            "review_id": row["review_id"],
            "original_batch": row["original_batch"],
            "digest_id": row["digest_id"],
            "source_id": row["source_id"],
            "provider": row["provider"],
            "board_id": row["board_id"],
            "record_id": row["record_id"],
            "external_id": row["external_id"],
            "raw_payload_sha256": "a" * 64,
            "normalized_facts_sha256": "b" * 64,
            "capture_timestamp": row["capture_timestamp"],
            "evidence_references": [],
            "provenance_aliases": [],
        }
        for row in rows
    ]
    _dump(
        root / "provenance.json",
        {
            "schema_version": "efds-consolidated-opportunity-provenance-v1",
            "pack_id": "synthetic-pack",
            "rows": provenance_rows,
            "input_file_sha256": {},
        },
    )
    _dump(
        root / "coverage-and-gaps.json",
        {
            "schema_version": "efds-consolidated-opportunity-coverage-v1",
            "pack_id": "synthetic-pack",
            "source_count": 2,
            "included_opportunity_count": 2,
            "source_rows": [
                {
                    "source_id": "source-a",
                    "firm": "Example Quant",
                    "raw_record_count": 1,
                    "included_record_count": 1,
                    "excluded_record_count": 0,
                    "reported_status": "complete",
                    "capture_status": "complete",
                    "outstanding_gaps": [],
                },
                {
                    "source_id": "optiver-official",
                    "firm": "Optiver",
                    "raw_record_count": 166,
                    "included_record_count": 0,
                    "excluded_record_count": 16,
                    "reported_status": "partial",
                    "capture_status": "partial",
                    "outstanding_gaps": ["16/166; pagination unresolved"],
                },
            ],
            "aggregate": {
                "raw_record_count": 167,
                "included_record_count": 2,
                "excluded_record_count": 16,
            },
        },
    )
    (root / "START-HERE.md").write_text("synthetic\n", encoding="utf-8")
    (root / "HUMAN_REVIEW.md").write_text("unreviewed\n", encoding="utf-8")
    return root


def _verification(tmp_path: Path, pack: Path) -> Path:
    root = tmp_path / "verification"
    root.mkdir()
    observations = []
    for review_id, source_id, record_id, title, url in (
        ("review-a", "source-a", "record-a", "Quant Intern", "https://example.invalid/new-a"),
        ("review-b", "source-b", "record-b", "Software Intern", "https://example.invalid/old-b"),
    ):
        body = f"<html><title>{title}</title><p>London Apply</p></html>".encode()
        filename = f"responses/{review_id}.bin"
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        observations.append(
            {
                "review_id": review_id,
                "historical_source_identity": {
                    "source_id": source_id,
                    "record_id": record_id,
                },
                "listing_status": "success",
                "role_match": True,
                "location_match": True,
                "requested_url": url,
                "final_url": url,
                "response_body_file": filename,
                "response_sha256": _sha(path),
                "response_status": 200,
                "retrieval_timestamp_utc": "2026-09-10T00:00:00Z",
                "application_state": "matching listing retrieved",
                "explicit_deadline": None,
                "education_graduation_statements": [],
                "sponsorship_work_authorization_statements": [],
                "evidence": [{"file": filename, "locator": "html:title", "quote": title}],
                "unresolved_questions": [],
            }
        )
    _dump(
        root / "verification-observations.json",
        {
            "schema_version": "efds-opportunity-verification-observations-v2",
            "run_id": "synthetic-verification",
            "source_pack_id": "synthetic-pack",
            "status": "complete",
            "count": 2,
            "observations": observations,
        },
    )
    response_entries = [
        {
            "raw_file": observation["response_body_file"],
            "raw_sha256": _sha(root / observation["response_body_file"]),
            "decoded_file": observation["response_body_file"],
            "decoded_sha256": _sha(root / observation["response_body_file"]),
        }
        for observation in observations
    ]
    _dump(
        root / "capture-manifest.json",
        {
            "run_id": "synthetic-verification",
            "source_pack_id": "synthetic-pack",
            "status": "complete",
            "response_entries": response_entries,
        },
    )
    _dump(
        root / "request-ledger.json",
        {
            "run_id": "synthetic-verification",
            "source_pack_id": "synthetic-pack",
            "status": "complete",
        },
    )
    return root


def _reconciliation(tmp_path: Path, pack: Path, verification: Path) -> Path:
    root = tmp_path / "reconciliation"
    (root / "gsa-discovery" / "responses").mkdir(parents=True)
    _dump(
        root / "corrections.json",
        {
            "schema_version": "synthetic",
            "source_pack_id": "synthetic-pack",
            "verification_run_id": "synthetic-verification",
            "all_human_decisions": "unreviewed",
            "corrections": [],
        },
    )
    corrected = []
    for review_id, source_id, record_id, title, historical, observed, year in (
        (
            "review-a",
            "source-a",
            "record-a",
            "Quant Intern",
            "https://example.invalid/old-a",
            "https://example.invalid/new-a",
            None,
        ),
        (
            "review-b",
            "source-b",
            "record-b",
            "Software Intern",
            "https://example.invalid/old-b",
            "https://example.invalid/old-b",
            "2027",
        ),
    ):
        evidence_file = f"responses/{review_id}.bin"
        corrected.append(
            {
                "review_id": review_id,
                "firm": "Example Quant" if review_id == "review-a" else "Example Tech",
                "title": title,
                "location": "London",
                "historical_application_url": historical,
                "observed_final_url": observed,
                "observed_listing_status": "matching listing retrieved",
                "matching_listing_observed": True,
                "apply_link_or_form_observed": True,
                "explicit_availability_statement": None,
                "programme_type": "internship",
                "programme_year": year,
                "programme_year_basis": (
                    "synthetic explicit programme evidence" if year else "unknown"
                ),
                "graduation_or_education_evidence": [],
                "deadline": "unknown",
                "evidence": [{"file": evidence_file, "locator": "html:title", "quote": title}],
                "unresolved_questions": [],
                "human_decision": "unreviewed",
                "historical_source_identity": {
                    "source_id": source_id,
                    "record_id": record_id,
                    "external_id": "external-a" if review_id == "review-a" else "external-b",
                    "digest_id": "digest-a" if review_id == "review-a" else "digest-b",
                    "original_batch": "batch-a" if review_id == "review-a" else "batch-b",
                },
            }
        )
    _dump(
        root / "corrected-review.json",
        {
            "schema_version": "synthetic",
            "source_pack_id": "synthetic-pack",
            "verification_run_id": "synthetic-verification",
            "count": 2,
            "opportunities": corrected,
        },
    )
    (root / "FINDINGS.md").write_text("synthetic findings\n", encoding="utf-8")
    (root / "gsa-discovery" / "request-ledger.json").write_text(
        json.dumps({"attempts": []}) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": "synthetic",
        "source_pack_id": "synthetic-pack",
        "verification_run_id": "synthetic-verification",
        "input_hashes": {
            "original_consolidated_pack": {
                name: _sha(pack / name)
                for name in (
                    "START-HERE.md",
                    "opportunities.csv",
                    "coverage-and-gaps.json",
                    "provenance.json",
                    "HUMAN_REVIEW.md",
                )
            },
            "verification_run_selected_files": {
                name: _sha(verification / name)
                for name in (
                    "capture-manifest.json",
                    "request-ledger.json",
                    "verification-observations.json",
                )
            },
        },
        "output_files": {},
        "evidence_file_sha256": {},
    }
    for name in ("corrections.json", "corrected-review.json", "FINDINGS.md"):
        manifest["output_files"][name] = _sha(root / name)
    _dump(root / "reconciliation-manifest.json", manifest)
    return root


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    pack = _pack(tmp_path)
    verification = _verification(tmp_path, pack)
    reconciliation = _reconciliation(tmp_path, pack, verification)
    return pack, verification, reconciliation


def test_consolidation_is_deterministic_and_preserves_unknowns(tmp_path: Path) -> None:
    pack, verification, reconciliation = _inputs(tmp_path)
    first = build_review_pack(pack, verification, reconciliation, tmp_path / "out-a")
    second = build_review_pack(pack, verification, reconciliation, tmp_path / "out-b")
    for name in (
        "START-HERE.md",
        "opportunities.csv",
        "HUMAN_REVIEW.md",
        "provenance.json",
        "coverage-and-gaps.json",
    ):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    rows = list(csv.DictReader((first / "opportunities.csv").open(encoding="utf-8", newline="")))
    assert rows[0]["application_url"] == "https://example.invalid/new-a"
    assert rows[0]["programme_year"] == "unknown"
    assert all(row["human_decision"] == "unreviewed" for row in rows)
    assert "16/166" in (first / "HUMAN_REVIEW.md").read_text(encoding="utf-8")


def test_changed_correction_id_and_dangling_evidence_fail(tmp_path: Path) -> None:
    pack, verification, reconciliation = _inputs(tmp_path)
    corrected_path = reconciliation / "corrected-review.json"
    corrected = json.loads(corrected_path.read_text())
    corrected["opportunities"][0]["evidence"][0]["file"] = "responses/missing.bin"
    _dump(corrected_path, corrected)
    manifest_path = reconciliation / "reconciliation-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["output_files"]["corrected-review.json"] = _sha(corrected_path)
    _dump(manifest_path, manifest)
    with pytest.raises(OpportunityReviewPackError, match="does not resolve to a file"):
        build_review_pack(pack, verification, reconciliation, tmp_path / "bad")


def test_mutated_existing_evidence_bytes_fail_without_manifest_change(tmp_path: Path) -> None:
    pack, verification, reconciliation = _inputs(tmp_path)
    evidence = verification / "responses" / "review-a.bin"
    evidence.write_bytes(evidence.read_bytes() + b"tampered")
    with pytest.raises(OpportunityReviewPackError, match="verification evidence hash mismatch"):
        build_review_pack(pack, verification, reconciliation, tmp_path / "bad")


def test_raw_response_must_be_declared_by_capture_manifest(tmp_path: Path) -> None:
    pack, verification, reconciliation = _inputs(tmp_path)
    observations_path = verification / "verification-observations.json"
    observations = json.loads(observations_path.read_text())
    original = verification / "responses" / "review-a.bin"
    unlisted = verification / "responses" / "unlisted.bin"
    unlisted.write_bytes(original.read_bytes())
    observations["observations"][0]["response_body_file"] = "responses/unlisted.bin"
    observations["observations"][0]["response_sha256"] = _sha(unlisted)
    _dump(observations_path, observations)
    manifest_path = reconciliation / "reconciliation-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["input_hashes"]["verification_run_selected_files"][
        "verification-observations.json"
    ] = _sha(observations_path)
    _dump(manifest_path, manifest)
    with pytest.raises(
        OpportunityReviewPackError,
        match="verification raw response is not capture-manifest bound",
    ):
        build_review_pack(pack, verification, reconciliation, tmp_path / "bad")


def test_review_revision_is_optional_but_pack_bound(tmp_path: Path) -> None:
    pack, verification, reconciliation = _inputs(tmp_path)
    review_pack = tmp_path / "review-pack"
    shutil.copytree(pack, review_pack)
    template = tmp_path / "template"
    create_review_template(review_pack, template)
    output = build_review_pack(
        pack,
        verification,
        reconciliation,
        tmp_path / "with-review",
        review_revision=template,
    )
    provenance = json.loads((output / "provenance.json").read_text())
    assert provenance["review_revision"]["status"] == "supplied"
    assert all(
        row["human_decision"] == "unreviewed"
        for row in csv.DictReader(
            (output / "opportunities.csv").open(encoding="utf-8", newline="")
        )
    )


def test_changed_pack_and_collision_are_rejected(tmp_path: Path) -> None:
    pack, verification, reconciliation = _inputs(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(OpportunityReviewPackError, match="already exists"):
        build_review_pack(pack, verification, reconciliation, output)
    (pack / "START-HERE.md").write_text("changed\n", encoding="utf-8")
    with pytest.raises(OpportunityReviewPackError, match="hash mismatch"):
        build_review_pack(pack, verification, reconciliation, tmp_path / "changed")


def test_cli_runs_offline_and_rejects_duplicate_embedded_json(tmp_path: Path) -> None:
    pack, verification, reconciliation = _inputs(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "research",
            "opportunity-review-pack",
            str(pack),
            str(verification),
            str(reconciliation),
            str(tmp_path / "cli-output"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "cli-output" / "review-pack-manifest.json").is_file()
    csv_path = pack / "opportunities.csv"
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0])
    rows[0]["evidence_references"] = '{"a":1,"a":2}'
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(OpportunityReviewPackError, match="duplicate JSON key"):
        build_review_pack(pack, verification, reconciliation, tmp_path / "duplicate")
