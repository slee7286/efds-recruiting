from pathlib import Path

from quant_recruiting.discovery.official import parse_sitemap
from quant_recruiting.discovery.scoring import classify_research_category, score_url
from quant_recruiting.jobs import classify_role, extract_internship_cycle, extract_job_posting
from quant_recruiting.utils import canonicalize_url


def test_url_canonicalization_preserves_material_query() -> None:
    assert (
        canonicalize_url("HTTP://Example.com:80/jobs/?utm_medium=x&role=qr#top")
        == "http://example.com/jobs?role=qr"
    )
    assert canonicalize_url("https://example.com/jobs?role=qr") != canonicalize_url(
        "https://example.com/jobs?role=trader"
    )


def test_sitemap_and_sitemap_index_parsing() -> None:
    pages, children = parse_sitemap(
        """<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>https://example.com/careers</loc></url></urlset>"""
    )
    assert pages == ["https://example.com/careers"]
    assert children == []
    pages, children = parse_sitemap(
        """<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><sitemap><loc>https://example.com/jobs.xml</loc></sitemap></sitemapindex>"""
    )
    assert pages == []
    assert children == ["https://example.com/jobs.xml"]


def test_relevance_scoring_is_transparent() -> None:
    score, reasons = score_url(
        "https://example.com/internships/quantitative-research", domain_type="careers"
    )
    assert score > 0.4
    assert any("intern" in reason or "careers" in reason for reason in reasons)
    assert (
        classify_research_category("https://example.com/technology/engineering")[0] == "technology"
    )


def test_jsonld_job_posting_and_malformed_jsonld() -> None:
    html = Path(__file__).parent.joinpath("fixtures", "job-posting.html").read_bytes()
    posting = extract_job_posting("https://example.com/jobs/qr", html)
    assert posting is not None
    assert posting.title == "Quantitative Research Intern"
    assert posting.external_id == "QR-2027"
    assert posting.structured_data["datePosted"] == "2026-07-01"
    malformed = b'<script type="application/ld+json">{not json</script>'
    assert extract_job_posting("https://example.com/jobs/bad", malformed) is None


def test_classification_and_explicit_cycle_wording() -> None:
    assert classify_role("QR Intern") == ("quantitative_research", 0.95)
    assert classify_role("Mystery Opportunity")[0] == "other"
    assert extract_internship_cycle("Summer 2027 Internship") == ("2027", "Summer 2027 Internship")
    assert extract_internship_cycle("open-ended role") == (None, None)
