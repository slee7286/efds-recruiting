from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import quant_recruiting.opportunity_digest as digest_module
from quant_recruiting.opportunity_digest import (
    DigestInputError,
    build_opportunity_digest,
    render_digest_json,
    render_digest_markdown,
    run_fixture_digest,
    write_digest_outputs,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "opportunity_digest" / "sample-capture.json"


def sample_manifest() -> dict[str, object]:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _claim(value: object, source_id: str, record_id: str, field: str) -> dict[str, object]:
    quote = value if isinstance(value, str) else json.dumps(
        value, separators=(",", ":"), sort_keys=True
    )
    return {
        "value": value,
        "evidence": [
            {
                "source_id": source_id,
                "record_id": record_id,
                "field": field,
                "locator": f"/{field}",
                "quote": quote,
            }
        ],
    }


def _minimal_manifest(
    *, sources: list[dict[str, object]], expected: list[str] | None = None
) -> dict[str, object]:
    expected_ids = expected if expected is not None else [source["source_id"] for source in sources]
    return {
        "schema_version": "efds-opportunity-capture-v1",
        "parser_version": "local-opportunity-parser-v1",
        "policy_id": "efds-opportunity-policy-v1",
        "expected_sources": expected_ids,
        "sources": sources,
    }


def _source(record: dict[str, object], *, source_id: str = "source-a") -> dict[str, object]:
    return {
        "source_id": source_id,
        "provider": "synthetic",
        "board_id": "board-a",
        "source_url": "https://source.example.invalid/jobs",
        "observed_at_utc": "2026-09-08T00:00:00Z",
        "capture_status": "complete",
        "records": [record],
    }


def _record(
    *,
    record_id: str = "record-a",
    external_id: str | None = "role-a",
    source_id: str = "source-a",
    job_url: str = "https://jobs.example.invalid/role-a",
) -> dict[str, object]:
    facts = {
        "firm": [_claim("Example Quant Labs", source_id, record_id, "firm")],
        "role": [_claim("Research Intern", source_id, record_id, "role")],
        "location": [_claim("London", source_id, record_id, "location")],
        "job_url": [_claim(job_url, source_id, record_id, "job_url")],
    }
    record: dict[str, object] = {
        "record_id": record_id,
        "record_status": "included",
        "raw_payload": {
            "record_id": record_id,
            "title": "Research Intern",
            "firm": "Example Quant Labs",
            "role": "Research Intern",
            "location": "London",
            "job_url": job_url,
        },
        "facts": facts,
    }
    if external_id is not None:
        record["external_id"] = external_id
    return record


def test_complete_opportunity_retains_evidence_and_unknowns() -> None:
    result = build_opportunity_digest(sample_manifest())

    assert result["status"] == "incomplete"  # the fixture intentionally includes one failed source
    assert len(result["opportunities"]) == 2
    accepted = next(item for item in result["opportunities"] if item["external_id"] == "role-001")
    assert accepted["facts"]["firm"]["value"] == "Example Quant Labs"
    assert accepted["facts"]["application_url"]["status"] == "known"
    assert accepted["facts"]["eligibility"] == {
        "status": "unknown",
        "value": None,
        "reason": "not_reported",
        "evidence": [],
    }
    assert accepted["facts"]["firm"]["evidence"][0]["record_id"] == "accepted-001"


def test_missing_deadline_is_unknown_and_structured_eligibility_is_preserved() -> None:
    record = _record()
    eligibility = {"dimension": "work_authorization", "status": "required"}
    record["raw_payload"]["eligibility"] = eligibility
    record["facts"]["eligibility"] = [
        _claim(eligibility, "source-a", "record-a", "eligibility")
    ]
    result = build_opportunity_digest(_minimal_manifest(sources=[_source(record)]))
    opportunity = result["opportunities"][0]

    assert opportunity["facts"]["deadline"]["status"] == "unknown"
    assert opportunity["facts"]["eligibility"]["value"] == eligibility


def test_malformed_deadline_is_excluded_with_a_source_error() -> None:
    record = _record()
    record["raw_payload"]["deadline"] = "tomorrow"
    record["facts"]["deadline"] = [_claim("tomorrow", "source-a", "record-a", "deadline")]
    result = build_opportunity_digest(_minimal_manifest(sources=[_source(record)]))

    assert result["opportunities"] == []
    assert result["exclusions"][0]["reason"].endswith("must be an ISO date")
    assert result["source_errors"][0]["code"] == "malformed_record"


def test_provider_scoped_duplicate_collapses_and_preserves_references() -> None:
    result = build_opportunity_digest(sample_manifest())
    accepted = next(item for item in result["opportunities"] if item["external_id"] == "role-001")

    assert len(result["opportunities"]) == 2
    assert {item["record_id"] for item in accepted["source_references"]} == {
        "accepted-001",
        "accepted-duplicate",
    }
    assert len(accepted["facts"]["firm"]["evidence"]) == 2


def test_same_external_id_on_another_provider_stays_separate() -> None:
    first = _source(_record())
    second_record = _record(record_id="record-b", source_id="source-b")
    second = _source(second_record, source_id="source-b")
    second["provider"] = "other-synthetic"
    manifest = _minimal_manifest(sources=[first, second])

    result = build_opportunity_digest(manifest)

    assert len(result["opportunities"]) == 2
    assert {item["provider"] for item in result["opportunities"]} == {
        "synthetic",
        "other-synthetic",
    }


def test_same_external_id_on_another_board_stays_separate() -> None:
    first = _source(_record())
    second_record = _record(record_id="record-b", source_id="source-b")
    second = _source(second_record, source_id="source-b")
    second["board_id"] = "board-b"
    result = build_opportunity_digest(_minimal_manifest(sources=[first, second]))

    assert len(result["opportunities"]) == 2
    assert {item["board_id"] for item in result["opportunities"]} == {"board-a", "board-b"}


def test_conflicting_claims_remain_visible() -> None:
    record = _record()
    facts = record["facts"]
    assert isinstance(facts, dict)
    facts["deadline"] = [
        _claim("2026-10-01", "source-a", "record-a", "deadline"),
        _claim("2026-11-01", "source-a", "record-a", "deadline"),
    ]
    record["raw_payload"]["deadline_claims"] = ["2026-10-01", "2026-11-01"]
    facts["deadline"][0]["evidence"][0]["locator"] = "/deadline_claims/0"
    facts["deadline"][1]["evidence"][0]["locator"] = "/deadline_claims/1"
    result = build_opportunity_digest(_minimal_manifest(sources=[_source(record)]))
    deadline = result["opportunities"][0]["facts"]["deadline"]

    assert deadline["status"] == "conflict"
    assert {claim["value"] for claim in deadline["claims"]} == {"2026-10-01", "2026-11-01"}
    assert all(claim["evidence"] for claim in deadline["claims"])


def test_claim_and_quote_mutation_without_payload_change_is_rejected() -> None:
    manifest = sample_manifest()
    claim = manifest["sources"][1]["records"][0]["facts"]["firm"][0]
    claim["value"] = "Fabricated Quant Labs"
    claim["evidence"][0]["quote"] = "Fabricated Quant Labs"

    with pytest.raises(DigestInputError, match="evidence value"):
        build_opportunity_digest(manifest)

    manifest = sample_manifest()
    manifest["sources"][1]["records"][0]["raw_payload"]["firm"] = "Changed Payload"
    with pytest.raises(DigestInputError, match="evidence value"):
        build_opportunity_digest(manifest)


def test_exclusion_and_failed_source_are_visible() -> None:
    excluded = {
        "record_id": "irrelevant",
        "record_status": "unsupported",
        "exclusion_reason": "unsupported_provider_record",
        "raw_payload": {"title": "Unsupported"},
    }
    failed = {
        "source_id": "source-failed",
        "provider": "synthetic",
        "board_id": "failure-board",
        "source_url": "https://failure.example.invalid/jobs",
        "observed_at_utc": "2026-09-08T00:00:00Z",
        "capture_status": "failed",
        "error": "synthetic failure",
        "records": [],
    }
    result = build_opportunity_digest(
        _minimal_manifest(
            sources=[_source(excluded), failed], expected=["source-a", "source-failed"]
        )
    )

    assert result["status"] == "incomplete"
    assert len(result["exclusions"]) == 1
    assert result["exclusions"][0]["source_id"] == "source-a"
    assert result["exclusions"][0]["record_id"] == "irrelevant"
    assert result["exclusions"][0]["reason"] == "unsupported_provider_record"
    assert result["exclusions"][0]["raw_payload_sha256"]
    assert result["source_errors"][0]["code"] == "capture_failed"


def test_missing_expected_source_is_incomplete_not_complete_empty() -> None:
    result = build_opportunity_digest(
        _minimal_manifest(sources=[], expected=["source-never-captured"])
    )

    assert result["status"] == "incomplete"
    assert result["source_errors"] == [
        {
            "source_id": "source-never-captured",
            "code": "missing_expected_source",
            "message": "expected source was not supplied",
        }
    ]


def test_partial_source_records_are_not_admitted() -> None:
    source = _source(_record())
    source["capture_status"] = "partial"
    source["error"] = "synthetic pagination ended early"
    result = build_opportunity_digest(_minimal_manifest(sources=[source]))

    assert result["status"] == "incomplete"
    assert result["opportunities"] == []
    assert result["exclusions"][0]["reason"] == "incomplete_source_record"


def test_missing_core_facts_are_excluded_with_payload_digest() -> None:
    record = _record()
    del record["facts"]["firm"]
    result = build_opportunity_digest(_minimal_manifest(sources=[_source(record)]))

    assert result["opportunities"] == []
    assert result["exclusions"][0]["reason"] == "missing_core_fact"
    assert result["exclusions"][0]["raw_payload_sha256"]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda manifest: manifest["sources"][0]["records"][0]["facts"]["firm"][0][
                "evidence"
            ][0].update(record_id="other-record"),
            "evidence identity",
        ),
        (
            lambda manifest: manifest["sources"][0]["records"][0]["facts"]["role"][0][
                "evidence"
            ][0].update(locator="record:record-a.location"),
            "evidence locator",
        ),
    ],
)
def test_dangling_or_mismatched_evidence_rejects(mutator, message: str) -> None:
    manifest = _minimal_manifest(sources=[_source(_record())])
    mutator(manifest)

    with pytest.raises(DigestInputError, match=message):
        build_opportunity_digest(manifest)


