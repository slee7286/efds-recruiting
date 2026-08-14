from __future__ import annotations

from urllib.parse import urlsplit

from quant_recruiting.utils import normalize_text

CAREER_TERMS = {
    "career",
    "careers",
    "job",
    "jobs",
    "student",
    "students",
    "graduate",
    "graduates",
    "intern",
    "internship",
    "quant",
    "quantitative",
    "research",
    "researcher",
    "trading",
    "trader",
    "engineering",
    "technology",
    "machine-learning",
    "data",
    "people",
    "culture",
    "news",
    "insights",
    "publications",
    "papers",
    "events",
    "university",
    "campus",
}
CATEGORY_TERMS = {
    "careers": {"career", "careers", "job", "jobs", "join", "open-roles"},
    "internship": {"intern", "internship", "student", "graduate", "campus", "university"},
    "role_description": {"job", "jobs", "role", "position", "opportunity"},
    "culture": {"culture", "people", "life", "values", "team"},
    "technology": {"technology", "engineering", "software", "machine-learning", "data"},
    "research": {"research", "quantitative", "quant"},
    "news": {"news", "insights", "events"},
    "publication": {"publication", "publications", "papers", "report"},
}


def _terms(value: str) -> set[str]:
    text = normalize_text(value.replace("_", "-")).replace("/", " ")
    return {part for part in text.replace("-", " ").split() if part}


def classify_research_category(url: str, title: str = "", anchor: str = "") -> tuple[str, float]:
    values = _terms(url) | _terms(title) | _terms(anchor)
    scores = {
        category: len(values & {_part for term in terms for _part in _terms(term)})
        for category, terms in CATEGORY_TERMS.items()
    }
    category, count = max(scores.items(), key=lambda pair: pair[1], default=("other", 0))
    return (category if count else "other", min(1.0, 0.4 + count * 0.12) if count else 0.1)


def score_url(
    url: str, title: str = "", anchor: str = "", domain_type: str = ""
) -> tuple[float, list[str]]:
    parsed = urlsplit(url)
    values = _terms(parsed.path) | _terms(title) | _terms(anchor)
    reasons: list[str] = []
    hits = values & CAREER_TERMS
    score = min(0.72, len(hits) * 0.12)
    if hits:
        reasons.append("contains: " + ", ".join(sorted(hits)))
    if domain_type == "careers":
        score += 0.25
        reasons.append("careers domain")
    elif domain_type in {"research", "technology"}:
        score += 0.12
        reasons.append(f"{domain_type} domain")
    if title:
        title_hits = _terms(title) & CAREER_TERMS
        if title_hits:
            score += 0.08
            reasons.append("relevant page title")
    return min(1.0, round(score, 3)), reasons or ["public internal link"]
