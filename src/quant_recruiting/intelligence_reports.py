"""Deterministic interview, coverage, and preparation reports."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.db.models import (
    Company,
    InterviewQuestion,
    InterviewQuestionSkill,
    InterviewReport,
    Resource,
    ResourceRoleFamily,
    Skill,
)

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017


def topic_frequency(
    session: Session,
    company: Company,
    *,
    role_family_id: UUID | None = None,
    cycle: str | None = None,
    stage_id: UUID | None = None,
    since: datetime | None = None,
) -> list[tuple[str, int]]:
    query = (
        select(Skill.name, InterviewQuestionSkill.question_id)
        .join(InterviewQuestionSkill, InterviewQuestionSkill.skill_id == Skill.id)
        .join(InterviewQuestion, InterviewQuestion.id == InterviewQuestionSkill.question_id)
        .where(InterviewQuestion.company_id == company.id)
    )
    if role_family_id:
        query = query.where(InterviewQuestion.role_family_id == role_family_id)
    if cycle:
        query = query.where(InterviewQuestion.recruiting_cycle == cycle)
    if stage_id:
        query = query.where(InterviewQuestion.stage_id == stage_id)
    if since:
        query = query.where(InterviewQuestion.created_at >= since)
    counts: Counter[str] = Counter()
    seen: set[tuple[str, Any]] = set()
    for name, question_id in session.execute(query):
        if (name, question_id) not in seen:
            counts[name] += 1
            seen.add((name, question_id))
    return counts.most_common()


def process_evidence(session: Session, company: Company) -> list[dict[str, Any]]:
    reports = list(
        session.scalars(select(InterviewReport).where(InterviewReport.company_id == company.id))
    )
    return [
        {
            "report_id": str(report.id),
            "role_family": report.role_family,
            "cycle": report.internship_cycle,
            "stage": report.stage,
            "source_id": str(report.source_id),
            "reliability": report.reliability,
            "summary": report.summary,
        }
        for report in reports
    ]


def coverage_report(session: Session, company: Company) -> dict[str, Any]:
    sources = list(company.sources)
    counts: Counter[str] = Counter()
    for source in sources:
        category = str(source.metadata_.get("category", source.source_type))
        counts[category] += 1
    required = {
        "firm_overview": "official firm overview",
        "careers": "official careers source",
        "technology": "technology/research source",
        "news": "recent news",
        "interview_process": "interview-process evidence",
        "candidate_experience": "candidate experience evidence",
        "preparation_resources": "preparation resources",
    }
    weak = [label for category, label in required.items() if counts[category] == 0]
    return {"counts": dict(counts), "weak_coverage": weak, "source_count": len(sources)}


def preparation_report(
    session: Session, company: Company, role_family_id: UUID | None = None
) -> dict[str, Any]:
    topics = topic_frequency(session, company, role_family_id=role_family_id)
    resources_query = select(Resource).join(
        ResourceRoleFamily, ResourceRoleFamily.resource_id == Resource.id
    )
    if role_family_id:
        resources_query = resources_query.where(ResourceRoleFamily.role_family_id == role_family_id)
    resources = list(session.scalars(resources_query))
    return {
        "company": company.name,
        "topics": topics,
        "resources": [
            {"title": item.title, "url": item.url, "type": item.resource_type} for item in resources
        ],
        "coverage_note": "Frequencies are within collected evidence, not interview probabilities.",
    }
