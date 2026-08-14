"""Interactive-AI task preparation, validation, import, and quality checks.

This module deliberately stops at a filesystem handoff. It never calls an LLM.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.ai_contracts import (
    ApplicationAnalysisOutput,
    CandidateFirmMatchOutput,
    CompanySynthesisOutput,
    CoverLetterOutput,
    CVTailoringOutput,
    WrittenAnswersOutput,
    contract_for,
)
from quant_recruiting.config import Settings
from quant_recruiting.db.models import (
    AIPromptVersion,
    AITask,
    AITaskOutput,
    AITaskRun,
    Application,
    ApplicationAnswer,
    ApplicationArgument,
    ApplicationArgumentEvidence,
    ApplicationArgumentSource,
    ApplicationGap,
    ApplicationQuestion,
    ApplicationRequirement,
    ApplicationRequirementEvidence,
    CandidateEvidence,
    CandidateFirmMatch,
    Company,
    CVBullet,
    CVBulletEvidence,
    CVVersion,
    FirmIntelligenceItem,
    FirmIntelligenceSource,
    Job,
    ResearchClaim,
    ResearchSource,
    Resource,
)

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017 - Python 3.10 compatibility

TASK_SCHEMAS = {
    "company_synthesis": "company_synthesis_v1",
    "company_research_synthesis": "company_synthesis_v1",
    "candidate_firm_match": "candidate_firm_match_v1",
    "application_analysis": "application_analysis_v1",
    "cv_tailoring": "cv_tailoring_v1",
    "written_answers": "written_answers_v1",
    "cover_letter": "cover_letter_v1",
    "interview_prep": "interview_prep_v1",
    "why_firm": "why_firm_v1",
}


def _json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def _source_rows(session: Session, company_id: UUID, limit: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(ResearchSource)
        .where(ResearchSource.company_id == company_id)
        .order_by(ResearchSource.source_quality, ResearchSource.retrieved_at.desc())
        .limit(limit)
    )
    return [
        {
            "source_id": str(row.id),
            "url": row.url,
            "canonical_url": row.canonical_url,
            "source_type": row.source_type,
            "title": row.title,
            "source_quality": row.source_quality,
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "retrieved_at": row.retrieved_at.isoformat(),
            "normalized_path": row.normalized_path,
        }
        for row in rows
    ]


def _candidate_rows(session: Session, limit: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(CandidateEvidence)
        .where(CandidateEvidence.approved_for_application.is_(True))
        .order_by(CandidateEvidence.updated_at.desc())
        .limit(limit)
    )
    return [
        {
            "evidence_id": str(row.id),
            "experience_id": str(row.experience_id) if row.experience_id else None,
            "evidence_type": row.evidence_type,
            "statement": row.statement,
            "confidence": row.confidence,
            "evidence_quality": row.evidence_quality,
        }
        for row in rows
    ]


def _company_inputs(session: Session, company: Company, limit: int) -> dict[str, Any]:
    jobs = session.scalars(select(Job).where(Job.company_id == company.id).limit(limit))
    claims = session.scalars(
        select(ResearchClaim).where(ResearchClaim.company_id == company.id).limit(limit)
    )
    resources = session.scalars(select(Resource).limit(limit))
    return {
        "company.json": {
            "company_id": str(company.id),
            "slug": company.slug,
            "name": company.name,
            "description": company.description,
            "primary_domain": company.primary_domain,
        },
        "jobs.json": [
            {
                "job_id": str(job.id),
                "title": job.title,
                "url": job.job_url,
                "role_family": job.role_family,
                "description": job.description_text,
                "requirements": job.requirements_text,
            }
            for job in jobs
        ],
        "sources.json": _source_rows(session, company.id, limit),
        "claims.json": [
            {
                "claim_id": str(claim.id),
                "claim": claim.claim,
                "claim_type": claim.claim_type,
                "confidence": claim.confidence,
                "source_id": str(claim.source_id),
            }
            for claim in claims
        ],
        "resources.json": [
            {
                "resource_id": str(resource.id),
                "title": resource.title,
                "url": resource.url,
                "resource_type": resource.resource_type,
            }
            for resource in resources
        ],
    }


def _application_inputs(session: Session, application: Application, limit: int) -> dict[str, Any]:
    job = application.job
    company = job.company
    inputs = _company_inputs(session, company, limit)
    inputs["job.json"] = {
        "job_id": str(job.id),
        "title": job.title,
        "url": job.job_url,
        "role_family": job.role_family,
        "role_family_id": str(job.role_family_id) if job.role_family_id else None,
        "description": job.description_text,
        "requirements": job.requirements_text,
    }
    inputs["application.json"] = {
        "application_id": str(application.id),
        "company_id": str(company.id),
        "job_id": str(job.id),
        "question_ids": [str(question.id) for question in application.questions],
        "cv_version_ids": [str(version.id) for version in application.cv_versions],
    }
    inputs["candidate-evidence.json"] = _candidate_rows(session, limit)
    inputs["application-questions.json"] = [
        {
            "application_question_id": str(question.id),
            "question": question.question_text,
            "category": question.category,
            "max_words": question.max_words,
            "max_characters": question.max_characters,
            "required": question.required,
        }
        for question in application.questions
    ]
    return inputs


def prepare_task(
    session: Session,
    *,
    task_type: str,
    entity_type: str,
    entity_id: UUID,
    settings: Settings,
    full: bool = False,
) -> AITask:
    if task_type not in TASK_SCHEMAS:
        raise ValueError(f"unsupported V5 task type: {task_type}")
    company: Company | None
    application: Application | None = None
    if entity_type == "company":
        company = session.get(Company, entity_id)
    elif entity_type == "application":
        application = session.get(Application, entity_id)
        company = application.job.company if application else None
    else:
        company = None
    if company is None:
        raise LookupError(f"entity not found for {entity_type}: {entity_id}")
    if entity_type == "application" and application is None:
        raise LookupError(f"application not found: {entity_id}")
    limit = 500 if full else 40
    task = AITask(
        task_type=task_type,
        entity_type=entity_type,
        entity_id=entity_id,
        status="ready",
        prompt_version="v1",
        expected_output_schema=TASK_SCHEMAS[task_type],
        validation_status="pending",
        approval_status="draft",
    )
    prompt_record = session.scalar(
        select(AIPromptVersion).where(
            AIPromptVersion.task_type == task_type,
            AIPromptVersion.version == "v1",
        )
    )
    if prompt_record is None:
        session.add(
            AIPromptVersion(
                task_type=task_type,
                version="v1",
                template_path=f"prompts/{TASK_SCHEMAS[task_type]}.md",
                schema_version="v1",
            )
        )
    session.add(task)
    session.flush()
    task_dir = (
        settings.local_data_dir / "applications" / str(entity_id) / "ai" / str(task.id)
        if settings.storage_mode == "local_first"
        else settings.data_dir / "ai_queue" / str(task.id)
    )
    input_dir = task_dir / "input"
    output_dir = task_dir / "output"
    validation_dir = task_dir / "validation"
    for directory in (input_dir, output_dir, validation_dir):
        directory.mkdir(parents=True, exist_ok=True)
    if entity_type == "company":
        inputs = _company_inputs(session, company, limit)
    else:
        if application is None:
            raise LookupError(f"application not found: {entity_id}")
        inputs = _application_inputs(session, application, limit)
    if task_type == "candidate_firm_match":
        inputs["firm-intelligence.json"] = [
            {
                "intelligence_id": str(item.id),
                "item_type": item.item_type,
                "title": item.title,
                "statement": item.statement,
                "confidence": item.confidence,
                "source_ids": [str(link.source_id) for link in item.sources],
            }
            for item in session.scalars(
                select(FirmIntelligenceItem).where(FirmIntelligenceItem.company_id == company.id)
            )
        ]
        inputs["candidate-evidence.json"] = _candidate_rows(session, limit)
    for filename, payload in inputs.items():
        _json(input_dir / filename, payload)
    prompt_path = Path("prompts") / f"{TASK_SCHEMAS[task_type]}.md"
    prompt = (
        prompt_path.read_text(encoding="utf-8")
        if prompt_path.exists()
        else "Follow the JSON schema and cite provenance IDs."
    )
    instructions = f"""# Interactive AI task: {task.task_type}

