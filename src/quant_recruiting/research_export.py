from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.config import Settings
from quant_recruiting.db.models import (
    Company,
    InterviewQuestion,
    Job,
    RecruitingCycle,
    ResearchDocument,
    ResearchSource,
    Resource,
)


def _frontmatter(values: Mapping[str, object]) -> str:
    return (
        "---\n" + yaml.safe_dump(values, sort_keys=False, allow_unicode=True).strip() + "\n---\n\n"
    )


def export_company(session: Session, company: Company, settings: Settings) -> Path:
    root = settings.research_dir / company.slug
    sources_dir = root / "sources"
    manifests_dir = root / "manifests"
    firm_dir = root / "firm"
    recruiting_dir = root / "recruiting"
    interviews_dir = root / "interviews"
    recent_dir = root / "recent"
    resources_dir = root / "resources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)
    firm_dir.mkdir(parents=True, exist_ok=True)
    recruiting_dir.mkdir(parents=True, exist_ok=True)
    interviews_dir.mkdir(parents=True, exist_ok=True)
    recent_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)
    sources = list(
        session.scalars(
            select(ResearchSource)
            .where(ResearchSource.company_id == company.id)
            .order_by(ResearchSource.retrieved_at)
        )
    )
    jobs = list(
        session.scalars(select(Job).where(Job.company_id == company.id).order_by(Job.title))
    )
    cycles = list(
        session.scalars(
            select(RecruitingCycle)
            .where(RecruitingCycle.company_id == company.id)
            .order_by(RecruitingCycle.internship_cycle)
        )
    )
    manifest_sources: list[dict[str, object]] = []
    for source in sources:
        document = session.scalar(
            select(ResearchDocument)
            .where(ResearchDocument.source_id == source.id)
            .order_by(ResearchDocument.version.desc())
        )
        if document is None:
            continue
        output_path = sources_dir / f"{source.id}-v{document.version}.md"
        frontmatter = {
            "source_id": str(source.id),
            "company": company.name,
            "source_type": source.source_type,
            "title": document.title,
            "url": source.url,
            "published_at": source.published_at.isoformat() if source.published_at else None,
            "retrieved_at": source.retrieved_at.isoformat(),
            "source_quality": source.source_quality,
            "content_hash": document.content_hash,
        }
        output_path.write_text(_frontmatter(frontmatter) + document.content, encoding="utf-8")
        manifest_sources.append(
            {
                "source_id": str(source.id),
                "document_id": str(document.id),
                "path": str(output_path),
                "content_hash": document.content_hash,
            }
        )
    source_counts: dict[str, int] = {}
    quality_counts: dict[str, int] = {}
    for source in sources:
        source_counts[source.source_type] = source_counts.get(source.source_type, 0) + 1
        quality_counts[source.source_quality] = quality_counts.get(source.source_quality, 0) + 1
    lines = [
        f"# {company.name}",
        "",
        "## Company",
        "",
        f"- Slug: `{company.slug}`",
        f"- Domain: {company.primary_domain or '-'}",
        f"- Careers: {company.careers_url or '-'}",
        "",
        "## Jobs",
        "",
    ]
    if jobs:
        lines.extend(
            f"- [{job.title}]({job.job_url}) - {job.role_family} - {job.status}" for job in jobs
        )
    else:
        lines.append("- None recorded")
    lines += ["", "## Source counts", ""]
    if source_counts:
        lines.extend(
            f"- {source_type}: {count}" for source_type, count in sorted(source_counts.items())
        )
    else:
        lines.append("- None recorded")
    lines += ["", "## Source quality", ""]
    if quality_counts:
        lines.extend(f"- {quality}: {count}" for quality, count in sorted(quality_counts.items()))
    else:
        lines.append("- None recorded")
    lines += ["", "## Recruiting cycles", ""]
    if cycles:
        lines.extend(
            f"- {cycle.internship_cycle} / {cycle.role_family} / "
            f"{cycle.region or 'all regions'} - confidence {cycle.confidence:.2f}"
            for cycle in cycles
        )
    else:
        lines.append("- None recorded")
    lines += ["", "## Sources", ""]
    if manifest_sources:
        lines.extend(
            f"- [{item['source_id']}]({Path('sources') / Path(str(item['path'])).name})"
            for item in manifest_sources
        )
    else:
        lines.append("- None recorded")
    (root / "_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (manifests_dir / "sources.json").write_text(
        json.dumps(manifest_sources, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    jobs_manifest = [
        {
            "job_id": str(job.id),
            "title": job.title,
            "url": job.job_url,
            "role_family": job.role_family,
            "internship_cycle": job.internship_cycle,
            "status": job.status,
            "date_last_seen": job.date_last_seen.isoformat(),
            "content_hash": job.content_hash,
        }
        for job in jobs
    ]
    (manifests_dir / "jobs.json").write_text(
        json.dumps(jobs_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    categorized: dict[str, list[str]] = {}
    for item in manifest_sources:
        source = next(source for source in sources if str(source.id) == item["source_id"])
        category = str(source.metadata_.get("category", source.source_type))
        relative_source = Path("..") / "sources" / Path(str(item["path"])).name
        categorized.setdefault(category, []).append(
            f"- [{source.title or source.url}]({relative_source}) "
            f"— source `{source.id}` — quality `{source.source_quality}` — {source.url}"
        )
    category_targets = {
        "firm_overview": firm_dir / "official-pages.md",
        "careers": firm_dir / "careers.md",
        "internship": firm_dir / "careers.md",
        "research": firm_dir / "research.md",
        "technology": firm_dir / "technology.md",
        "culture": firm_dir / "official-pages.md",
        "people": firm_dir / "official-pages.md",
        "news": firm_dir / "official-pages.md",
        "publication": firm_dir / "research.md",
        "role_description": recruiting_dir / "jobs.md",
        "job_board": recruiting_dir / "jobs.md",
    }
    grouped_output: dict[Path, list[str]] = {}
    for category, entries in categorized.items():
        grouped_output.setdefault(
            category_targets.get(category, firm_dir / "official-pages.md"), []
        ).extend(entries)
    for path, entries in grouped_output.items():
        path.write_text(
            f"# {company.name} — {path.stem}\n\n" + "\n".join(sorted(entries)) + "\n",
            encoding="utf-8",
        )
    (recruiting_dir / "recruiting-cycle.md").write_text(
        "# Recruiting cycle records\n\n"
        + "\n".join(
            f"- `{cycle.id}` — {cycle.internship_cycle} / {cycle.role_family} / "
            f"{cycle.region or 'all regions'} — confidence {cycle.confidence:.2f}"
            for cycle in cycles
        )
        + "\n",
        encoding="utf-8",
    )
    questions = list(
        session.scalars(
            select(InterviewQuestion)
            .where(InterviewQuestion.company_id == company.id)
            .order_by(InterviewQuestion.created_at)
        )
    )
    question_lines = [f"# {company.name} — interview questions", "", "Evidence index", ""]
    for question in questions:
        question_lines.append(
            f"- {question.canonical_question} — source `{question.source_id}` — "
            f"confidence `{question.extraction_confidence or '-'}`"
        )
    (interviews_dir / "questions.md").write_text("\n".join(question_lines) + "\n", encoding="utf-8")
    (interviews_dir / "process-evidence.md").write_text(
        "# Interview process evidence\n\n"
        "Conflicting reports remain separate; this is not a definitive process.\n",
        encoding="utf-8",
    )
    (interviews_dir / "topics.md").write_text(
        "# Interview topics\n\nSee `interview_questions` skill mappings and "
        "the CLI topic report.\n",
        encoding="utf-8",
    )
    resources = list(session.scalars(select(Resource).order_by(Resource.title)))
    resource_manifest = [
        {
            "resource_id": str(item.id),
            "title": item.title,
            "url": item.url,
            "resource_type": item.resource_type,
            "metadata": item.metadata_,
        }
        for item in resources
    ]
    (manifests_dir / "interviews.json").write_text(
        json.dumps(
            [
                {
                    "question_id": str(item.id),
                    "question": item.canonical_question,
                    "source_id": str(item.source_id) if item.source_id else None,
                }
                for item in questions
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (manifests_dir / "resources.json").write_text(
        json.dumps(resource_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (resources_dir / "role-prep.md").write_text(
        "# Role preparation resources\n\n"
        + "\n".join(
            f"- [{item.title}]({item.url or ''}) — {item.resource_type}" for item in resources
        )
        + "\n",
        encoding="utf-8",
    )
    (recent_dir / "news.md").write_text(
        "# Recent news\n\nDeterministic index of company-linked news sources.\n",
        encoding="utf-8",
    )
    return root / "_index.md"