def test_malformed_url_and_unknown_fields_fail_before_admission() -> None:
    manifest = _minimal_manifest(sources=[_source(_record())])
    record = manifest["sources"][0]["records"][0]
    record["facts"]["job_url"][0]["value"] = "not-a-url"
    with pytest.raises(DigestInputError, match=r"absolute http\(s\) URL"):
        build_opportunity_digest(manifest)

    manifest = _minimal_manifest(sources=[_source(_record())])
    manifest["sources"][0]["source_url"] = "https://[malformed"
    with pytest.raises(DigestInputError, match="malformed"):
        build_opportunity_digest(manifest)

    manifest = _minimal_manifest(sources=[_source(_record())])
    manifest["sources"][0]["records"][0]["facts"]["unknown_fact"] = []
    with pytest.raises(DigestInputError, match="unknown field"):
        build_opportunity_digest(manifest)

    manifest = _minimal_manifest(sources=[_source(_record())])
    del manifest["sources"][0]["records"][0]["record_status"]
    with pytest.raises(DigestInputError, match="record_status"):
        build_opportunity_digest(manifest)


def test_repeated_rendering_is_byte_identical_and_markdown_agrees() -> None:
    result_a = build_opportunity_digest(sample_manifest())
    result_b = build_opportunity_digest(sample_manifest())
    json_a = render_digest_json(result_a)
    json_b = render_digest_json(result_b)
    markdown = render_digest_markdown(result_a)

    assert json_a == json_b
    assert render_digest_markdown(result_a) == render_digest_markdown(result_b)
    assert result_a["digest_id"] in markdown
    for opportunity in result_a["opportunities"]:
        assert opportunity["identity"] in markdown
        assert opportunity["content_sha256"] in json_a
    assert "Source errors" in markdown
    assert "Exclusions" in markdown


