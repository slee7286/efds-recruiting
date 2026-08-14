"""Deterministic extraction of recruiting and interview evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.db.models import (
    Company,
    InterviewQuestion,
    InterviewQuestionSkill,
    ResearchDocument,
    Skill,
    StructuredExtraction,
)
from quant_recruiting.utils import normalize_text, slugify_text

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017


@dataclass(frozen=True)
class ExtractionItem:
    extraction_type: str
    entity_type: str
    text: str
    confidence: float
    start: int | None = None
    end: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionResult:
    items: list[ExtractionItem]


class StructuredExtractor(Protocol):
    def supports(self, document: ResearchDocument) -> bool: ...

    def extract(self, document: ResearchDocument) -> ExtractionResult: ...


STAGE_RULES = {
    "online_assessment": ("online assessment", "oa", "coding assessment", "numerical test"),
    "phone_screen": ("phone screen", "recruiter screen", "phone interview"),
    "technical_interview": ("technical interview", "technical round", "coding interview"),
    "behavioural_interview": ("behavioural interview", "behavioral interview"),
    "case_interview": ("case interview", "case study", "market sizing"),
    "assessment_centre": ("assessment centre", "assessment center"),
    "superday": ("superday",),
    "final_round": ("final round", "final interview"),
}

TOPIC_RULES = {
    "valuation": ("dcf", "discounted cash flow", "valuation"),
    "algorithms": ("algorithm", "binary search", "graph", "dynamic programming"),
    "data-structures": ("data structure", "linked list", "hash table", "tree"),
    "probability": ("probability", "bayes", "expected value", "conditional probability"),
    "statistics": ("statistics", "regression", "hypothesis testing", "maximum likelihood"),
    "system-design": ("system design", "distributed system", "scalability"),
    "accounting": ("accounting", "income statement", "balance sheet", "cash flow"),
    "commercial-awareness": ("market awareness", "commercial awareness", "industry"),
}


class InterviewDocumentExtractor:
    def supports(self, document: ResearchDocument) -> bool:
        return document.document_type in {"web_page", "pdf", "transcript", "discussion"}

    def extract(self, document: ResearchDocument) -> ExtractionResult:
        items: list[ExtractionItem] = []
        for match in re.finditer(r"(?im)^\s*(?:[-*•]|\d+[.)])\s+(.+?\??)\s*$", document.content):
            text = match.group(1).strip()
            if "?" in text or re.match(r"(?:what|why|how|tell me|describe|walk me)\b", text, re.I):
                items.append(
                    ExtractionItem(
                        "interview_question",
                        "interview_question",
                        text,
                        0.82,
                        match.start(1),
                        match.end(1),
                    )
                )
        for match in re.finditer(
            r"(?im)(?:they asked|asked me|questions included)[:\s]+([^\n]+)", document.content
        ):
            text = match.group(1).strip()
            if len(text) > 8:
                items.append(
                    ExtractionItem(
                        "interview_question",
                        "interview_question",
                        text,
                        0.72,
                        match.start(1),
                        match.end(1),
                    )
                )
        lower = document.content.lower()
        for stage, patterns in STAGE_RULES.items():
            for pattern in patterns:
                start = lower.find(pattern)
                if start >= 0:
                    items.append(
                        ExtractionItem(
                            "interview_stage",
                            "interview_stage",
                            document.content[start : start + len(pattern)],
                            0.7,
                            start,
                            start + len(pattern),
                            {"stage_slug": stage},
                        )
                    )
                    break
        for event, patterns in {
            "applications_open": ("applications open", "applications opened"),
            "applications_close": ("applications close", "applications closed", "deadline"),
            "offer": ("offer", "offers made"),
        }.items():
            for pattern in patterns:
                event_match = re.search(re.escape(pattern), document.content, re.I)
                if event_match:
                    items.append(
                        ExtractionItem(
                            "recruiting_event",
                            "recruiting_event",
                            event_match.group(0),
                            0.55,
                            event_match.start(),
                            event_match.end(),
                            {"event_type": event},
                        )
                    )
                    break
        return ExtractionResult(items)


def topic_slugs(text: str) -> list[str]:
    lowered = text.lower()
    return [
        slug
        for slug, patterns in TOPIC_RULES.items()
        if any(pattern in lowered for pattern in patterns)
    ]


def persist_extraction(
    session: Session,
    document: ResearchDocument,
    result: ExtractionResult,
    *,
    company: Company | None = None,
    source_type: str = "extracted",
    role_family_id: UUID | None = None,
    recruiting_cycle: str | None = None,
) -> dict[str, int]:
    created = questions = stages = events = 0
    for item in result.items:
        exists = session.scalar(
            select(StructuredExtraction).where(
                StructuredExtraction.document_id == document.id,
                StructuredExtraction.extraction_type == item.extraction_type,
                StructuredExtraction.extracted_text == item.text,
            )
        )
        if exists is None:
            session.add(
                StructuredExtraction(
                    document_id=document.id,
                    extraction_type=item.extraction_type,
                    entity_type=item.entity_type,
                    extracted_text=item.text,
                    provenance_start=item.start,
                    provenance_end=item.end,
                    confidence=item.confidence,
                    method="deterministic_rules",
                    metadata_=item.metadata,
                )
            )
            created += 1
        if item.entity_type == "interview_question":
            normalized = normalize_text(item.text).strip(" ?.!:")
            question = session.scalar(
                select(InterviewQuestion).where(InterviewQuestion.normalized_question == normalized)
            )
            if question is None:
                question = InterviewQuestion(
                    canonical_question=item.text,
                    normalized_question=normalized,
                    source_type=source_type,
                    source_id=document.source_id,
                    company_id=company.id if company else None,
                    role_family_id=role_family_id,
                    recruiting_cycle=recruiting_cycle,
                    extraction_confidence=item.confidence,
                    original_text=item.text,
                    provenance_start=item.start,
                    provenance_end=item.end,
                    metadata_={
                        "extraction_method": "deterministic_rules",
                        "topics": topic_slugs(item.text),
                    },
                )
                session.add(question)
                session.flush()
                questions += 1
            for slug in topic_slugs(item.text):
                skill = session.scalar(select(Skill).where(Skill.slug == slugify_text(slug)))
                if (
                    skill
                    and session.get(
                        InterviewQuestionSkill, {"question_id": question.id, "skill_id": skill.id}
                    )
                    is None
                ):
                    session.add(
                        InterviewQuestionSkill(
                            question=question, skill=skill, strength=item.confidence
                        )
                    )
        elif item.entity_type == "interview_stage":
            stages += 1
        elif item.entity_type == "recruiting_event":
            events += 1
    session.flush()
    return {"extractions": created, "questions": questions, "stages": stages, "events": events}