Task ID: `{task.id}`
Schema: `{task.expected_output_schema}`

Read the input files in `input/` and return only valid JSON matching the schema. Save it as
`output/result.json`; do not edit database files.

{prompt}

The local workflow is: prepare → interactive human/AI session → save result.json →
`recruiting ai validate {task.id}` → `recruiting ai import {task.id}` → human review.
No output is approved automatically.
"""
    (task_dir / "instructions.md").write_text(instructions, encoding="utf-8")
    _json(
        task_dir / "manifest.json",
        {
            "task_id": str(task.id),
            "task_type": task.task_type,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "company_id": str(company.id),
            "prompt_version": task.prompt_version,
            "schema_version": task.expected_output_schema,
            "input_directory": "input",
            "output_path": "output/result.json",
            "validation_path": "validation/validation.json",
            "approved_evidence_only": True,
        },
    )
    if not (output_dir / "result.json").exists():
        _json(output_dir / "result.json", {})
    _json(
        validation_dir / "validation.json",
        {"status": "pending", "task_id": str(task.id), "errors": []},
    )
    task.input_manifest_path = str(task_dir / "manifest.json")
    task.output_manifest_path = str(output_dir / "result.json")
    session.flush()
    return task


def _ids_exist(session: Session, model: Any, ids: list[UUID]) -> bool:
    if not ids:
        return True
    return len(session.scalars(select(model.id).where(model.id.in_(ids))).all()) == len(set(ids))


def _approved_evidence(session: Session, ids: list[UUID]) -> bool:
    if not ids:
        return True
    rows = session.scalars(
        select(CandidateEvidence).where(
            CandidateEvidence.id.in_(ids), CandidateEvidence.approved_for_application.is_(True)
        )
    ).all()
    return len(rows) == len(set(ids))


def _company_id_for_task(session: Session, task: AITask) -> UUID | None:
    if task.entity_type == "company":
        return task.entity_id
    if task.entity_type == "application":
        application = session.get(Application, task.entity_id)
        return application.job.company_id if application else None
    return None


def _sources_for_company(session: Session, company_id: UUID | None, ids: list[UUID]) -> bool:
    if not ids:
        return True
    query = select(ResearchSource).where(ResearchSource.id.in_(ids))
    rows = session.scalars(query).all()
    return len(rows) == len(set(ids)) and all(row.company_id in (company_id, None) for row in rows)


def _has_duplicates(ids: list[UUID]) -> bool:
    return len(ids) != len(set(ids))


def validate_task(session: Session, task_id: UUID, settings: Settings) -> dict[str, Any]:
    task = session.get(AITask, task_id)
    if task is None or not task.output_manifest_path:
        raise LookupError(f"AI task output not found: {task_id}")
    path = Path(task.output_manifest_path)
    errors: list[str] = []
    company_id = _company_id_for_task(session, task)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        contract = contract_for(task.task_type).model_validate(payload)
        if contract.task_id != task.id:
            errors.append("task_id does not match the task being validated")
        if contract.schema_version != "v1":
            errors.append("unsupported schema_version")
        if isinstance(contract, CandidateFirmMatchOutput):
            for match in contract.matches:
                if _has_duplicates(match.candidate_evidence_ids + match.source_ids):
                    errors.append("match contains duplicate provenance IDs")
                if not _ids_exist(session, FirmIntelligenceItem, [match.firm_intelligence_id]):
                    errors.append(f"unknown firm intelligence ID: {match.firm_intelligence_id}")
                if not _approved_evidence(session, match.candidate_evidence_ids):
                    errors.append("match references missing or unapproved candidate evidence")
                if not _sources_for_company(session, company_id, match.source_ids):
                    errors.append("match references unknown source")
        if isinstance(contract, CompanySynthesisOutput):
            statements = (
                contract.themes
                + contract.values
                + contract.teams
                + contract.programs
                + contract.technology_themes
                + contract.business_themes
                + contract.recruiting_themes
                + contract.talking_points
            )
            source_ids = [
                source_id for statement in statements for source_id in statement.source_ids
            ]
            if _has_duplicates(source_ids):
                errors.append("company synthesis contains duplicate source IDs")
            if not _sources_for_company(session, company_id, source_ids):
                errors.append("company synthesis references an unknown source")
        if isinstance(contract, ApplicationAnalysisOutput):
            evidence_ids = [
                evidence_id
                for requirement in contract.requirements
                for evidence_id in requirement.candidate_evidence_ids
            ]
            evidence_ids += [
                evidence_id
                for argument in contract.arguments
                for evidence_id in argument.candidate_evidence_ids
            ]
            if _has_duplicates(evidence_ids):
                errors.append("application analysis contains duplicate evidence IDs")
            if not _approved_evidence(session, evidence_ids):
                errors.append(
                    "application analysis references missing or unapproved candidate evidence"
                )
            for argument in contract.arguments:
                if _has_duplicates(argument.candidate_evidence_ids + argument.source_ids):
                    errors.append("application argument contains duplicate provenance IDs")
                if argument.specificity_score >= 4 and not argument.source_ids:
                    errors.append("specificity >= 4 requires company source IDs")
                if argument.specificity_score == 5 and not argument.candidate_evidence_ids:
                    errors.append("specificity 5 requires candidate evidence IDs")
                if not _sources_for_company(session, company_id, argument.source_ids):
                    errors.append("application argument references an invalid company source")
        if isinstance(contract, CVTailoringOutput):
            evidence_ids = [
                evidence_id
                for bullet in contract.bullets
                for evidence_id in bullet.candidate_evidence_ids
            ]
            if any(_has_duplicates(bullet.candidate_evidence_ids) for bullet in contract.bullets):
                errors.append("CV bullet contains duplicate evidence IDs")
            if not _approved_evidence(session, evidence_ids):
                errors.append("CV tailoring references missing or unapproved candidate evidence")
        if isinstance(contract, WrittenAnswersOutput):
            application = session.get(Application, task.entity_id)
            question_ids = [answer.application_question_id for answer in contract.answers]
            if application is None or not _ids_exist(session, ApplicationQuestion, question_ids):
                errors.append("written answers reference unknown application questions")
            else:
                questions = {question.id: question for question in application.questions}
                for answer in contract.answers:
                    if _has_duplicates(answer.candidate_evidence_ids + answer.company_source_ids):
                        errors.append("written answer contains duplicate provenance IDs")
                    question = questions.get(answer.application_question_id)
                    if question is None:
                        errors.append("written answer question is outside the application")
                        continue
                    if question.max_words and len(answer.answer.split()) > question.max_words:
                        errors.append(f"answer exceeds word limit for question {question.id}")
                    if question.max_characters and len(answer.answer) > question.max_characters:
                        errors.append(f"answer exceeds character limit for question {question.id}")
                if not _approved_evidence(
                    session,
                    [
                        evidence_id
                        for answer in contract.answers
                        for evidence_id in answer.candidate_evidence_ids
                    ],
                ):
                    errors.append(
                        "written answers reference missing or unapproved candidate evidence"
                    )
                if not _sources_for_company(
                    session,
                    company_id,
                    [
                        source_id
                        for answer in contract.answers
                        for source_id in answer.company_source_ids
                    ],
                ):
                    errors.append("written answers reference an invalid company source")
        if isinstance(contract, CoverLetterOutput):
            if not _approved_evidence(
                session,
                [
                    evidence_id
                    for paragraph in contract.paragraphs
                    for evidence_id in paragraph.candidate_evidence_ids
                ],
            ):
                errors.append("cover letter references missing or unapproved candidate evidence")
    except (json.JSONDecodeError, ValueError) as exc:
        errors.append(str(exc))
    result = {
        "task_id": str(task.id),
        "status": "valid" if not errors else "invalid",
        "errors": errors,
    }
    if task.input_manifest_path is None or task.output_manifest_path is None:
        raise LookupError(f"AI task has no filesystem manifest: {task.id}")
    validation_path = Path(task.input_manifest_path).parent / "validation" / "validation.json"
    _json(validation_path, result)
    task.validation_status = "valid" if not errors else "invalid"
    task.status = "completed" if not errors else "failed"
    task.completed_at = datetime.now(UTC)  # noqa: UP017 - Python 3.10 compatibility
    session.add(
        AITaskRun(
            task_id=task.id,
            run_number=_next_run_number(session, task.id),
            output_path=str(path),
            validation_path=str(validation_path),
            status=result["status"],
        )
    )
    session.flush()
    return result


def _next_run_number(session: Session, task_id: UUID) -> int:
    values = session.scalars(select(AITaskRun.run_number).where(AITaskRun.task_id == task_id)).all()
    return max(values, default=0) + 1


def import_task(session: Session, task_id: UUID, settings: Settings) -> int:
    task = session.get(AITask, task_id)
    if task is None or task.validation_status != "valid":
        raise ValueError("task must pass validation before import")
    if task.output_manifest_path is None:
        raise LookupError(f"AI task has no output: {task.id}")
    payload = json.loads(Path(task.output_manifest_path).read_text(encoding="utf-8"))
    contract = contract_for(task.task_type).model_validate(payload)
    created = 0
    if isinstance(contract, CompanySynthesisOutput):
        company = session.get(Company, task.entity_id)
        if company is None:
            raise LookupError(f"company not found: {task.entity_id}")
        groups = (
            ("theme", contract.themes),
            ("value", contract.values),
            ("team", contract.teams),
            ("program", contract.programs),
            ("theme", contract.technology_themes),
            ("theme", contract.business_themes),
            ("theme", contract.recruiting_themes),
            ("talking_point", contract.talking_points),
        )
        for item_type, statements in groups:
            for statement in statements:
                item = FirmIntelligenceItem(
                    company_id=company.id,
                    item_type=item_type,
                    title=statement.title,
                    statement=statement.summary,
                    confidence=statement.confidence,
                    metadata_={
                        "ai_task_id": str(task.id),
                        "claim_type": statement.claim_type,
                        "status": "draft",
                    },
                )
                session.add(item)
                session.flush()
                for source_id in statement.source_ids:
                    session.add(FirmIntelligenceSource(item_id=item.id, source_id=source_id))
                created += 1
    elif isinstance(contract, CandidateFirmMatchOutput):
        company_id = task.entity_id
        if contract.matches:
            intelligence_item = session.get(
                FirmIntelligenceItem, contract.matches[0].firm_intelligence_id
            )
            if intelligence_item is None:
                raise LookupError("matched firm-intelligence item not found")
            company_id = intelligence_item.company_id
        for match in contract.matches:
            for evidence_id in match.candidate_evidence_ids:
                session.add(
                    CandidateFirmMatch(
                        company_id=company_id,
                        evidence_id=evidence_id,
                        intelligence_item_id=match.firm_intelligence_id,
                        relevance_score=match.relevance_score,
                        rationale=match.rationale,
                        method="interactive_ai",
                        approved=False,
                        metadata_={
                            "ai_task_id": str(task.id),
                            "source_ids": [str(value) for value in match.source_ids],
                            "status": "draft",
                        },
                    )
                )
                created += 1
    elif isinstance(contract, ApplicationAnalysisOutput):
        for requirement in contract.requirements:
            requirement_row = ApplicationRequirement(
                application_id=task.entity_id,
                requirement=requirement.requirement,
                classification=requirement.classification,
                match_strength=requirement.match_strength,
                ai_task_id=task.id,
            )
            session.add(requirement_row)
            session.flush()
            for evidence_id in requirement.candidate_evidence_ids:
                session.add(
                    ApplicationRequirementEvidence(
                        requirement_id=requirement_row.id, evidence_id=evidence_id
                    )
                )
            created += 1
        for gap in contract.gaps:
            session.add(
                ApplicationGap(
                    application_id=task.entity_id,
                    requirement=gap.requirement,
                    gap_type=gap.gap_type,
                    severity=gap.severity,
                    evidence=gap.evidence,
                    resolvable=gap.resolvable,
                    suggested_preparation=gap.suggested_preparation,
                    ai_task_id=task.id,
                )
            )
            created += 1
        application = session.get(Application, task.entity_id)
        if application is None:
            raise LookupError(f"application not found: {task.entity_id}")
        for argument in contract.arguments:
            argument_row = ApplicationArgument(
                company_id=application.job.company_id,
                role_family_id=application.job.role_family_id,
                team_or_program=argument.team_or_program,
                argument_type=argument.argument_type,
                summary=argument.summary,
                specificity_score=argument.specificity_score,
                strength_score=argument.strength_score,
                ai_task_id=task.id,
                metadata_={"status": "draft"},
            )
            session.add(argument_row)
            session.flush()
            for evidence_id in argument.candidate_evidence_ids:
                session.add(
                    ApplicationArgumentEvidence(
                        argument_id=argument_row.id, evidence_id=evidence_id
                    )
                )
            for source_id in argument.source_ids:
                session.add(
                    ApplicationArgumentSource(argument_id=argument_row.id, source_id=source_id)
                )
            created += 1
    elif isinstance(contract, CVTailoringOutput):
        application = session.get(Application, task.entity_id)
        if application is None:
            raise LookupError(f"application not found: {task.entity_id}")
        cv_version = session.scalar(
            select(CVVersion)
            .where(CVVersion.application_id == application.id)
            .order_by(CVVersion.created_at.desc())
        )
        if cv_version is None:
            raise ValueError("CV tailoring import requires an existing CV version")
        for order_index, bullet in enumerate(contract.bullets):
            cv_bullet = CVBullet(
                cv_version_id=cv_version.id,
                experience_id=bullet.experience_id,
                text=bullet.draft,
                order_index=order_index,
                generated_by_task=task.id,
            )
            session.add(cv_bullet)
            session.flush()
            for evidence_id in bullet.candidate_evidence_ids:
                session.add(CVBulletEvidence(bullet_id=cv_bullet.id, evidence_id=evidence_id))
            created += 1
    elif isinstance(contract, WrittenAnswersOutput):
        for answer in contract.answers:
            latest = session.scalar(
                select(ApplicationAnswer.version)
                .where(ApplicationAnswer.application_question_id == answer.application_question_id)
                .order_by(ApplicationAnswer.version.desc())
            )
            session.add(
                ApplicationAnswer(
                    application_question_id=answer.application_question_id,
                    answer_text=answer.answer,
                    version=(latest or 0) + 1,
                    approved=False,
                    specificity_score=answer.specificity_score,
                    generated_at=datetime.now(UTC),  # noqa: UP017 - Python 3.10 compatibility
                    metadata_={
                        "ai_task_id": str(task.id),
                        "candidate_evidence_ids": [
                            str(value) for value in answer.candidate_evidence_ids
                        ],
                        "company_source_ids": [str(value) for value in answer.company_source_ids],
                        "status": "draft",
                    },
                )
            )
            created += 1
    latest_run = session.scalar(
        select(AITaskRun).where(AITaskRun.task_id == task.id).order_by(AITaskRun.run_number.desc())
    )
    if latest_run is None:
        raise ValueError("validated task has no recorded run")
    output = AITaskOutput(
        task_id=task.id,
        run_id=latest_run.id,
        schema_version="v1",
        raw_path=task.output_manifest_path,
        validation_status="imported",
        imported_at=datetime.now(UTC),  # noqa: UP017 - Python 3.10 compatibility
        metadata_={"created": created},
    )
    session.add(output)
    task.metadata_["imported"] = True
    session.flush()
    return created


def approve_task(session: Session, task_id: UUID, approved_by: str) -> AITask:
    task = session.get(AITask, task_id)
    if task is None:
        raise LookupError(f"unknown AI task: {task_id}")
    if task.validation_status != "valid":
        raise ValueError("only a valid task can be approved")
    task.approval_status = "approved"
    task.approved_at = datetime.now(UTC)  # noqa: UP017 - Python 3.10 compatibility
    task.approved_by = approved_by
    session.flush()
    return task


def readiness(session: Session, application: Application) -> dict[str, Any]:
    company = application.job.company
    source_count = session.scalar(
        select(ResearchSource.id).where(ResearchSource.company_id == company.id).limit(1)
    )
    evidence_count = session.scalar(
        select(CandidateEvidence.id)
        .where(CandidateEvidence.approved_for_application.is_(True))
        .limit(1)
    )
    return {
        "application_id": str(application.id),
        "job_description": bool(application.job.description_text),
        "official_or_company_sources": bool(source_count),
        "approved_candidate_evidence": bool(evidence_count),
        "questions": len(application.questions),
        "ready": bool(application.job.description_text and source_count and evidence_count),
        "gaps": [] if source_count and evidence_count else ["insufficient approved context"],
    }


def quality_report(session: Session, application: Application) -> dict[str, Any]:
    ready = readiness(session, application)
    source_count = session.scalar(
        select(ResearchSource.id)
        .where(ResearchSource.company_id == application.job.company_id)
        .limit(1)
    )
    requirement_count = session.scalar(
        select(ApplicationRequirement.id)
        .where(ApplicationRequirement.application_id == application.id)
        .limit(1)
    )
    return {
        **ready,
        "research_coverage": 100 if source_count else 0,
        "requirement_analysis": 100 if requirement_count else 0,
        "question_count": len(application.questions),
        "overall": "READY FOR HUMAN REVIEW" if ready["ready"] else "RESEARCH OR EVIDENCE NEEDED",
    }