def test_committed_sample_outputs_match_current_generator() -> None:
    result = build_opportunity_digest(sample_manifest())
    output_dir = ROOT / "tests" / "fixtures" / "opportunity_digest" / "sample-output"
    generated_json = render_digest_json(result)
    assert (output_dir / "opportunity-digest.json").read_text(encoding="utf-8") == generated_json
    markdown = (output_dir / "opportunity-digest.md").read_text(encoding="utf-8")
    assert markdown == render_digest_markdown(result)
    for opportunity in result["opportunities"]:
        assert opportunity["identity"] in markdown
        for fact in opportunity["facts"].values():
            for evidence in fact.get("evidence", []):
                assert evidence["record_id"] in markdown


def test_advisory_ranking_is_separate_from_source_facts() -> None:
    result = build_opportunity_digest(sample_manifest())
    facts_before = copy.deepcopy([item["facts"] for item in result["opportunities"]])

    assert "advisory" not in result["opportunities"][0]
    assert result["advisory_ranking"]["candidate_specific_fit_assessed"] is False
    assert facts_before == [item["facts"] for item in result["opportunities"]]


def test_output_collision_is_rejected_without_overwrite(tmp_path: Path) -> None:
    result = build_opportunity_digest(sample_manifest())
    write_digest_outputs(result, tmp_path)
    json_path = tmp_path / "opportunity-digest.json"
    original = json_path.read_text(encoding="utf-8")

    with pytest.raises(DigestInputError, match="already exist"):
        write_digest_outputs(result, tmp_path)
    assert json_path.read_text(encoding="utf-8") == original


