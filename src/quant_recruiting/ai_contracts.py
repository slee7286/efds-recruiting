"""Versioned, machine-checkable contracts for interactive AI handoffs."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ClaimKind = Literal["fact", "inference", "anecdote", "opinion"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    schema_version: str = "v1"


class CitedStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1)
    claim_type: ClaimKind
    source_ids: list[UUID] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class ThemeOutput(CitedStatement):
    pass


class CompanySynthesisOutput(ContractModel):
    summary: str = ""
    themes: list[ThemeOutput] = Field(default_factory=list)
    values: list[ThemeOutput] = Field(default_factory=list)
    teams: list[ThemeOutput] = Field(default_factory=list)
    programs: list[ThemeOutput] = Field(default_factory=list)
    technology_themes: list[ThemeOutput] = Field(default_factory=list)
    business_themes: list[ThemeOutput] = Field(default_factory=list)
    recruiting_themes: list[ThemeOutput] = Field(default_factory=list)
    talking_points: list[ThemeOutput] = Field(default_factory=list)


class MatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    firm_intelligence_id: UUID
    candidate_evidence_ids: list[UUID] = Field(min_length=1)
    relevance_score: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)
    source_ids: list[UUID] = Field(default_factory=list)


class CandidateFirmMatchOutput(ContractModel):
    matches: list[MatchOutput] = Field(default_factory=list)


class RequirementOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement: str = Field(min_length=1)
    candidate_evidence_ids: list[UUID] = Field(default_factory=list)
    match_strength: float = Field(ge=0, le=1)
    classification: Literal["strong_match", "partial_match", "gap", "unknown"] = "unknown"


class GapOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement: str = Field(min_length=1)
    gap_type: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    evidence: str | None = None
    resolvable: bool = False
    suggested_preparation: str | None = None


class ArgumentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    argument_type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    candidate_evidence_ids: list[UUID] = Field(default_factory=list)
    source_ids: list[UUID] = Field(default_factory=list)
    specificity_score: int = Field(ge=0, le=5)
    strength_score: float = Field(ge=0, le=1)
    team_or_program: str | None = None


class ApplicationAnalysisOutput(ContractModel):
    role_summary: str = ""
    requirements: list[RequirementOutput] = Field(default_factory=list)
    gaps: list[GapOutput] = Field(default_factory=list)
    arguments: list[ArgumentOutput] = Field(default_factory=list)
    cv_recommendations: list[str] = Field(default_factory=list)
    likely_interview_topics: list[str] = Field(default_factory=list)
    preparation_priorities: list[str] = Field(default_factory=list)


class CVBulletOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experience_id: UUID | None = None
    candidate_evidence_ids: list[UUID] = Field(min_length=1)
    draft: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class CVTailoringOutput(ContractModel):
    experience_order: list[UUID] = Field(default_factory=list)
    bullets: list[CVBulletOutput] = Field(default_factory=list)
    skills_order: list[str] = Field(default_factory=list)
    summary_recommendation: str | None = None


class AnswerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_question_id: UUID
    answer: str = Field(min_length=1)
    candidate_evidence_ids: list[UUID] = Field(default_factory=list)
    company_source_ids: list[UUID] = Field(default_factory=list)
    specificity_score: int = Field(ge=0, le=5)


class WrittenAnswersOutput(ContractModel):
    answers: list[AnswerOutput] = Field(default_factory=list)


class CoverLetterParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    candidate_evidence_ids: list[UUID] = Field(default_factory=list)
    company_source_ids: list[UUID] = Field(default_factory=list)
    argument_ids: list[UUID] = Field(default_factory=list)


class CoverLetterOutput(ContractModel):
    paragraphs: list[CoverLetterParagraph] = Field(default_factory=list)
    final_draft: str = ""


class InterviewPrepOutput(ContractModel):
    likely_stages: list[str] = Field(default_factory=list)
    topics_to_prepare: list[str] = Field(default_factory=list)
    priority_skills: list[UUID] = Field(default_factory=list)
    resource_ids: list[UUID] = Field(default_factory=list)
    firm_talking_points: list[UUID] = Field(default_factory=list)
    candidate_story_ids: list[UUID] = Field(default_factory=list)
    interviewer_questions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


CONTRACTS: dict[str, type[ContractModel]] = {
    "company_synthesis": CompanySynthesisOutput,
    "company_research_synthesis": CompanySynthesisOutput,
    "candidate_firm_match": CandidateFirmMatchOutput,
    "application_analysis": ApplicationAnalysisOutput,
    "cv_tailoring": CVTailoringOutput,
    "written_answers": WrittenAnswersOutput,
    "cover_letter": CoverLetterOutput,
    "interview_prep": InterviewPrepOutput,
    "why_firm": ApplicationAnalysisOutput,
}


def contract_for(task_type: str) -> type[ContractModel]:
    try:
        return CONTRACTS[task_type]
    except KeyError as exc:
        raise ValueError(f"No V5 contract registered for task type: {task_type}") from exc
