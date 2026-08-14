from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.config import Settings
from quant_recruiting.db.models import (
    AITask,
    Company,
    InterviewQuestion,
    Job,
    ResearchClaim,
    ResearchDocument,
    ResearchSource,
    Resource,
)
from quant_recruiting.research_export import export_company


def prepare_company_task(session: Session, company: Company, settings: Settings) -> AITask:
    export_company(session, company, settings)
    task = AITask(
        task_type="company_research_synthesis",
        entity_type="company",
        entity_id=company.id,
        status="ready",
    )
    session.add(task)
    session.flush()
    task_dir = settings.local_data_dir / "research-cache" / "ai" / str(task.id)
    output_dir = task_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    task_firm_dir = task_dir / "firm"
    task_recruiting_dir = task_dir / "recruiting"
    task_application_dir = task_dir / "application-intelligence"
    for directory in (task_firm_dir, task_recruiting_dir, task_application_dir):
        directory.mkdir(parents=True, exist_ok=True)
    sources = []
    for source in session.scalars(
        select(ResearchSource)
        .where(ResearchSource.company_id == company.id)
        .order_by(ResearchSource.retrieved_at)
    ):
        document = session.scalar(
            select(ResearchDocument)
            .where(ResearchDocument.source_id == source.id)
            .order_by(ResearchDocument.version.desc())
        )
        sources.append(
            {
                "source_id": str(source.id),
                "document_id": str(document.id) if document else None,
                "url": source.url,
                "path": document.markdown_path if document else source.normalized_path,
                "source_quality": source.source_quality,
                "content_hash": source.content_hash,
            }
        )
    manifest = {
        "task_id": str(task.id),
        "task_type": task.task_type,
        "company_id": str(company.id),
        "company_slug": company.slug,
        "sources": sources,
        "output_directory": str(output_dir),
    }
    (task_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (task_dir / "sources.json").write_text(
        json.dumps(sources, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    jobs = [
        {
            "job_id": str(job.id),
            "title": job.title,
            "url": job.job_url,
            "role_family": job.role_family,
        }
        for job in session.scalars(select(Job).where(Job.company_id == company.id))
    ]
    claims = [
        {
            "claim_id": str(claim.id),
            "claim": claim.claim,
            "claim_type": claim.claim_type,
            "confidence": claim.confidence,
            "source_id": str(claim.source_id),
        }
        for claim in session.scalars(
            select(ResearchClaim).where(ResearchClaim.company_id == company.id)
        )
    ]
    interview_evidence = [
        {
            "question_id": str(question.id),
            "question": question.canonical_question,
            "source_id": str(question.source_id) if question.source_id else None,
            "topics": question.metadata_.get("topics", []),
        }
        for question in session.scalars(
            select(InterviewQuestion).where(InterviewQuestion.company_id == company.id)
        )
    ]
    resources = [
        {
            "resource_id": str(resource.id),
            "title": resource.title,
            "url": resource.url,
            "resource_type": resource.resource_type,
        }
        for resource in session.scalars(select(Resource))
    ]
    for filename, payload in (
        ("jobs.json", jobs),
        ("claims.json", claims),
        ("interview-evidence.json", interview_evidence),
        ("resources.json", resources),
    ):
        (task_dir / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    instructions = f"""# Company research task: {company.name}

Read the sources listed in `manifest.json` and write outputs under `output/`.

- Do not invent unsupported facts.
- Every synthesized claim must retain one or more source IDs.
- Distinguish official facts, inferences, anecdotes, and opinions.
- Keep company-specific information separate from personal candidate evidence.
- Preserve temporal context.
- Prefer recent/current-cycle evidence for process claims and flag contradictions.
- Treat search results as candidates, not verified facts.
- Never invent interview stages, firm facts, or candidate achievements.

Expected output: a structured Markdown research note with a claim table containing claim type,
confidence, source IDs, and validity/observation dates.
"""
    (task_dir / "instructions.md").write_text(instructions, encoding="utf-8")
    context_files = {
        "firm/overview.md": "# Firm overview\n\nUse official source links from the manifest. "
        "Record only sourced facts.\n",
        "firm/culture.md": "# Culture\n\nUse culture, people, and values sources when available. "
        "Mark weak evidence explicitly.\n",
        "firm/technology.md": "# Technology\n\nUse technology, engineering, research, and "
        "publication sources.\n",
        "recruiting/internship-overview.md": "# Internship overview\n\nUse careers, internship, "
        "and job sources. Do not infer eligibility.\n",
        "recruiting/recruiting-cycle.md": "# Recruiting cycle\n\nUse dated recruiting evidence "
        "only. "
        "Do not invent stages.\n",
        "recruiting/interview-process.md": "# Interview process\n\nOnly include explicitly sourced "
        "interview-process evidence.\n",
        "application-intelligence/what-they-value.md": "# What they value\n\nSeparate sourced "
        "evidence from inference and cite source IDs.\n",
        "application-intelligence/why-firm.md": "# Why firm evidence\n\nPrepare evidence-backed "
        "prompts "
        "for later human review; do not write unsupported conclusions.\n",
    }
    for relative_path, content in context_files.items():
        (task_dir / relative_path).write_text(content, encoding="utf-8")
    task.input_manifest_path = str(task_dir / "manifest.json")
    task.output_manifest_path = str(output_dir / "manifest.json")
    session.flush()
    return task
