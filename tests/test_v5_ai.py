from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from quant_recruiting.ai_contracts import (
    ApplicationAnalysisOutput,
    CompanySynthesisOutput,
    CVTailoringOutput,
)
from quant_recruiting.db.base import Base


def test_v5_tables_and_approval_fields_are_present() -> None:
    expected = {
        "ai_prompt_versions",
        "ai_task_runs",
        "ai_task_outputs",
        "application_arguments",
        "application_argument_evidence",
        "application_argument_sources",
        "application_gaps",
        "application_requirements",
        "application_requirement_evidence",
        "cv_bullets",
        "cv_bullet_evidence",
        "candidate_stories",
        "candidate_story_evidence",
    }
    assert expected <= set(Base.metadata.tables)
    assert "approved_for_application" in Base.metadata.tables["candidate_evidence"].c
    assert "prompt_version" in Base.metadata.tables["ai_tasks"].c


def test_company_contract_requires_provenance_ids_only_as_references() -> None:
    task_id = uuid4()
    output = CompanySynthesisOutput(
        task_id=task_id,
        themes=[
            {
                "title": "Research culture",
                "summary": "The firm publishes research.",
                "claim_type": "fact",
                "source_ids": [uuid4()],
                "confidence": 0.9,
            }
        ],
    )
    assert output.task_id == task_id
    assert output.themes[0].confidence == 0.9


def test_contract_rejects_invalid_confidence_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CompanySynthesisOutput(
            task_id=uuid4(),
            themes=[
                {
                    "title": "Bad",
                    "summary": "Bad",
                    "claim_type": "fact",
                    "confidence": 1.2,
                    "unexpected": True,
                }
            ],
        )


def test_cv_bullet_requires_candidate_evidence() -> None:
    with pytest.raises(ValidationError):
        CVTailoringOutput(
            task_id=uuid4(),
            bullets=[
                {
                    "draft": "Unsupported achievement",
                    "reason": "Looks good",
                    "candidate_evidence_ids": [],
                }
            ],
        )


def test_application_contract_carries_specificity_and_requirements() -> None:
    output = ApplicationAnalysisOutput(
        task_id=uuid4(),
        requirements=[
            {
                "requirement": "Python",
                "candidate_evidence_ids": [uuid4()],
                "match_strength": 0.8,
                "classification": "strong_match",
            }
        ],
        arguments=[
            {
                "argument_type": "why_company",
                "summary": "A sourced reason.",
                "source_ids": [uuid4()],
                "candidate_evidence_ids": [uuid4()],
                "specificity_score": 5,
                "strength_score": 0.8,
            }
        ],
    )
    assert output.requirements[0].classification == "strong_match"
    assert output.arguments[0].specificity_score == 5


def test_prompt_templates_are_versioned() -> None:
    prompt_dir = Path("prompts")
    names = {path.name for path in prompt_dir.glob("*_v1.md")}
    assert {
        "company_synthesis_v1.md",
        "application_analysis_v1.md",
        "candidate_firm_match_v1.md",
        "cv_tailoring_v1.md",
        "written_answers_v1.md",
        "interview_prep_v1.md",
    } <= names
