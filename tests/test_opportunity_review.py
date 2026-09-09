from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from quant_recruiting.opportunity_review import (
    OpportunityReviewError,
    apply_review_annotations,
    create_review_template,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PACK = ROOT / "tests" / "fixtures" / "opportunity_review" / "pack"


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _template(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    output = tmp_path / "template"
    create_review_template(FIXTURE_PACK, output)
    document = _read(output / "annotations.json")
    return output, document


def _edited(tmp_path: Path, document: dict[str, object]) -> Path:
    path = tmp_path / "annotations-edited.json"
    _write(path, document)
    return path


def _recorded(document: dict[str, object]) -> dict[str, object]:
    annotations = document["annotations"]
    assert isinstance(annotations, list)
    first = annotations[0]
    assert isinstance(first, dict)
    first["availability"] = {
        "status": "open",
        "checked_at": "2026-09-09T12:00:00Z",
        "references": ["saved-evidence:/synthetic/role-1"],
        "note": "Synthetic positive control.",
    }
    first["relevance"] = {
        "status": "relevant",
        "checked_at": None,
        "references": [],
        "note": "Role family matches the declared review scope.",
    }
    first["deadline"] = {
        "status": "confirmed",
        "value": "2027-06-30",
        "precision": "date",
        "timezone": None,
        "checked_at": "2026-09-09T12:01:00Z",
        "references": ["saved-evidence:/synthetic/role-1/deadline"],
        "note": "Synthetic positive control.",
    }
    first["eligibility"] = {
        "status": "conditional",
        "subject": "an applicant graduating in 2027",
        "checked_at": "2026-09-09T12:02:00+00:00",
        "references": ["saved-evidence:/synthetic/role-1/eligibility"],
        "note": "Human assertion for this subject only.",
    }
    first["reviewer"] = "synthetic-reviewer"
    first["reviewed_at"] = "2026-09-09T12:03:00Z"
    second = annotations[1]
    assert isinstance(second, dict)
    second["eligibility"] = {
        "status": "unknown",
        "subject": "any prospective applicant",
        "checked_at": "2026-09-09T12:04:00Z",
        "references": [],
        "note": "The synthetic evidence does not establish eligibility.",
    }
    second["reviewer"] = "synthetic-reviewer"
    second["reviewed_at"] = "2026-09-09T12:05:00Z"
    return document


def test_template_is_complete_and_unreviewed(tmp_path: Path) -> None:
    output, document = _template(tmp_path)
    assert output.is_dir()
    assert document["schema_version"] == "efds-opportunity-annotation-v1"
    assert document["parent_revision"] is None
    assert len(document["annotations"]) == 2
    for annotation in document["annotations"]:
        assert annotation["reviewer"] is None
        assert annotation["reviewed_at"] is None
        assert annotation["availability"]["status"] == "unreviewed"
        assert annotation["relevance"]["status"] == "unreviewed"
        assert annotation["deadline"]["status"] == "unreviewed"
        assert annotation["eligibility"]["status"] == "unreviewed"
    assert "unreviewed" in (output / "review-summary.md").read_text(encoding="utf-8")


def test_valid_apply_preserves_snapshot_and_links_revision(tmp_path: Path) -> None:
    template_dir, template = _template(tmp_path)
    edited = _edited(tmp_path, _recorded(template))
    output = apply_review_annotations(FIXTURE_PACK, edited, tmp_path / "review-r1")
    applied = _read(output / "annotations.json")
    manifest = _read(output / "review-manifest.json")
    assert applied["parent_revision"] == template["revision_id"]
    assert applied["revision_id"] != template["revision_id"]
    assert applied["annotations"][0]["opportunity_snapshot"]["title"] == "Quantitative Intern"
    assert applied["annotations"][0]["eligibility"]["subject"] == "an applicant graduating in 2027"
    assert manifest["recorded_decision_count"] == 2
    assert manifest["unreviewed_count"] == 0
    assert template_dir.exists()


def test_unknown_and_conditional_states_are_independent(tmp_path: Path) -> None:
    _, template = _template(tmp_path)
    document = _recorded(template)
    first = document["annotations"][0]
    first["availability"] = {
        "status": "unknown",
        "checked_at": None,
        "references": [],
        "note": "No current check.",
    }
    first["reviewer"] = "synthetic-reviewer"
    first["reviewed_at"] = "2026-09-09T12:06:00Z"
    edited = _edited(tmp_path, document)
    output = apply_review_annotations(FIXTURE_PACK, edited, tmp_path / "review-r1")
    applied = _read(output / "annotations.json")
    assert applied["annotations"][0]["availability"]["status"] == "unknown"
    assert applied["annotations"][0]["eligibility"]["status"] == "conditional"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("foreign_id", "unknown review ID"),
        ("duplicate_id", "duplicate annotation review ID"),
        ("changed_snapshot", "opportunity facts changed"),
        ("changed_evidence", "source evidence identity changed"),
        ("bad_enum", "unsupported availability status"),
        ("bad_type", "availability.status must be a non-empty string"),
        ("missing_subject", "subject or audience"),
        ("bad_deadline", "confirmed deadline requires"),
    ],
)
def test_invalid_annotations_fail_for_the_intended_reason(
    tmp_path: Path, mutation: str, message: str
) -> None:
    _, template = _template(tmp_path)
    document = _recorded(template)
    first = document["annotations"][0]
    if mutation == "foreign_id":
        first["review_id"] = "foreign-review-id"
    elif mutation == "duplicate_id":
        document["annotations"][1]["review_id"] = first["review_id"]
    elif mutation == "changed_snapshot":
        first["opportunity_snapshot"]["title"] = "Changed fact"
    elif mutation == "changed_evidence":
        first["source_identity"]["raw_payload_sha256"] = "0" * 64
    elif mutation == "bad_enum":
        first["availability"]["status"] = "approved"
    elif mutation == "bad_type":
        first["availability"]["status"] = True
    elif mutation == "missing_subject":
        first["eligibility"]["subject"] = None
    elif mutation == "bad_deadline":
        first["deadline"]["value"] = None
    with pytest.raises(OpportunityReviewError, match=message):
        apply_review_annotations(
            FIXTURE_PACK, _edited(tmp_path, document), tmp_path / f"bad-{mutation}"
        )


