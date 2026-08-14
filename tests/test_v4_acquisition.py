from io import BytesIO
from types import SimpleNamespace

import httpx
from pypdf import PdfWriter

from quant_recruiting.extraction import InterviewDocumentExtractor, topic_slugs
from quant_recruiting.ingestion.web import DiscoveredSource, FetchedSource, SourceCollector
from quant_recruiting.public_sources import (
    normalize_reddit_payload,
    normalize_transcript,
    youtube_video_id,
)
from quant_recruiting.research_discovery import (
    BraveSearchProvider,
    SearchResult,
    normalize_result,
)
from quant_recruiting.resource_intelligence import (
    ResourceCandidate,
    infer_resource_type,
    normalize_resource,
)


def test_search_result_normalization_and_platform_dedupe() -> None:
    result = normalize_result(
        SearchResult("HTTPS://Example.com/article/?utm_source=test#top", title="Article")
    )
    assert result.url == "https://example.com/article"
    assert result.source_type_guess == "other"


def test_brave_provider_normalizes_mocked_api_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "secret"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://example.test/jobs",
                            "title": "Jobs",
                            "description": "Open roles",
                        }
                    ]
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        results = BraveSearchProvider("secret", "https://search.test", client=client).search(
            "Example jobs", limit=3
        )
    finally:
        client.close()
    assert results[0].provider == "brave"
    assert results[0].rank == 1


def test_pdf_normalization_preserves_page_markers() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    stream = BytesIO()
    writer.write(stream)
    fetched = FetchedSource(
        DiscoveredSource("file:///tmp/report.pdf", "report"),
        stream.getvalue(),
        "application/pdf",
        200,
        __import__("datetime").datetime.now(),
    )
    normalized = SourceCollector().normalize(fetched)
    assert normalized.document_type == "pdf"
    assert "<!-- page: 1 -->" in normalized.content


def test_public_discussion_and_transcript_normalization() -> None:
    normalized = normalize_reddit_payload(
        {
            "post": {"title": "Interview", "selftext": "They asked Bayes."},
            "comments": [{"body": "Useful", "score": 2}],
        },
        max_comments=1,
    )
    assert normalized["claim_type_default"] == "anecdote"
    assert len(normalized["comments"]) == 1
    assert youtube_video_id("https://www.youtube.com/watch?v=abc123") == "abc123"
    assert "## 00:00:04" in normalize_transcript([{"start": 4.2, "text": "Culture discussion"}])


def test_interview_extraction_and_topic_rules() -> None:
    document = SimpleNamespace(
        document_type="discussion",
        content=(
            "Interview report\n"
            "- What is a DCF?\n"
            "- Reverse a linked list?\n"
            "They asked Bayes theorem.\n"
            "There was a technical interview."
        ),
    )
    result = InterviewDocumentExtractor().extract(document)
    assert len([item for item in result.items if item.entity_type == "interview_question"]) >= 2
    assert "valuation" in topic_slugs("Explain a DCF")
    assert any(item.metadata.get("stage_slug") == "technical_interview" for item in result.items)


def test_resource_normalization_is_conservative() -> None:
    assert (
        infer_resource_type("Graph algorithms problem bank", "https://example.test")
        == "problem_bank"
    )
    normalized = normalize_resource(
        ResourceCandidate("  Book  ", "https://example.test/book/?utm_medium=x", "book", free=None)
    )
    assert normalized.title == "Book"
    assert normalized.free is None