def test_overwrite_failure_restores_existing_output_pair(tmp_path: Path, monkeypatch) -> None:
    result = build_opportunity_digest(sample_manifest())
    write_digest_outputs(result, tmp_path)
    original_json = (tmp_path / "opportunity-digest.json").read_bytes()
    original_markdown = (tmp_path / "opportunity-digest.md").read_bytes()
    real_replace = digest_module.os.replace
    failed = False

    def fail_markdown_replace(source, target):
        nonlocal failed
        if Path(target) == tmp_path / "opportunity-digest.md" and not failed:
            failed = True
            raise OSError("synthetic second-file failure")
        real_replace(source, target)

    monkeypatch.setattr(digest_module.os, "replace", fail_markdown_replace)
    with pytest.raises(DigestInputError, match="could not publish"):
        write_digest_outputs(result, tmp_path, overwrite=True)
    assert (tmp_path / "opportunity-digest.json").read_bytes() == original_json
    assert (tmp_path / "opportunity-digest.md").read_bytes() == original_markdown


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    input_path = tmp_path / "duplicate.json"
    input_path.write_text(
        '{"schema_version":"one","schema_version":"two"}', encoding="utf-8"
    )

    with pytest.raises(DigestInputError, match="duplicate JSON key"):
        run_fixture_digest(input_path, tmp_path / "output")


def test_cli_runs_fixture_path_without_database_or_network(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT / "src"),
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "quant_recruiting.cli",
            "research",
            "opportunity-digest",
            str(SAMPLE),
            str(output_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    output_json = output_dir / "opportunity-digest.json"
    output_markdown = output_dir / "opportunity-digest.md"
    parsed = json.loads(output_json.read_text(encoding="utf-8"))
    assert parsed["schema_version"] == "efds-opportunity-digest-v1"
    assert parsed["status"] == "incomplete"
    assert output_markdown.exists()
    assert "digest:" in completed.stdout


def test_cli_rejects_collision_without_overwrite(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    result = build_opportunity_digest(sample_manifest())
    write_digest_outputs(result, output_dir)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT / "src"),
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "quant_recruiting.cli",
            "research",
            "opportunity-digest",
            str(SAMPLE),
            str(output_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "already exist" in completed.stderr
