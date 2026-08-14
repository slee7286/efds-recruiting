from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from quant_recruiting.ats import AshbyAdapter, GreenhouseAdapter, LeverAdapter, detect_ats
from quant_recruiting.db.models import CompanyATS, RefreshTarget
from quant_recruiting.jobs import classify_role
from quant_recruiting.refresh import is_due, record_failure, record_success
from quant_recruiting.research_discovery import classify_url, generate_queries


def _ats(provider: str, board: str) -> CompanyATS:
    return CompanyATS(
        company_id=uuid4(),
        provider=provider,
        board_identifier=board,
        board_url=f"https://jobs.{board}.example",
        discovered_at=datetime.now(timezone.utc),  # noqa: UP017
    )


def test_public_ats_detection_and_normalization() -> None:
    assert detect_ats("https://boards.greenhouse.io/example") is not None
    assert detect_ats("https://jobs.lever.co/example").provider == "lever"
    assert detect_ats("https://jobs.ashbyhq.com/example").provider == "ashby"
    assert (
        GreenhouseAdapter()
        .normalize_job(
            {
                "id": 1,
                "title": "Software Engineer Intern",
                "absolute_url": "https://boards.greenhouse.io/example/jobs/1",
                "content": "Build systems",
            },
            _ats("greenhouse", "example"),
        )
        .external_id
        == "1"
    )
    assert (
        LeverAdapter()
        .normalize_job(
            {
                "id": "l1",
                "text": "Investment Banking Summer Analyst",
                "hostedUrl": "https://jobs.lever.co/example/l1",
                "descriptionPlain": "Valuation",
            },
            _ats("lever", "example"),
        )
        .title.startswith("Investment")
    )
    assert (
        AshbyAdapter()
        .normalize_job(
            {
                "title": "Quantitative Research Intern",
                "jobUrl": "https://jobs.ashbyhq.com/example/qr",
                "descriptionPlain": "Probability",
            },
            _ats("ashby", "example"),
        )
        .title.startswith("Quantitative")
    )


def test_general_role_classification() -> None:
    assert classify_role("Investment Banking Summer Analyst")[0] == "investment_banking"
    assert classify_role("Software Engineer Intern")[0] == "software_engineering"
    assert classify_role("Quantitative Research Intern")[0] == "quantitative_research"


def test_research_queries_aliases_and_source_registry() -> None:
    company = SimpleNamespace(
        name="Example Bank", aliases=[SimpleNamespace(alias="Example Capital")]
    )
    queries = generate_queries(company, role_family="investment_banking", cycle="2027")
    assert any("Example Capital" in item.query for item in queries)
    assert any("investment banking" in item.query for item in queries)
    assert classify_url("https://www.reddit.com/r/jobs/example")[0] == "reddit"
    assert classify_url("https://example.com/report.pdf")[0] == "pdf"


def test_refresh_success_and_backoff() -> None:
    now = datetime(2026, 8, 12, tzinfo=timezone.utc)  # noqa: UP017
    target = RefreshTarget(entity_type="ats", entity_id=uuid4(), cadence_seconds=60)
    assert is_due(target, now)
    record_failure(target, "temporary", now)
    assert not is_due(target, now)
    assert target.failure_count == 1
    record_success(target, now)
    assert target.failure_count == 0
    assert target.next_due_at is not None
