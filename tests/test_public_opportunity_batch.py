from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from quant_recruiting.public_opportunity_batch import (
    CollectionLimits,
    PublicBatchError,
    PublicBatchManifest,
    collect_public_batch,
    replay_saved_captures,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def _manifest(
    *,
    source_ids: list[str] | None = None,
    limits: CollectionLimits | None = None,
) -> dict[str, object]:
    sources = []
    for source_id in source_ids or ["example"]:
        sources.append(
            {
                "source_id": source_id,
                "firm": "Example Quant Labs",
                "official_careers_url": "https://careers.example.test/careers",
                "endpoint_url": "https://boards-api.example.test/v1/boards/example/jobs",
                "provider": "greenhouse",
                "board_id": "example",
                "allowed_hosts": ["boards-api.example.test", "careers.example.test"],
                "board_evidence": "Official careers page links to the public Example ATS board.",
                "adapter": "greenhouse",
                "pagination": "single Greenhouse jobs response; truncation is recorded",
                "observed_at_utc": "2026-09-09T10:00:00Z",
            }
        )
    return {
        "schema_version": "efds-public-opportunity-batch-v1",
        "batch_id": "batch-test",
        "scope": "synthetic UK finance and technology opportunities",
        "limits": (limits or CollectionLimits(min_host_interval_seconds=2.0)).__dict__,
        "sources": sources,
    }


def _posting_payload(*, jobs: list[dict[str, object]]) -> bytes:
    return json.dumps({"jobs": jobs}, sort_keys=True).encode()


def _job(
    *,
    job_id: int = 1,
    title: str = "Quantitative Research Intern 2027",
    description: str = "London, UK. Students graduating in 2027 are eligible.",
    url: str = "https://boards-api.example.test/job/1",
) -> dict[str, object]:
    return {
        "id": job_id,
        "title": title,
        "content": description,
        "absolute_url": url,
        "location": {"name": "London, UK"},
        "first_published": "2026-09-01T00:00:00Z",
    }


def _run(
    tmp_path: Path,
    handler,
    *,
    manifest: dict[str, object] | None = None,
) -> dict[str, object]:
    manifest_path = tmp_path / "source-manifest.json"
    manifest_path.write_text(json.dumps(manifest or _manifest()), encoding="utf-8")
    clock = FakeClock()
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        batch = collect_public_batch(
            manifest_path,
            tmp_path / "batch",
            client=client,
            clock=clock.now,
            sleeper=clock.sleep,
        )
    batch["_test_sleeps"] = clock.sleeps
    return batch


def test_valid_manifest_requires_authorized_complete_limits() -> None:
    parsed = PublicBatchManifest.from_mapping(_manifest())
    assert parsed.sources[0].provider == "greenhouse"
    bad = _manifest()
    bad["limits"] = {**bad["limits"], "min_host_interval_seconds": 1.0}
    with pytest.raises(PublicBatchError, match="two-second"):
        PublicBatchManifest.from_mapping(bad)


def test_successful_capture_preserves_bytes_evidence_and_unknowns(tmp_path: Path) -> None:
    board_body = _posting_payload(jobs=[_job()])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "careers.example.test":
            return httpx.Response(
                200, text="Official careers page links to boards-api.example.test"
            )
        return httpx.Response(200, content=board_body)

    batch = _run(tmp_path, handler)
    digest = batch["digest"]
    assert digest["status"] == "complete"
    assert len(digest["opportunities"]) == 1
    opportunity = digest["opportunities"][0]
    assert opportunity["facts"]["firm"]["value"] == "Example Quant Labs"
    assert opportunity["facts"]["location"]["value"] == "London, UK"
    assert opportunity["facts"]["deadline"]["status"] == "unknown"
    assert opportunity["facts"]["eligibility"]["status"] == "known"
    capture = tmp_path / "batch" / "captures" / "example" / "board-page-1.bin"
    assert capture.read_bytes() == board_body
    digest_input = json.loads((tmp_path / "batch" / "digest-input.json").read_text())
    board_meta = digest_input["sources"][0]["records"][0]["raw_payload"]["capture"]["board"]
    assert board_meta["body_sha256"] == hashlib.sha256(capture.read_bytes()).hexdigest()


def test_compatible_eligibility_dimensions_do_not_become_a_digest_conflict(
    tmp_path: Path,
) -> None:
    board_body = _posting_payload(
        jobs=[
            _job(
                description=(
                    "London, UK. Students graduating in 2027 are eligible. "
                    "Candidates requiring visa sponsorship should apply by March."
                )
            )
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=board_body if "boards-api" in request.url.host else b"careers",
        )

    batch = _run(tmp_path, handler)
    record = json.loads((tmp_path / "batch" / "digest-input.json").read_text())[
        "sources"
    ][0]["records"][0]
    claims = record["raw_payload"]["derived"]["eligibility_claims"]
    assert [claim["dimension"] for claim in claims] == ["graduation", "sponsorship"]
    eligibility = batch["digest"]["opportunities"][0]["facts"]["eligibility"]
    assert eligibility["status"] == "known"
    assert eligibility["value"]["dimension"] == "graduation"
    assert eligibility["evidence"][0]["locator"] == "/derived/eligibility_claims/0"


def test_same_dimension_eligibility_contradictions_remain_visible(
    tmp_path: Path,
) -> None:
    board_body = _posting_payload(
        jobs=[
            _job(
                description=(
                    "London, UK. Students graduating in 2027 are eligible. "
                    "Students graduating in 2028 are not eligible."
                )
            )
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=board_body if "boards-api" in request.url.host else b"careers",
        )

    batch = _run(tmp_path, handler)
    record = json.loads((tmp_path / "batch" / "digest-input.json").read_text())[
        "sources"
    ][0]["records"][0]
    claims = record["raw_payload"]["derived"]["eligibility_claims"]
    assert len(claims) == 2
    assert all(claim["dimension"] == "graduation" for claim in claims)
    eligibility = batch["digest"]["opportunities"][0]["facts"]["eligibility"]
    assert eligibility["status"] == "conflict"
    assert {
        reference["locator"]
        for claim in eligibility["claims"]
        for reference in claim["evidence"]
    } == {"/derived/eligibility_claims/0", "/derived/eligibility_claims/1"}


def test_saved_capture_replay_can_write_a_new_revision(tmp_path: Path) -> None:
    board_body = _posting_payload(jobs=[_job()])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=board_body if "boards-api" in request.url.host else b"careers",
        )

    batch = _run(tmp_path, handler)
    source = tmp_path / "batch"
    revision = tmp_path / "revision"
    replayed = replay_saved_captures(source, output_dir=revision)
    assert replayed["digest"]["digest_id"] == batch["digest"]["digest_id"]
    assert (source / "captures" / "example" / "board-page-1.bin").read_bytes() == board_body
    assert (revision / "digest" / "opportunity-digest.json").exists()


def test_empty_source_is_complete_but_failed_source_is_incomplete(tmp_path: Path) -> None:
    manifest = _manifest(source_ids=["empty", "failed"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "careers.example.test":
            if "failed" in request.url.path:
                raise httpx.ConnectError("synthetic unavailable", request=request)
            return httpx.Response(200, text="careers")
        if request.url.host == "boards-api.example.test" and "failed" in request.url.path:
            raise httpx.ConnectError("synthetic unavailable", request=request)
        if request.url.host == "careers.example.test":
            return httpx.Response(200, text="careers")
        return httpx.Response(200, content=_posting_payload(jobs=[]))

    # The two source records intentionally share URLs in the small fixture;
    # route the second source by changing its endpoint path.
    manifest["sources"][1]["official_careers_url"] = "https://careers.example.test/failed"
    manifest["sources"][1]["endpoint_url"] = "https://boards-api.example.test/failed"
    batch = _run(tmp_path, handler, manifest=manifest)
    statuses = {item["source_id"]: item["status"] for item in batch["report"]["sources"]}
    assert statuses == {"empty": "complete", "failed": "failed"}
    assert batch["digest"]["status"] == "incomplete"
    assert batch["digest"]["opportunities"] == []


def test_redirect_outside_allowlist_fails_closed(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "careers.example.test":
            return httpx.Response(302, headers={"location": "https://unexpected.example/jobs"})
        raise AssertionError("unexpected host reached")

    batch = _run(tmp_path, handler)
    source = batch["report"]["sources"][0]
    assert source["status"] == "failed"
    assert "allowlist" in source["error"]
    assert batch["report"]["requests"] == 1


def test_oversized_response_is_rejected_before_digest_admission(tmp_path: Path) -> None:
    oversized = b"x" * (2 * 1024 * 1024 + 1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=oversized)

    batch = _run(tmp_path, handler)
    assert batch["report"]["sources"][0]["status"] == "failed"
    assert "per-response" in batch["report"]["sources"][0]["error"]
    assert batch["digest"]["status"] == "incomplete"


def test_retry_after_and_timeout_stay_inside_attempt_budget(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.host == "careers.example.test":
            return httpx.Response(200, text="careers")
        calls += 1
        if calls <= 3:
            return httpx.Response(503, headers={"retry-after": "1"})
        raise AssertionError("the bounded retry budget should stop before a fourth attempt")

    batch = _run(tmp_path, handler)
    assert calls == 3
    assert 1.0 in batch["_test_sleeps"]
    assert batch["report"]["sources"][0]["status"] == "failed"
    assert batch["report"]["requests"] == 4


def test_timeout_retries_then_marks_source_failed(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.host == "careers.example.test":
            return httpx.Response(200, text="careers")
        calls += 1
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    batch = _run(tmp_path, handler)
    assert calls == 3
    assert batch["report"]["requests"] == 4
    assert batch["report"]["sources"][0]["status"] == "failed"


def test_truncation_is_recorded_and_incomplete_records_are_not_admitted(tmp_path: Path) -> None:
    limits = CollectionLimits(max_pages_per_source=1, min_host_interval_seconds=2.0)
    jobs = [
        _job(job_id=index, url=f"https://boards-api.example.test/job/{index}")
        for index in range(501)
    ]
    body = _posting_payload(jobs=jobs)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    batch = _run(tmp_path, handler, manifest=_manifest(limits=limits))
    assert batch["report"]["sources"][0]["status"] == "truncated"
    assert batch["digest"]["opportunities"] == []


def test_cli_replay_is_local_and_digest_is_reproducible(tmp_path: Path) -> None:
    board_body = _posting_payload(jobs=[_job()])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=board_body if "boards-api" in request.url.host else b"careers"
        )

    batch = _run(tmp_path, handler)
    input_path = batch["input_path"]
    first = tmp_path / "replay-one"
    second = tmp_path / "replay-two"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [
        sys.executable,
        "-B",
        "-m",
        "quant_recruiting.cli",
        "research",
        "public-opportunity-batch",
        str(input_path),
        str(first),
        "--replay-input",
        str(input_path),
    ]
    completed = subprocess.run(
        command, cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    subprocess.run(
        [*command[:-3], str(second), "--replay-input", str(input_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert (first / "opportunity-digest.json").read_bytes() == (
        second / "opportunity-digest.json"
    ).read_bytes()
    assert (first / "opportunity-digest.md").read_bytes() == (
        second / "opportunity-digest.md"
    ).read_bytes()


def test_private_destination_is_rejected_before_request() -> None:
    manifest = _manifest()
    manifest["sources"][0]["official_careers_url"] = "http://127.0.0.1/careers"
    with pytest.raises(PublicBatchError, match="private or local"):
        PublicBatchManifest.from_mapping(manifest)
