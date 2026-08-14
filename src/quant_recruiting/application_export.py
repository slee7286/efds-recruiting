"""Deterministic, provenance-preserving application context export."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from quant_recruiting.config import Settings
from quant_recruiting.db.models import Application


def export_application(session: Session, application: Application, settings: Settings) -> Path:
    root = settings.local_data_dir / "applications" / str(application.id)
    root.mkdir(parents=True, exist_ok=True)
    job = application.job
    company = job.company
    (root / "job.md").write_text(
        f"# {job.title}\n\n- Job ID: `{job.id}`\n- Company: {company.name} (`{company.id}`)\n"
        f"- URL: {job.job_url}\n- Role family: {job.role_family}\n\n{job.description_text or ''}\n",
        encoding="utf-8",
    )
    (root / "company.md").write_text(
        f"# {company.name}\n\n- Company ID: `{company.id}`\n"
        f"- Domain: {company.primary_domain or ''}\n",
        encoding="utf-8",
    )
    for filename, heading, content in (
        (
            "recent-news.md",
            "Recent news",
            "Deterministic source index: review company-linked news sources in the database.",
        ),
        (
            "recruiting-intelligence.md",
            "Recruiting intelligence",
            "Review recruiting cycles, interview reports, stages, and questions "
            "linked to this company or role.",
        ),
        (
            "candidate-evidence.md",
            "Candidate evidence",
            "Private candidate evidence is referenced by approved workflows only; "
            "no unsupported achievements are generated.",
        ),
        (
            "resources.md",
            "Preparation resources",
            "Review resources mapped to the job's role family, skills, company, "
            "and interview stages.",
        ),
    ):
        (root / filename).write_text(f"# {heading}\n\n{content}\n", encoding="utf-8")
    manifest = {
        "application_id": str(application.id),
        "job_id": str(job.id),
        "company_id": str(company.id),
        "job_url": job.job_url,
        "company_slug": company.slug,
        "question_ids": [str(question.id) for question in application.questions],
        "cv_version_ids": [str(version.id) for version in application.cv_versions],
        "provenance_note": "This is a deterministic context export; factual claims "
        "must retain source IDs.",
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return root
