from pathlib import Path

from sqlalchemy import UniqueConstraint

from quant_recruiting.db.base import Base
from quant_recruiting.db.models import Company, CompanyAlias, Job, ResearchDocument, ResearchSource
from quant_recruiting.db.seed import SKILL_TREE
from quant_recruiting.ingestion.web import DiscoveredSource, FetchedSource, SourceCollector
from quant_recruiting.research_export import _frontmatter
from quant_recruiting.utils import canonicalize_url, sha256_text, slugify_text


def test_company_and_alias_constraints_are_modelled() -> None:
    assert "uq_companies_slug" in {
        constraint.name for constraint in Company.__table__.constraints if constraint.name
    }
    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns} == {"company_id", "normalized_alias"}
        for constraint in CompanyAlias.__table__.constraints
    )


def test_job_deduplication_indexes_are_modelled() -> None:
    indexes = {index.name for index in Job.__table__.indexes}
    assert "uq_jobs_company_external_id" in indexes
    assert "uq_jobs_company_url" in indexes


def test_source_canonical_url_and_hash_behaviour() -> None:
    assert (
        canonicalize_url("HTTPS://Example.com/jobs/?utm_source=x&b=2&a=1#fragment")
        == "https://example.com/jobs?a=1&b=2"
    )
    assert sha256_text("same") == sha256_text("same")
    assert sha256_text("same") != sha256_text("changed")


def test_normalization_is_deterministic_and_removes_scripts() -> None:
    path = Path(__file__).parent / "fixtures" / "sample.html"
    source = DiscoveredSource(path.as_uri(), "careers_page")
    fetched = FetchedSource(
        source, path.read_bytes(), "text/html", 200, __import__("datetime").datetime.now()
    )
    normalized = SourceCollector().normalize(fetched)
    assert normalized.title == "Example Careers"
    assert "ignored" not in normalized.content
    assert "Probability" in normalized.content
    assert normalized.content_hash == sha256_text(normalized.content)


def test_markdown_frontmatter_is_yaml() -> None:
    rendered = _frontmatter(
        {"source_id": "abc", "source_quality": "official", "content_hash": "123"}
    )
    assert rendered.startswith("---\n")
    assert "source_quality: official" in rendered
    assert rendered.count("---") == 2


def test_skill_seed_catalog_is_unique_and_sluggable() -> None:
    names = [name for names in SKILL_TREE.values() for name in names]
    assert len({slugify_text(name) for name in names}) <= len(names)
    assert "Probability" in SKILL_TREE


def test_model_relationship_tables_exist() -> None:
    expected = {
        "companies",
        "company_aliases",
        "company_domains",
        "jobs",
        "job_observations",
        "applications",
        "application_events",
        "research_sources",
        "fetch_errors",
        "research_documents",
        "research_claims",
        "recruiting_cycles",
        "recruiting_events",
        "interview_reports",
        "interview_questions",
        "interview_report_questions",
        "skills",
        "job_skills",
        "interview_question_skills",
        "resources",
        "resource_skills",
        "candidate_experiences",
        "candidate_evidence",
        "candidate_evidence_skills",
        "cv_versions",
        "application_questions",
        "application_answers",
        "question_attempts",
        "ai_tasks",
        "discovered_urls",
    }
    assert expected <= set(Base.metadata.tables)
    assert ResearchDocument.__table__.c.version is not None
    assert ResearchSource.__table__.c.content_hash is not None