def test_pack_change_duplicate_json_and_collision_are_rejected(tmp_path: Path) -> None:
    template_dir, template = _template(tmp_path)
    collision = tmp_path / "collision"
    collision.mkdir()
    with pytest.raises(OpportunityReviewError, match="already exists"):
        create_review_template(FIXTURE_PACK, collision)

    copied_pack = tmp_path / "changed-pack"
    shutil.copytree(FIXTURE_PACK, copied_pack)
    (copied_pack / "START-HERE.md").write_text("changed\n", encoding="utf-8")
    with pytest.raises(OpportunityReviewError, match="pack file hashes changed"):
        apply_review_annotations(
            copied_pack, _edited(tmp_path, _recorded(template)), tmp_path / "changed"
        )

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"pack_id":"a","pack_id":"b"}\n', encoding="utf-8")
    with pytest.raises(OpportunityReviewError, match="duplicate JSON key"):
        apply_review_annotations(FIXTURE_PACK, duplicate, tmp_path / "duplicate")


def test_deterministic_revisions_and_handled_publish_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, template = _template(tmp_path)
    edited = _edited(tmp_path, _recorded(template))
    first = apply_review_annotations(FIXTURE_PACK, edited, tmp_path / "r1")
    second = apply_review_annotations(FIXTURE_PACK, edited, tmp_path / "r2")
    for name in ("annotations.json", "review-summary.md", "review-manifest.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()

    import quant_recruiting.opportunity_review as review

    original_replace = review.os.replace

    def fail_replace(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic publish failure")

    monkeypatch.setattr(review.os, "replace", fail_replace)
    failed = tmp_path / "failed"
    with pytest.raises(OpportunityReviewError, match="could not publish"):
        review.create_review_template(FIXTURE_PACK, failed)
    monkeypatch.setattr(review.os, "replace", original_replace)
    assert not failed.exists()
    assert not list(tmp_path.glob(f".{failed.name}.*"))


def test_cli_template_runs_without_database_configuration(tmp_path: Path) -> None:
    output = tmp_path / "cli-template"
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT / "src"),
            "DATABASE_URL": "postgresql://invalid.example.test/never-used",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "quant_recruiting.cli",
            "research",
            "opportunity-review-template",
            str(FIXTURE_PACK),
            str(output),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (output / "annotations.json").is_file()
    assert "template:" in result.stdout


def test_cli_apply_runs_offline_with_an_explicit_synthetic_decision(tmp_path: Path) -> None:
    template_dir = tmp_path / "cli-template"
    applied_dir = tmp_path / "cli-review"
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT / "src"),
            "DATABASE_URL": "postgresql://invalid.example.test/never-used",
        }
    )
    template_result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "quant_recruiting.cli",
            "research",
            "opportunity-review-template",
            str(FIXTURE_PACK),
            str(template_dir),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert template_result.returncode == 0, template_result.stderr
    edited = _recorded(_read(template_dir / "annotations.json"))
    edited_path = tmp_path / "edited.json"
    _write(edited_path, edited)
    apply_result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "quant_recruiting.cli",
            "research",
            "opportunity-review-apply",
            str(FIXTURE_PACK),
            str(edited_path),
            str(applied_dir),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert apply_result.returncode == 0, apply_result.stderr
    assert (applied_dir / "annotations.json").is_file()
    assert "review:" in apply_result.stdout
