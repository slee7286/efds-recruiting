from __future__ import annotations

import importlib.util
import json
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from uuid import UUID

import httpx
import typer
import yaml
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_recruiting.ai_workflow import (
    approve_task,
    import_task,
    prepare_task,
    quality_report,
    readiness,
    validate_task,
)
from quant_recruiting.ai_workspace import (
    import_conversations,
    link_conversation,
    list_conversations,
    open_task,
    search_conversations,
    show_conversation,
)
from quant_recruiting.application_export import export_application
from quant_recruiting.artifacts import (
    application_readiness,
    approve_answer,
    approve_artifact,
    build_packet,
    diff_cv,
    export_candidate_profile,
    render_answers,
    render_cover_letter,
    render_cv,
    verify_packet,
)
from quant_recruiting.ats import adapter_for, detect_company_ats
from quant_recruiting.ats_capabilities import capability_report
from quant_recruiting.background_runner import (
    add_job_alert_rule,
    list_job_alert_rules,
)
from quant_recruiting.background_runner import (
    run_once as run_background_once,
)
from quant_recruiting.browser_engine import (
    abort_browser,
    add_field_alias,
    browser_status,
    create_browser_issue,
    inspect_browser,
    install_browser,
    mark_submitted,
    preflight,
    record_dogfood_feedback,
    resolve_field,
    resume_browser,
    run_browser,
)
from quant_recruiting.calendar_export import export_interview_ics
from quant_recruiting.company_service import (
    add_company_alias,
    add_company_domain,
    normalized_company_name,
    resolve_company,
)
from quant_recruiting.config import get_settings
from quant_recruiting.db.models import (
    AITask,
    AITaskRun,
    Application,
    Company,
    CompanyATS,
    DiscoveredURL,
    InterviewStage,
    Job,
    ResearchQuery,
    ResearchSource,
    RoleFamily,
)
from quant_recruiting.db.seed import (
    seed_companies,
    seed_interview_stages,
    seed_role_families,
    seed_skills,
)
from quant_recruiting.db.session import database_diagnostics, session_scope
from quant_recruiting.discovery.core import DiscoveryContext
from quant_recruiting.discovery.official import OfficialSiteDiscoveryProvider
from quant_recruiting.discovery.persistence import persist_discovered_url
from quant_recruiting.email_fixtures import capture_email_fixture
from quant_recruiting.email_ingestion import import_eml
from quant_recruiting.gmail_oauth import (
    GmailOAuthError,
    connect_gmail,
    disconnect_gmail,
    sync_authenticated_gmail,
)
from quant_recruiting.ingestion.web import (
    DiscoveredSource,
    SourceCollector,
    persist_fetch_error,
    persist_fetched_source,
)
from quant_recruiting.intelligence_reports import (
    coverage_report,
    preparation_report,
    process_evidence,
    topic_frequency,
)
from quant_recruiting.jobs import discover_jobs
from quant_recruiting.local_models import (
    LocalAssessment,
    LocalEmailAccount,
    LocalEmailLink,
    LocalEmailMessage,
    LocalInterviewAppointment,
    LocalNotification,
    LocalPrepPlan,
    LocalTimelineEvent,
)
from quant_recruiting.local_ops import (
    backup_local,
    cleanup_local,
    cloud_sync_warnings,
    export_local,
    local_doctor,
    restore_local,
    wipe_local,
)
from quant_recruiting.local_server import app_url, serve_companion
from quant_recruiting.logging_config import configure_logging
from quant_recruiting.personal_migration import migrate_personal_to_local
from quant_recruiting.recruiting_operations import (
    build_prep_plan,
    deliver_due_reminders,
)
from quant_recruiting.research_acquisition import (
    execute_company_search,
    fetch_company_queue,
    queue_company_results,
)
from quant_recruiting.research_discovery import generate_queries, get_search_provider
from quant_recruiting.research_export import export_company
from quant_recruiting.storage import get_local_session, private_session_scope
from quant_recruiting.sync import pull_shared, sync_status
from quant_recruiting.utils import slugify_text

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017 - Python 3.10 local verification compatibility

app = typer.Typer(help="Private recruiting intelligence system.")
db_app = typer.Typer(help="Database operations.")
company_app = typer.Typer(help="Company operations.")
job_app = typer.Typer(help="Job operations.")
source_app = typer.Typer(help="Research source operations.")
research_app = typer.Typer(help="Research export operations.")
ai_app = typer.Typer(help="Human-directed AI task operations.")
ai_conversations_app = typer.Typer(help="Local AI conversation archive.")
seed_app = typer.Typer(help="Seed deterministic reference data.")
discover_app = typer.Typer(help="Discover public company URLs and jobs.")
discovered_app = typer.Typer(help="Inspect persisted discovery candidates.")
applications_app = typer.Typer(help="Application candidate operations.")
ats_app = typer.Typer(help="Public ATS operations.")
refresh_app = typer.Typer(help="Incremental refresh operations.")
intelligence_app = typer.Typer(help="Interview and firm intelligence reports.")
prep_app = typer.Typer(help="Preparation reports.")
artifact_app = typer.Typer(help="Deterministic application artifacts and packets.")
candidate_app = typer.Typer(help="Private candidate profile operations.")
review_app_group = typer.Typer(help="Local human review workspace.")
app_app = typer.Typer(help="Local Recruiting Assistant companion application.")
api_app = typer.Typer(help="Shared public-intelligence API server.")
setup_app = typer.Typer(help="Optional local dependency setup and diagnostics.")
readiness_app = typer.Typer(help="Local operational readiness checks.")
browser_app = typer.Typer(help="Local-only Playwright application autofill.")
background_app = typer.Typer(help="Local-only safe background operations.")
application_app = typer.Typer(help="Application readiness operations.")
local_app = typer.Typer(help="Private local storage operations.")
sync_app = typer.Typer(help="One-way shared intelligence sync operations.")
migrate_app = typer.Typer(help="Non-destructive storage migrations.")
email_app = typer.Typer(help="Local recruiting-email ingestion.")
timeline_app = typer.Typer(help="Local recruiting timeline.")
assessment_app = typer.Typer(help="Local assessment tracking.")
interview_app = typer.Typer(help="Local interview tracking.")
notifications_app = typer.Typer(help="Local notifications.")
calendar_app = typer.Typer(help="Local calendar exports.")
job_alert_app = typer.Typer(help="Local job-alert rules.")
for group, name in (
    (db_app, "db"),
    (company_app, "company"),
    (job_app, "job"),
    (source_app, "source"),
    (research_app, "research"),
    (ai_app, "ai"),
    (seed_app, "seed"),
    (discover_app, "discover"),
    (discovered_app, "discovered"),
    (applications_app, "applications"),
    (ats_app, "ats"),
    (refresh_app, "refresh"),
    (intelligence_app, "intelligence"),
    (prep_app, "prep"),
    (artifact_app, "artifact"),
    (candidate_app, "candidate"),
    (review_app_group, "review"),
    (app_app, "app"),
    (api_app, "api"),
    (setup_app, "setup"),
    (readiness_app, "readiness"),
    (application_app, "application"),
    (local_app, "local"),
    (sync_app, "sync"),
    (migrate_app, "migrate"),
    (email_app, "email"),
    (timeline_app, "timeline"),
    (assessment_app, "assessment"),
    (interview_app, "interview"),
    (notifications_app, "notifications"),
    (calendar_app, "calendar"),
    (browser_app, "browser"),
    (background_app, "background"),
    (job_alert_app, "job-alert"),
):
    app.add_typer(group, name=name)
ai_app.add_typer(ai_conversations_app, name="conversations")


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging.")) -> None:
    configure_logging(verbose)


@db_app.command("check")
def db_check() -> None:
    try:
        diagnostics = database_diagnostics()
    except Exception as exc:
        raise typer.BadParameter(f"database unavailable: {exc}") from exc
    current = cast(tuple[str, ...], diagnostics["current"])
    head = cast(tuple[str, ...], diagnostics["head"])
    extensions = cast(list[str], diagnostics["extensions"])
    typer.echo("Database: connected")
    typer.echo(f"PostgreSQL: {diagnostics['postgres_version']}")
    typer.echo(f"Alembic current: {', '.join(current) or 'none'}")
    typer.echo(f"Alembic head: {', '.join(head)}")
    typer.echo(f"Schema: {'current' if diagnostics['schema_current'] else 'pending migrations'}")
    typer.echo(f"Extensions: {', '.join(extensions) or 'none required'}")
    typer.echo(f"Read/write check: {'passed' if diagnostics['read_write'] else 'failed'}")


@db_app.command("upgrade")
def db_upgrade() -> None:
    config = Config(str(Path("alembic.ini").resolve()))
    command.upgrade(config, "head")
    typer.echo("database: upgraded to head")


@company_app.command("add")
def company_add(
    name: str,
    slug: str | None = None,
    careers_url: str | None = None,
    primary_domain: str | None = None,
) -> None:
    company_slug = slug or slugify_text(name)
    with session_scope() as session:
        if session.scalar(select(Company).where(Company.slug == company_slug)):
            raise typer.BadParameter(f"company slug already exists: {company_slug}")
        company = Company(
            name=name,
            slug=company_slug,
            normalized_name=normalized_company_name(name),
            careers_url=careers_url,
            primary_domain=primary_domain,
        )
        session.add(company)
        session.flush()
        typer.echo(f"created company {company.name} ({company.slug})")


@company_app.command("list")
def company_list() -> None:
    with session_scope() as session:
        for company in session.scalars(select(Company).order_by(Company.name)):
            typer.echo(
                f"{company.slug}\t{company.name}\t{'active' if company.active else 'inactive'}"
            )


@company_app.command("show")
def company_show(slug: str) -> None:
    with session_scope() as session:
        company = session.scalar(select(Company).where(Company.slug == slug))
        if company is None:
            raise typer.BadParameter(f"unknown company: {slug}")
        typer.echo(f"{company.name} ({company.slug})")
        typer.echo(f"domain: {company.primary_domain or '-'}")
        typer.echo(f"careers: {company.careers_url or '-'}")
        typer.echo(f"jobs: {len(company.jobs)} | sources: {len(company.sources)}")


@company_app.command("add-alias")
def company_add_alias(company: str, alias: str) -> None:
    with session_scope() as session:
        canonical = resolve_company(session, company)
        add_company_alias(session, canonical, alias)
        typer.echo(f"alias added: {alias} -> {canonical.slug}")


@company_app.command("add-domain")
def company_add_domain(
    company: str,
    domain: str,
    domain_type: str = "other",
    canonical: bool = False,
    verified: bool = False,
) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        item = add_company_domain(
            session,
            canonical_company,
            domain,
            domain_type=domain_type,
            canonical=canonical,
            verified=verified,
        )
        typer.echo(f"domain added: {item.domain} -> {canonical_company.slug}")


@company_app.command("set-careers-url")
def company_set_careers_url(company: str, url: str) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        canonical_company.careers_url = url
        session.flush()
        typer.echo(f"careers URL set: {canonical_company.slug} -> {url}")


@job_app.command("add")
def job_add(
    company_slug: str,
    title: str,
    job_url: str,
    role_family: str = "other",
    external_id: str | None = None,
    location: str | None = None,
) -> None:
    now = datetime.now(UTC)
    with session_scope() as session:
        company = session.scalar(select(Company).where(Company.slug == company_slug))
        if company is None:
            raise typer.BadParameter(f"unknown company: {company_slug}")
        existing = session.scalar(
            select(Job).where(Job.company_id == company.id, Job.job_url == job_url)
        )
        if existing:
            existing.date_last_seen = now
            typer.echo(f"job already tracked: {existing.id}")
            return
        job = Job(
            company=company,
            title=title,
            job_url=job_url,
            role_family=role_family,
            external_id=external_id,
            location_text=location,
            source_type="manual",
            date_first_seen=now,
            date_last_seen=now,
        )
        session.add(job)
        session.flush()
        typer.echo(f"created job {job.id}")


@job_app.command("list")
def job_list(company_slug: str | None = None) -> None:
    with session_scope() as session:
        query = select(Job).join(Company).order_by(Company.name, Job.title)
        if company_slug:
            query = query.where(Company.slug == company_slug)
        for job in session.scalars(query):
            typer.echo(
                f"{job.company.slug}\t{job.title}\t{job.role_family}\t{job.status}\t{job.job_url}"
            )


@source_app.command("add-url")
def source_add_url(
    url: str, company_slug: str | None = None, source_type: str = "official_website"
) -> None:
    settings = get_settings()
    with session_scope() as session:
        company = (
            session.scalar(select(Company).where(Company.slug == company_slug))
            if company_slug
            else None
        )
        if company_slug and company is None:
            raise typer.BadParameter(f"unknown company: {company_slug}")
        try:
            fetched = SourceCollector().fetch(DiscoveredSource(url, source_type), settings)
        except (OSError, PermissionError, RuntimeError, ValueError, httpx.HTTPError) as exc:
            persist_fetch_error(session, url, exc, operation="source_add_url")
            raise typer.BadParameter(f"source fetch failed: {exc}") from exc
        source, document, changed = persist_fetched_source(session, company, fetched, settings)
        state = "changed" if changed else "unchanged"
        typer.echo(f"source {source.id} document v{document.version} ({state})")


@source_app.command("list")
def source_list(company_slug: str | None = None) -> None:
    with session_scope() as session:
        query = select(ResearchSource).order_by(ResearchSource.retrieved_at.desc())
        if company_slug:
            query = query.join(Company).where(Company.slug == company_slug)
        for source in session.scalars(query):
            typer.echo(f"{source.id}\t{source.source_type}\t{source.source_quality}\t{source.url}")


@source_app.command("ingest-discovered")
def source_ingest_discovered(company: str, minimum_score: float = 0.2) -> None:
    settings = get_settings()
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        candidates = session.scalars(
            select(DiscoveredURL).where(
                DiscoveredURL.company_id == canonical_company.id,
                DiscoveredURL.relevance_score >= minimum_score,
                DiscoveredURL.status.in_(["discovered", "queued", "failed"]),
            )
        )
        ingested = failed = 0
        for item in candidates:
            freshness_hours = (
                settings.job_freshness_hours
                if item.probable_source_type in {"role_description", "internship", "job_board"}
                else settings.discovery_freshness_hours
            )
            if item.last_fetched_at and datetime.now(UTC) - item.last_fetched_at < timedelta(
                hours=freshness_hours
            ):
                continue
            try:
                fetched = SourceCollector().fetch(
                    DiscoveredSource(
                        item.url,
                        item.probable_source_type,
                        metadata={"discovery_id": str(item.id), **item.metadata_},
                    ),
                    settings,
                )
                source, _, _ = persist_fetched_source(session, canonical_company, fetched, settings)
                item.ingested_source_id = source.id
                item.status = "ingested"
                item.last_fetched_at = fetched.retrieved_at
                ingested += 1
            except (OSError, PermissionError, RuntimeError, ValueError, httpx.HTTPError) as exc:
                item.status = "failed"
                item.error_message = str(exc)
                persist_fetch_error(session, item.url, exc, operation="discovered_source")
                failed += 1
        typer.echo(f"Ingested: {ingested}")
        typer.echo(f"Failed: {failed}")


@research_app.command("export")
def research_export(company_slug: str) -> None:
    with session_scope() as session:
        company = session.scalar(select(Company).where(Company.slug == company_slug))
        if company is None:
            raise typer.BadParameter(f"unknown company: {company_slug}")
        typer.echo(f"exported {export_company(session, company, get_settings())}")


@ai_app.command("prepare-company")
def ai_prepare_company(company_slug: str, full: bool = False) -> None:
    with private_session_scope() as session:
        company = resolve_company(session, company_slug)
        task = prepare_task(
            session,
            task_type="company_synthesis",
            entity_type="company",
            entity_id=company.id,
            settings=get_settings(),
            full=full,
        )
        typer.echo(f"created AI task {task.id}: {task.input_manifest_path}")


@seed_app.command("skills")
def seed_skills_command() -> None:
    with session_scope() as session:
        typer.echo(f"skills created: {seed_skills(session)}")


@seed_app.command("taxonomy")
def seed_taxonomy_command() -> None:
    with session_scope() as session:
        created = seed_role_families(session) + seed_interview_stages(session)
        typer.echo(f"taxonomy records created: {created}")


@seed_app.command("companies")
def seed_companies_command() -> None:
    with session_scope() as session:
        typer.echo(f"companies created: {seed_companies(session)}")


def _discover(company_value: str, careers_only: bool = False) -> None:
    settings = get_settings()
    with session_scope() as session:
        company = resolve_company(session, company_value)
        candidates = OfficialSiteDiscoveryProvider(session, settings).discover(
            company,
            DiscoveryContext(
                max_pages=settings.discovery_max_pages,
                max_depth=settings.discovery_max_depth,
                per_domain_delay_seconds=settings.http_per_host_delay_seconds,
            ),
        )
        if careers_only:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.probable_source_type in {"careers", "internship", "role_description"}
                or "career" in candidate.url.lower()
            ]
        for candidate in candidates:
            persist_discovered_url(session, company, candidate)
        typer.echo(f"Company: {company.name}")
        for candidate in candidates:
            typer.echo(f"{candidate.relevance_score:.2f} {candidate.url} [{candidate.reason}]")
        typer.echo(f"Discovered: {len(candidates)}")


@discover_app.command("website")
def discover_website(company: str) -> None:
    _discover(company)


@discover_app.command("careers")
def discover_careers(company: str) -> None:
    _discover(company, careers_only=True)


@discover_app.command("jobs")
def discover_jobs_command(company: str) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        result = discover_jobs(session, canonical_company, get_settings())
        typer.echo(canonical_company.name)
        for key, value in result.items():
            typer.echo(f"{key.replace('_', ' ').title()}: {value}")


@discovered_app.command("list")
def discovered_list(company: str) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        query = (
            select(DiscoveredURL)
            .where(DiscoveredURL.company_id == canonical_company.id)
            .order_by(DiscoveredURL.relevance_score.desc())
        )
        for item in session.scalars(query):
            typer.echo(
                f"{item.status}\t{item.relevance_score:.2f}\t{item.probable_source_type}\t{item.url}"
            )


@job_app.command("sync")
def job_sync(company: str) -> None:
    discover_jobs_command(company)


@applications_app.command("candidates")
def application_candidates(config_path: Path = Path("config/recruiting.yaml")) -> None:
    criteria = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    role_config = criteria.get("role_families", {})
    roles = set(role_config.get("include", criteria.get("target_role_families", [])))
    excluded_roles = set(role_config.get("exclude", []))
    cycles = {str(value) for value in criteria.get("target_cycles", [])}
    location_config = criteria.get("locations", {})
    locations = [
        str(value).lower()
        for value in location_config.get("include", criteria.get("target_locations", []))
    ]
    excluded_locations = [str(value).lower() for value in location_config.get("exclude", [])]
    include = set(criteria.get("companies", {}).get("include", []))
    exclude = set(criteria.get("companies", {}).get("exclude", []))
    with private_session_scope() as session:
        query = select(Job).join(Company).where(Job.status == "open")
        for job in session.scalars(query):
            location = (job.location_text or "").lower()
            if roles and job.role_family not in roles:
                continue
            if job.role_family in excluded_roles:
                continue
            if cycles and job.internship_cycle not in cycles:
                continue
            if locations and not any(value in location for value in locations):
                continue
            if excluded_locations and any(value in location for value in excluded_locations):
                continue
            if include and job.company.slug not in include:
                continue
            if job.company.slug in exclude:
                continue
            typer.echo(f"{job.id}\t{job.company.slug}\t{job.title}\t{job.location_text or '-'}")


@applications_app.command("create")
def application_create(job_id: str) -> None:
    with private_session_scope() as session:
        job = session.get(Job, UUID(job_id))
        if job is None:
            raise typer.BadParameter(f"unknown job: {job_id}")
        existing = session.scalar(select(Application).where(Application.job_id == job.id))
        if existing:
            typer.echo(f"application already exists: {existing.id}")
            return
        application = Application(job=job)
        session.add(application)
        session.flush()
        typer.echo(f"created application {application.id}")


@ai_app.command("prepare-application")
def ai_prepare_application(application_id: str, full: bool = False) -> None:
    with private_session_scope() as session:
        application = session.get(Application, UUID(application_id))
        if application is None:
            raise typer.BadParameter(f"unknown application: {application_id}")
        path = export_application(session, application, get_settings())
        task = prepare_task(
            session,
            task_type="application_analysis",
            entity_type="application",
            entity_id=application.id,
            settings=get_settings(),
            full=full,
        )
        typer.echo(f"created application context: {path}")
        typer.echo(f"created AI task {task.id}: {task.input_manifest_path}")


@ai_app.command("prepare-match")
def ai_prepare_match(company: str, full: bool = False) -> None:
    with private_session_scope() as session:
        canonical = resolve_company(session, company)
        task = prepare_task(
            session,
            task_type="candidate_firm_match",
            entity_type="company",
            entity_id=canonical.id,
            settings=get_settings(),
            full=full,
        )
        typer.echo(f"created AI task {task.id}: {task.input_manifest_path}")


def _prepare_application_task(application_id: str, task_type: str, full: bool) -> None:
    with private_session_scope() as session:
        application = session.get(Application, UUID(application_id))
        if application is None:
            raise typer.BadParameter(f"unknown application: {application_id}")
        task = prepare_task(
            session,
            task_type=task_type,
            entity_type="application",
            entity_id=application.id,
            settings=get_settings(),
            full=full,
        )
        typer.echo(f"created AI task {task.id}: {task.input_manifest_path}")


@ai_app.command("prepare-answers")
def ai_prepare_answers(application_id: str, full: bool = False) -> None:
    _prepare_application_task(application_id, "written_answers", full)


@ai_app.command("prepare-cover-letter")
def ai_prepare_cover_letter(application_id: str, full: bool = False) -> None:
    _prepare_application_task(application_id, "cover_letter", full)


@ai_app.command("prepare-cv")
def ai_prepare_cv(application_id: str, full: bool = False) -> None:
    _prepare_application_task(application_id, "cv_tailoring", full)


@ai_app.command("prepare-interview")
def ai_prepare_interview(application_id: str, full: bool = False) -> None:
    _prepare_application_task(application_id, "interview_prep", full)


@ai_app.command("readiness")
def ai_readiness(application_id: str) -> None:
    with private_session_scope() as session:
        application = session.get(Application, UUID(application_id))
        if application is None:
            raise typer.BadParameter(f"unknown application: {application_id}")
        typer.echo(json.dumps(readiness(session, application), indent=2, default=str))


@ai_app.command("validate")
def ai_validate(task_id: str) -> None:
    with private_session_scope() as session:
        result = validate_task(session, UUID(task_id), get_settings())
        typer.echo(json.dumps(result, indent=2))
        if result["status"] != "valid":
            raise typer.Exit(code=1)


@local_app.command("doctor")
def local_doctor_command() -> None:
    typer.echo(json.dumps(local_doctor(get_settings()), indent=2, default=str))


@readiness_app.command("system")
def system_readiness_command() -> None:
    from quant_recruiting.system_readiness import system_readiness

    typer.echo(json.dumps(system_readiness(get_settings()), indent=2, default=str))


@local_app.command("backup")
def local_backup_command(
    destination: Path | None = typer.Option(None, "--destination"),  # noqa: B008
    include_browser_state: bool = typer.Option(False, "--include-browser-state"),  # noqa: B008
) -> None:
    backup_path = backup_local(
        get_settings(), destination=destination, include_browser_state=include_browser_state
    )
    typer.echo(f"private backup: {backup_path}")
    for warning in cloud_sync_warnings(backup_path):
        typer.echo(f"WARNING: {warning}", err=True)


@local_app.command("restore")
def local_restore_command(
    backup: Path,
    destination: Path | None = typer.Option(None, "--destination"),  # noqa: B008
) -> None:
    typer.echo(
        f"restored private data: {restore_local(backup, get_settings(), destination=destination)}"
    )


@local_app.command("export")
def local_export_command(destination: Path | None = typer.Option(None, "--destination")) -> None:  # noqa: B008
    typer.echo(f"private export: {export_local(get_settings(), destination=destination)}")


@local_app.command("cleanup")
def local_cleanup_command(
    cache: bool = typer.Option(False, "--cache"),
    browser_screenshots: bool = typer.Option(False, "--browser-screenshots"),
    temp: bool = typer.Option(False, "--temp"),
    old_ai_exports: bool = typer.Option(False, "--old-ai-exports"),
) -> None:
    removed = cleanup_local(
        get_settings(),
        cache=cache,
        browser_screenshots=browser_screenshots,
        temp=temp,
        old_ai_exports=old_ai_exports,
    )
    typer.echo(json.dumps({"removed": removed}, indent=2))


@local_app.command("wipe")
def local_wipe_command(
    confirmation: str = typer.Option(..., prompt="Type WIPE LOCAL RECRUITING DATA"),
) -> None:
    typer.echo(f"wiped: {wipe_local(get_settings(), confirmation=confirmation)}")


@sync_app.command("pull")
def sync_pull_command(
    company: str | None = typer.Option(None, "--company"),
    since: str | None = typer.Option(None, "--since"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    parsed_since = datetime.fromisoformat(since) if since else None
    typer.echo(
        json.dumps(
            pull_shared(get_settings(), company_slug=company, since=parsed_since, dry_run=dry_run),
            indent=2,
            default=str,
        )
    )


@sync_app.command("status")
def sync_status_command() -> None:
    typer.echo(json.dumps(sync_status(get_settings()), indent=2, default=str))


@local_app.command("migrate-personal")
def local_migrate_personal_command(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    typer.echo(
        json.dumps(
            migrate_personal_to_local(get_settings(), dry_run=dry_run), indent=2, default=str
        )
    )


@migrate_app.command("personal-to-local")
def migrate_personal_command(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    typer.echo(
        json.dumps(
            migrate_personal_to_local(get_settings(), dry_run=dry_run), indent=2, default=str
        )
    )


@background_app.command("run-once")
def background_run_once() -> None:
    try:
        result = run_background_once(get_settings(), trigger="cli")
    except RuntimeError as exc:
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(result, indent=2, default=str))


@background_app.command("install")
def background_install() -> None:
    from quant_recruiting.windows_scheduler import install_task

    typer.echo(install_task(executable=None))


@background_app.command("status")
def background_status() -> None:
    from quant_recruiting.windows_scheduler import task_status

    typer.echo(json.dumps(task_status(), indent=2))


@background_app.command("remove")
def background_remove() -> None:
    from quant_recruiting.windows_scheduler import remove_task

    typer.echo(json.dumps({"removed": remove_task()}, indent=2))


@setup_app.command("scheduled-tasks")
def setup_scheduled_tasks() -> None:
    from quant_recruiting.windows_scheduler import install_task

    typer.echo(install_task(executable=None))


@job_alert_app.command("add")
def job_alert_add(
    name: str,
    role_family: list[str] = typer.Option([], "--role-family"),  # noqa: B008
    location: list[str] = typer.Option([], "--location"),  # noqa: B008
    company: list[str] = typer.Option([], "--company"),  # noqa: B008
    keyword: list[str] = typer.Option([], "--keyword"),  # noqa: B008
) -> None:
    filters = {
        "role_families": role_family,
        "locations": location,
        "companies": company,
        "keywords": keyword,
    }
    typer.echo(json.dumps(add_job_alert_rule(name, filters, get_settings()), indent=2))


@job_alert_app.command("list")
def job_alert_list() -> None:
    typer.echo(json.dumps(list_job_alert_rules(get_settings()), indent=2))


@ai_app.command("import")
def ai_import(task_id: str) -> None:
    with private_session_scope() as session:
        created = import_task(session, UUID(task_id), get_settings())
        typer.echo(f"imported {created} draft records")


@ai_app.command("approve")
def ai_approve(task_id: str, approved_by: str = "human") -> None:
    with private_session_scope() as session:
        task = approve_task(session, UUID(task_id), approved_by)
        typer.echo(f"approved task {task.id} by {task.approved_by}")


@ai_app.command("prompt")
def ai_prompt(task_id: str) -> None:
    with private_session_scope() as session:
        task = session.get(AITask, UUID(task_id))
        if task is None or not task.input_manifest_path:
            raise typer.BadParameter(f"unknown AI task: {task_id}")
        instructions = Path(task.input_manifest_path).parent / "instructions.md"
        typer.echo(instructions.read_text(encoding="utf-8"))


@ai_app.command("diff")
def ai_diff(run_a: str, run_b: str) -> None:
    with private_session_scope() as session:
        first = session.get(AITaskRun, UUID(run_a))
        second = session.get(AITaskRun, UUID(run_b))
        if first is None or second is None:
            raise typer.BadParameter("both AI task run IDs must exist")
        left = json.loads(Path(first.output_path).read_text(encoding="utf-8"))
        right = json.loads(Path(second.output_path).read_text(encoding="utf-8"))
        typer.echo(
            json.dumps(
                {"run_a": left, "run_b": right, "equal": left == right}, indent=2, default=str
            )
        )


@ai_app.command("open")
def ai_open(task_id: str, provider: str | None = typer.Option(None, "--provider")) -> None:
    result = open_task(UUID(task_id), provider, get_settings())
    typer.echo(json.dumps(result, indent=2))


@ai_app.command("import-conversations")
def ai_import_conversations(
    provider: str, path: Path, dry_run: bool = typer.Option(False, "--dry-run")
) -> None:
    result = import_conversations(provider, path, get_settings(), dry_run=dry_run)
    typer.echo(json.dumps(result, indent=2))


@ai_app.command("import-conversation")
def ai_import_conversation(
    path: Path, provider: str = "custom", dry_run: bool = typer.Option(False, "--dry-run")
) -> None:
    result = import_conversations(provider, path, get_settings(), dry_run=dry_run)
    typer.echo(json.dumps(result, indent=2))


@ai_conversations_app.command("list")
def ai_conversations_list() -> None:
    typer.echo(json.dumps(list_conversations(get_settings()), indent=2))


@ai_conversations_app.command("search")
def ai_conversations_search(query: str) -> None:
    typer.echo(json.dumps(search_conversations(query, get_settings()), indent=2))


@ai_conversations_app.command("show")
def ai_conversations_show(conversation_id: str) -> None:
    typer.echo(json.dumps(show_conversation(UUID(conversation_id), get_settings()), indent=2))


@ai_conversations_app.command("link")
def ai_conversations_link(conversation_id: str, entity_type: str, entity_id: str) -> None:
    link_conversation(UUID(conversation_id), entity_type, entity_id, get_settings())
    typer.echo(f"linked conversation {conversation_id} to {entity_type}:{entity_id}")


@applications_app.command("quality")
def application_quality(application_id: str) -> None:
    with private_session_scope() as session:
        application = session.get(Application, UUID(application_id))
        if application is None:
            raise typer.BadParameter(f"unknown application: {application_id}")
        typer.echo(json.dumps(quality_report(session, application), indent=2, default=str))


def _get_application(session: Session, application_id: str) -> Application:
    application = session.get(Application, UUID(application_id))
    if application is None:
        raise typer.BadParameter(f"unknown application: {application_id}")
    return cast(Application, application)


@application_app.command("readiness")
def application_readiness_command(application_id: str) -> None:
    with private_session_scope() as session:
        typer.echo(
            json.dumps(
                application_readiness(session, _get_application(session, application_id)),
                indent=2,
                default=str,
            )
        )


@application_app.command("quality")
def application_quality_command(application_id: str) -> None:
    with private_session_scope() as session:
        typer.echo(
            json.dumps(
                quality_report(session, _get_application(session, application_id)),
                indent=2,
                default=str,
            )
        )


@application_app.command("mark-submitted")
def application_mark_submitted(application_id: str, run_id: str | None = None) -> None:
    """Record a submission performed manually by the user."""
    if run_id is None:
        raise typer.BadParameter("run_id is required so manual submission remains auditable")
    result = mark_submitted(UUID(run_id))
    if result["application_id"] != application_id:
        raise typer.BadParameter("run does not belong to the supplied application")
    typer.echo(json.dumps(result, indent=2))


@artifact_app.command("render-cv")
def artifact_render_cv(application_id: str) -> None:
    with private_session_scope() as session:
        artifacts = render_cv(session, _get_application(session, application_id), get_settings())
        typer.echo(json.dumps({key: str(value.id) for key, value in artifacts.items()}, indent=2))


@artifact_app.command("render-cover-letter")
def artifact_render_cover_letter(application_id: str) -> None:
    with private_session_scope() as session:
        artifacts = render_cover_letter(
            session, _get_application(session, application_id), get_settings()
        )
        typer.echo(json.dumps({key: str(value.id) for key, value in artifacts.items()}, indent=2))


@artifact_app.command("render-answers")
def artifact_render_answers(
    application_id: str, appendix: bool = typer.Option(False, "--appendix")
) -> None:
    with private_session_scope() as session:
        artifacts = render_answers(
            session,
            _get_application(session, application_id),
            get_settings(),
            include_provenance_appendix=appendix,
        )
        typer.echo(json.dumps({key: str(value.id) for key, value in artifacts.items()}, indent=2))


@artifact_app.command("build-packet")
def artifact_build_packet(application_id: str) -> None:
    with private_session_scope() as session:
        path = build_packet(session, _get_application(session, application_id), get_settings())
        typer.echo(f"packet built: {path}")


@artifact_app.command("verify-packet")
def artifact_verify_packet(application_id: str) -> None:
    with private_session_scope() as session:
        result = verify_packet(session, _get_application(session, application_id))
        typer.echo(json.dumps(result, indent=2))
        if result["status"] != "valid":
            raise typer.Exit(code=1)


@artifact_app.command("approve")
def artifact_approve(artifact_id: str, reviewer: str = "human") -> None:
    with private_session_scope() as session:
        artifact = approve_artifact(session, UUID(artifact_id), reviewer)
        typer.echo(f"approved artifact {artifact.id}")


@artifact_app.command("diff-cv")
def artifact_diff_cv(artifact_a: str, artifact_b: str) -> None:
    with private_session_scope() as session:
        typer.echo(json.dumps(diff_cv(session, UUID(artifact_a), UUID(artifact_b)), indent=2))


@artifact_app.command("approve-answer")
def artifact_approve_answer(answer_id: str, reviewer: str = "human") -> None:
    with private_session_scope() as session:
        answer = approve_answer(session, UUID(answer_id), reviewer)
        typer.echo(f"approved answer {answer.id}")


@candidate_app.command("export-profile")
def candidate_export_profile() -> None:
    with private_session_scope() as session:
        typer.echo(f"candidate profile exported: {export_candidate_profile(session)}")


@review_app_group.command("serve")
def review_serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    from quant_recruiting.review_app import create_review_app

    typer.echo(f"review workspace: http://{host}:{port} (local-only by default)")
    uvicorn.run(create_review_app(), host=host, port=port)


@app_app.command("serve")
def app_serve(
    host: str | None = None,
    port: int | None = typer.Option(None, min=1, max=65535),
    open_browser: bool = typer.Option(False, "--open-browser"),
) -> None:
    """Run the local-first companion on loopback."""
    settings = get_settings()
    selected_host = host or settings.local_host
    selected_port = port or settings.local_port
    typer.echo(f"Recruiting Assistant: {app_url(settings, host=selected_host, port=selected_port)}")
    serve_companion(
        settings,
        host=selected_host,
        port=selected_port,
        open_browser=open_browser or settings.auto_open_browser,
    )


@app_app.command("open")
def app_open(
    host: str | None = None,
    port: int | None = typer.Option(None, min=1, max=65535),
) -> None:
    """Open the already-running local companion in the default browser."""
    url = app_url(get_settings(), host=host, port=port)
    webbrowser.open(url)
    typer.echo(f"opened {url}")


@api_app.command("serve")
def api_serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    """Run the public shared-intelligence API; no private tables are routed here."""
    import uvicorn

    from quant_recruiting.shared_api.app import create_shared_api

    typer.echo(f"shared API: http://{host}:{port}/api/v1/health")
    backend_settings = get_settings().model_copy(update={"shared_transport": "postgres"})
    uvicorn.run(create_shared_api(backend_settings), host=host, port=port)


@api_app.command("check")
def api_check() -> None:
    """Check the configured shared API version without exposing credentials."""
    from quant_recruiting.shared_client import get_shared_client

    version = get_shared_client(get_settings()).version()
    typer.echo(json.dumps(version.model_dump(mode="json"), indent=2))


@setup_app.command("browser")
def setup_browser(install: bool = typer.Option(False, "--install")) -> None:
    """Check or install the local Playwright Chromium dependency."""
    if importlib.util.find_spec("playwright") is None:
        typer.echo("Playwright is not installed. Install project dependencies first.")
        return
    if install:
        code = install_browser()
        if code:
            raise typer.Exit(code=code)
    from quant_recruiting.browser_engine import browser_diagnostics

    typer.echo(json.dumps(browser_diagnostics(get_settings()), indent=2))


@browser_app.command("preflight")
def browser_preflight(application_id: str) -> None:
    typer.echo(json.dumps(preflight(UUID(application_id)), indent=2, default=str))


@browser_app.command("inspect")
def browser_inspect(application_id: str) -> None:
    typer.echo(json.dumps(inspect_browser(UUID(application_id)), indent=2, default=str))


@browser_app.command("fill")
def browser_fill(application_id: str) -> None:
    typer.echo(json.dumps(run_browser(UUID(application_id)), indent=2, default=str))


@browser_app.command("run")
def browser_run(
    application_id: str,
    mode: str = typer.Option("autofill", "--mode", help="autofill, assisted, or inspect"),
    dogfood: bool = typer.Option(
        False, "--dogfood", help="Record this local run for dogfood metrics."
    ),
) -> None:
    if mode == "inspect":
        result = inspect_browser(UUID(application_id), mode=mode)
    else:
        result = run_browser(UUID(application_id), mode=mode, dogfood=dogfood)
    typer.echo(json.dumps(result, indent=2, default=str))


@browser_app.command("resume")
def browser_resume(run_id: str) -> None:
    typer.echo(json.dumps(resume_browser(UUID(run_id)), indent=2, default=str))


@browser_app.command("status")
def browser_run_status(run_id: str) -> None:
    typer.echo(json.dumps(browser_status(UUID(run_id)), indent=2, default=str))


@browser_app.command("report")
def browser_report(run_id: str) -> None:
    result = browser_status(UUID(run_id))
    run_dir = Path(result["screenshot_dir"]).parent
    report = run_dir / "review.html"
    typer.echo(
        json.dumps(
            {
                **result,
                "report": str(report),
                "checklist": str(run_dir / "submission-checklist.md"),
            },
            indent=2,
        )
    )


@browser_app.command("abort")
def browser_abort(run_id: str) -> None:
    typer.echo(json.dumps(abort_browser(UUID(run_id)), indent=2))


@browser_app.command("restart")
def browser_restart(run_id: str) -> None:
    from quant_recruiting.browser_engine import restart_browser

    typer.echo(json.dumps(restart_browser(UUID(run_id)), indent=2, default=str))


@browser_app.command("ats-status")
def browser_ats_status() -> None:
    typer.echo(json.dumps(capability_report(get_settings()), indent=2, default=str))


@browser_app.command("diagnostics")
def browser_diagnostics_command(run_id: str) -> None:
    from quant_recruiting.browser_engine import run_diagnostics

    typer.echo(json.dumps(run_diagnostics(UUID(run_id)), indent=2, default=str))


@browser_app.command("privacy-check")
def browser_privacy_check(run_id: str) -> None:
    from quant_recruiting.browser_engine import privacy_check

    typer.echo(json.dumps(privacy_check(UUID(run_id)), indent=2, default=str))


@browser_app.command("export-diagnostics")
def browser_export_diagnostics(
    run_id: str,
    destination: Path | None = typer.Option(None, "--destination"),  # noqa: B008
) -> None:  # noqa: B008
    from quant_recruiting.browser_engine import export_diagnostics

    typer.echo(str(export_diagnostics(UUID(run_id), destination=destination)))


@browser_app.command("capture-fixture")
def browser_capture_fixture(
    url: str,
    real_sanitized: bool = typer.Option(
        False, "--real-sanitized", help="Mark a manually reviewed real-page capture as such."
    ),
) -> None:
    from quant_recruiting.browser_diagnostics import capture_fixture

    typer.echo(
        json.dumps(
            capture_fixture(
                url,
                get_settings(),
                source_kind="real_sanitized" if real_sanitized else "sanitized_capture",
            ),
            indent=2,
            default=str,
        )
    )


@browser_app.command("resolve")
def browser_resolve(
    run_id: str,
    field_key: str,
    value: str,
    reusable: bool = typer.Option(False, "--reusable"),
) -> None:
    typer.echo(
        json.dumps(resolve_field(UUID(run_id), field_key, value, reusable=reusable), indent=2)
    )


@browser_app.command("alias")
def browser_alias(label: str, normalized_key: str) -> None:
    """Save a local deterministic field-label override."""
    typer.echo(json.dumps(add_field_alias(label, normalized_key), indent=2))


@browser_app.command("dogfood-report")
def browser_dogfood_report() -> None:
    from quant_recruiting.browser_engine import dogfood_report

    typer.echo(json.dumps(dogfood_report(get_settings()), indent=2, default=str))


@browser_app.command("feedback")
def browser_feedback(
    run_id: str,
    feedback_status: str,
    note: str | None = typer.Option(None, "--note"),
) -> None:
    typer.echo(
        json.dumps(
            record_dogfood_feedback(UUID(run_id), feedback_status, note, get_settings()),
            indent=2,
        )
    )


@browser_app.command("issue")
def browser_issue(
    run_id: str,
    failure_category: str,
    description: str,
    priority: str = typer.Option("P1", "--priority"),
) -> None:
    typer.echo(
        json.dumps(
            create_browser_issue(
                UUID(run_id),
                failure_category,
                description,
                priority=priority,
                settings=get_settings(),
            ),
            indent=2,
        )
    )


@ats_app.command("detect")
def ats_detect(company: str) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        detections = detect_company_ats(canonical_company)
        now = datetime.now(UTC)
        for detection in detections:
            existing = session.scalar(
                select(CompanyATS).where(
                    CompanyATS.company_id == canonical_company.id,
                    CompanyATS.provider == detection.provider,
                    CompanyATS.board_identifier == detection.board_identifier,
                )
            )
            if existing is None:
                session.add(
                    CompanyATS(
                        company=canonical_company,
                        provider=detection.provider,
                        board_identifier=detection.board_identifier,
                        board_url=detection.board_url,
                        verified=True,
                        discovered_at=now,
                        last_verified_at=now,
                    )
                )
            else:
                existing.last_verified_at = now
            typer.echo(
                f"{detection.provider}: {detection.board_identifier} ({detection.confidence:.2f})"
            )
        if not detections:
            typer.echo("No public Greenhouse, Lever, or Ashby board detected from known URLs.")


@ats_app.command("sync")
def ats_sync(company: str) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        configs = list(
            session.scalars(select(CompanyATS).where(CompanyATS.company_id == canonical_company.id))
        )
        if not configs:
            raise typer.BadParameter(
                "no ATS configuration; run ats detect or add one from a verified public board URL"
            )
        from quant_recruiting.jobs import upsert_job

        settings = get_settings()
        new = changed = unchanged = 0
        with httpx.Client(
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.http_user_agent},
            follow_redirects=True,
        ) as client:
            for config in configs:
                adapter = adapter_for(config.provider)
                payloads = adapter.list_jobs(config, client)
                seen: set[UUID] = set()
                for payload in payloads:
                    posting = adapter.normalize_job(payload, config)
                    job, is_new, is_changed = upsert_job(
                        session, canonical_company, posting, config.board_url, config
                    )
                    seen.add(job.id)
                    new += is_new
                    changed += not is_new and is_changed
                    unchanged += not is_new and not is_changed
                for job in session.scalars(
                    select(Job).where(
                        Job.company_id == canonical_company.id,
                        Job.company_ats_id == config.id,
                        Job.status == "open",
                    )
                ):
                    if job.id not in seen:
                        job.status = "closed"
        typer.echo(f"Company: {canonical_company.name}")
        typer.echo(f"Jobs discovered: {new + changed + unchanged}")
        typer.echo(f"New: {new}\nChanged: {changed}\nUnchanged: {unchanged}")


@research_app.command("discover")
def research_discover(
    company: str, role_family: str | None = None, cycle: str | None = None
) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        specs = generate_queries(canonical_company, role_family, cycle)
        created = 0
        for spec in specs:
            existing = session.scalar(
                select(ResearchQuery).where(
                    ResearchQuery.company_id == canonical_company.id,
                    ResearchQuery.query == spec.query,
                    ResearchQuery.category == spec.category,
                )
            )
            if existing is None:
                session.add(
                    ResearchQuery(
                        company_id=canonical_company.id,
                        category=spec.category,
                        query=spec.query,
                        provider="configured_search",
                        discovered_at=datetime.now(UTC),
                        recruiting_cycle=spec.recruiting_cycle,
                        metadata_={"role_family": spec.role_family},
                    )
                )
                created += 1
            typer.echo(f"{spec.category}: {spec.query}")
        typer.echo(f"Queries created: {created}; total generated: {len(specs)}")


@research_app.command("search")
def research_search(
    company: str,
    dry_run: bool = typer.Option(False, "--dry-run"),
    limit: int | None = typer.Option(None, "--limit"),
    category: str | None = typer.Option(None, "--category"),
    role: str | None = typer.Option(None, "--role"),
    cycle: str | None = typer.Option(None, "--cycle"),
    force: bool = typer.Option(
        False, "--force", help="Reserved for bypassing future result caches."
    ),
) -> None:
    del force
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        try:
            provider = get_search_provider(get_settings())
            result = execute_company_search(
                session,
                canonical_company,
                get_settings(),
                provider,
                category=category,
                role_family=role,
                cycle=cycle,
                limit=limit,
                dry_run=dry_run,
            )
        except (RuntimeError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(json.dumps(result, indent=2, sort_keys=True))


@research_app.command("queue")
def research_queue(
    company: str,
    min_score: float = typer.Option(0.0, "--min-score"),
    max_items: int | None = typer.Option(None, "--max-items"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        if not dry_run:
            queue_company_results(session, canonical_company, min_score=min_score)
        from quant_recruiting.db.models import ResearchFetchQueue

        items = list(
            session.scalars(
                select(ResearchFetchQueue)
                .where(
                    ResearchFetchQueue.company_id == canonical_company.id,
                    ResearchFetchQueue.score >= min_score,
                )
                .order_by(ResearchFetchQueue.score.desc())
                .limit(max_items)
            )
        )
        for item in items:
            typer.echo(f"{item.status}\t{item.score:.2f}\t{item.url}")
        typer.echo(f"Queue candidates: {len(items)}")


@research_app.command("fetch")
def research_fetch(
    company: str,
    min_score: float = typer.Option(0.0, "--min-score"),
    max_items: int = typer.Option(20, "--max-items"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        result = fetch_company_queue(
            session,
            canonical_company,
            get_settings(),
            min_score=min_score,
            max_items=max_items,
            dry_run=dry_run,
        )
        typer.echo(json.dumps(result, indent=2, sort_keys=True))


@research_app.command("coverage")
def research_coverage(company: str) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        typer.echo(
            json.dumps(coverage_report(session, canonical_company), indent=2, sort_keys=True)
        )


@intelligence_app.command("topics")
def intelligence_topics(
    company: str,
    role: str | None = typer.Option(None, "--role"),
    cycle: str | None = typer.Option(None, "--cycle"),
    stage: str | None = typer.Option(None, "--stage"),
    since: int | None = typer.Option(
        None, "--since", help="Only include evidence from N days ago."
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        role_id = (
            session.scalar(select(RoleFamily.id).where(RoleFamily.slug == role)) if role else None
        )
        stage_id = (
            session.scalar(select(InterviewStage.id).where(InterviewStage.slug == stage))
            if stage
            else None
        )
        cutoff = datetime.now(UTC) - timedelta(days=since) if since else None
        rows = topic_frequency(
            session,
            canonical_company,
            role_family_id=role_id,
            cycle=cycle,
            stage_id=stage_id,
            since=cutoff,
        )
        payload = {
            "company": canonical_company.name,
            "note": "Frequencies are within collected evidence, not interview probabilities.",
            "topics": [{"topic": name, "count": count} for name, count in rows],
        }
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(payload["note"])
            for name, count in rows:
                typer.echo(f"{name}\t{count}")


@intelligence_app.command("process")
def intelligence_process(company: str, json_output: bool = typer.Option(False, "--json")) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        payload = process_evidence(session, canonical_company)
        typer.echo(
            json.dumps(payload, indent=2, sort_keys=True)
            if json_output
            else "\n".join(
                f"{item.get('role_family')} / {item.get('cycle') or 'unknown cycle'} / "
                f"{item.get('stage') or 'unknown stage'} / source {item.get('source_id')}"
                for item in payload
            )
        )


@prep_app.command("report")
def prep_report(company: str, role: str | None = typer.Option(None, "--role")) -> None:
    with session_scope() as session:
        canonical_company = resolve_company(session, company)
        role_id = (
            session.scalar(select(RoleFamily.id).where(RoleFamily.slug == role)) if role else None
        )
        typer.echo(
            json.dumps(
                preparation_report(session, canonical_company, role_id), indent=2, sort_keys=True
            )
        )


@email_app.command("connect")
def email_connect(
    provider: str = typer.Argument("gmail"),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open a browser window."),
) -> None:
    if provider.lower() != "gmail":
        raise typer.BadParameter(
            "only gmail is currently supported; use `email import` for provider-neutral EML"
        )
    try:
        result = connect_gmail(get_settings(), open_browser=not no_open)
    except GmailOAuthError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(result, indent=2))


@email_app.command("status")
def email_status() -> None:
    with get_local_session(get_settings()) as session:
        accounts = list(
            session.scalars(select(LocalEmailAccount).order_by(LocalEmailAccount.provider))
        )
        messages = session.scalar(select(func.count()).select_from(LocalEmailMessage)) or 0
    for account in accounts:
        account_status = (
            f"{account.provider}\t{account.address or 'unconfigured'}\t"
            f"{account.status}\t{account.last_synced_at or 'never'}"
            f"\thistory={account.history_id or 'none'}"
        )
        typer.echo(account_status)
    typer.echo(f"Local recruiting messages: {messages}")


@email_app.command("disconnect")
def email_disconnect(provider: str = typer.Argument("gmail")) -> None:
    if provider.lower() == "gmail":
        disconnect_gmail(get_settings())
        typer.echo("gmail: disconnected locally; stored messages were retained.")
        return
    with get_local_session(get_settings()) as session:
        accounts = list(
            session.scalars(select(LocalEmailAccount).where(LocalEmailAccount.provider == provider))
        )
        for account in accounts:
            account.status = "disconnected"
    typer.echo(f"{provider}: disconnected locally; stored messages were retained.")


@email_app.command("import")
def email_import(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise typer.BadParameter(f"email file not found: {path}")
    try:
        result = import_eml(path, get_settings())
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(result, indent=2, sort_keys=True, default=str))


@email_app.command("import-mbox")
def email_import_mbox(path: Path) -> None:
    import mailbox

    if not path.exists():
        raise typer.BadParameter(f"mbox not found: {path}")
    imported = 0
    with TemporaryDirectory() as temporary:
        temp_root = Path(temporary)
        for index, item in enumerate(mailbox.mbox(str(path))):
            eml_path = temp_root / f"{index}.eml"
            eml_path.write_bytes(item.as_bytes())
            import_eml(eml_path, get_settings())
            imported += 1
    typer.echo(f"Imported local mbox messages: {imported}")


@email_app.command("sync")
def email_sync() -> None:
    try:
        typer.echo(json.dumps(sync_authenticated_gmail(get_settings()), indent=2, default=str))
    except GmailOAuthError as exc:
        raise typer.BadParameter(str(exc)) from exc


@email_app.command("capture-fixture")
def email_capture_fixture(message_id: str) -> None:
    """Write a redacted local EML/metadata fixture; never auto-commit it."""
    try:
        result = capture_email_fixture(message_id, get_settings())
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(result, indent=2, default=str))


@email_app.command("unlinked")
def email_unlinked() -> None:
    with get_local_session(get_settings()) as session:
        rows = list(
            session.scalars(
                select(LocalEmailMessage)
                .where(~LocalEmailMessage.id.in_(select(LocalEmailLink.message_id)))
                .order_by(LocalEmailMessage.received_at.desc())
            )
        )
        for message in rows:
            classification = message.metadata_.get("classification", "unknown")
            typer.echo(f"{message.id}\t{message.subject}\t{classification}")
        typer.echo(f"Unlinked messages: {len(rows)}")


@timeline_app.command("show")
def timeline_show(
    application_id: str | None = typer.Option(None, "--application"),
    upcoming: bool = typer.Option(False, "--upcoming"),
) -> None:
    with get_local_session(get_settings()) as session:
        query = select(LocalTimelineEvent).order_by(
            LocalTimelineEvent.occurred_at, LocalTimelineEvent.deadline_at
        )
        if application_id:
            query = query.where(LocalTimelineEvent.application_id == UUID(application_id))
        rows = list(session.scalars(query))
        if upcoming:
            now = datetime.now(UTC)
            rows = [row for row in rows if (row.deadline_at or row.occurred_at or now) >= now]
        for row in rows:
            source = f"{row.source_type}:{row.source_id or '-'}"
            typer.echo(
                f"{row.occurred_at or '-'}\t{row.title}\t"
                f"deadline={row.deadline_at or '-'}\tsource={source}"
            )
        typer.echo(f"Timeline events: {len(rows)}")


@assessment_app.command("list")
def assessment_list() -> None:
    with get_local_session(get_settings()) as session:
        rows = list(session.scalars(select(LocalAssessment).order_by(LocalAssessment.due_at)))
        for item in rows:
            due = item.due_at or "-"
            typer.echo(
                f"{item.id}\t{item.provider}\t{item.assessment_type}\tdue={due}\t{item.status}"
            )
        typer.echo(f"Assessments: {len(rows)}")


@assessment_app.command("show")
def assessment_show(assessment_id: str) -> None:
    with get_local_session(get_settings()) as session:
        item = session.get(LocalAssessment, UUID(assessment_id))
        if item is None:
            raise typer.BadParameter("assessment not found locally")
        typer.echo(
            json.dumps(
                {
                    "id": str(item.id),
                    "application_id": str(item.application_id),
                    "provider": item.provider,
                    "type": item.assessment_type,
                    "due_at": item.due_at,
                    "url": item.url,
                    "status": item.status,
                },
                indent=2,
                default=str,
            )
        )


@assessment_app.command("complete")
def assessment_complete(assessment_id: str) -> None:
    with get_local_session(get_settings()) as session:
        item = session.get(LocalAssessment, UUID(assessment_id))
        if item is None:
            raise typer.BadParameter("assessment not found locally")
        item.status = "completed"
        item.completed_at = datetime.now(UTC)
    typer.echo("Assessment marked completed locally.")


@interview_app.command("list")
def interview_list() -> None:
    with get_local_session(get_settings()) as session:
        rows = list(
            session.scalars(
                select(LocalInterviewAppointment).order_by(LocalInterviewAppointment.starts_at)
            )
        )
        for item in rows:
            summary = (
                f"{item.id}\t{item.interview_stage}\t{item.starts_at} "
                f"({item.timezone_name})\t{item.confirmation_status}"
            )
            typer.echo(summary)
        typer.echo(f"Interviews: {len(rows)}")


@interview_app.command("show")
def interview_show(interview_id: str) -> None:
    with get_local_session(get_settings()) as session:
        item = session.get(LocalInterviewAppointment, UUID(interview_id))
        if item is None:
            raise typer.BadParameter("interview appointment not found locally")
        typer.echo(
            json.dumps(
                {
                    "id": str(item.id),
                    "application_id": str(item.application_id),
                    "stage": item.interview_stage,
                    "starts_at": item.starts_at,
                    "ends_at": item.ends_at,
                    "timezone": item.timezone_name,
                    "meeting_url": item.meeting_url,
                    "status": item.confirmation_status,
                },
                indent=2,
                default=str,
            )
        )


@interview_app.command("prepare")
def interview_prepare(interview_id: str) -> None:
    with get_local_session(get_settings()) as session:
        item = session.get(LocalInterviewAppointment, UUID(interview_id))
        if item is None:
            raise typer.BadParameter("interview appointment not found locally")
        application_id = item.application_id
    typer.echo(
        json.dumps(
            build_prep_plan(
                application_id,
                get_settings(),
                target="interview",
                target_id=UUID(interview_id),
                daily_minutes=get_settings().prep_daily_minutes,
            ),
            indent=2,
        )
    )


@interview_app.command("calendar")
def interview_calendar(interview_id: str) -> None:
    typer.echo(str(export_interview_ics(UUID(interview_id), get_settings())))


@calendar_app.command("export")
def calendar_export(interview_id: str) -> None:
    typer.echo(str(export_interview_ics(UUID(interview_id), get_settings())))


@prep_app.command("today")
def prep_today() -> None:
    with get_local_session(get_settings()) as session:
        plans = list(
            session.scalars(
                select(LocalPrepPlan).order_by(LocalPrepPlan.created_at.desc()).limit(20)
            )
        )
        for plan in plans:
            typer.echo(
                f"{plan.id}\t{plan.title}\t{plan.status}\tdaily_minutes={plan.daily_minutes or 0}"
            )
        typer.echo(f"Preparation plans: {len(plans)}")


@prep_app.command("interview")
def prep_interview(application_id: str) -> None:
    typer.echo(
        json.dumps(
            build_prep_plan(
                UUID(application_id),
                get_settings(),
                target="interview",
                daily_minutes=get_settings().prep_daily_minutes,
            ),
            indent=2,
        )
    )


@prep_app.command("assessment")
def prep_assessment(assessment_id: str) -> None:
    with get_local_session(get_settings()) as session:
        assessment = session.get(LocalAssessment, UUID(assessment_id))
        if assessment is None:
            raise typer.BadParameter("assessment not found locally")
        application_id = assessment.application_id
    typer.echo(
        json.dumps(
            build_prep_plan(
                application_id,
                get_settings(),
                target="assessment",
                target_id=UUID(assessment_id),
                daily_minutes=get_settings().prep_daily_minutes,
            ),
            indent=2,
        )
    )


@notifications_app.command("list")
def notifications_list(deliver: bool = typer.Option(False, "--deliver")) -> None:
    if deliver:
        typer.echo(json.dumps(deliver_due_reminders(get_settings()), indent=2))
    with get_local_session(get_settings()) as session:
        rows = list(
            session.scalars(
                select(LocalNotification)
                .where(LocalNotification.dismissed_at.is_(None))
                .order_by(LocalNotification.created_at.desc())
                .limit(100)
            )
        )
        for row in rows:
            read_state = "read" if row.read_at else "unread"
            typer.echo(f"{row.created_at}\t{row.notification_type}\t{row.title}\t{read_state}")
        typer.echo(f"Notifications: {len(rows)}")


@refresh_app.command("due")
def refresh_due() -> None:
    from quant_recruiting.db.models import RefreshTarget
    from quant_recruiting.refresh import is_due

    with session_scope() as session:
        now = datetime.now(UTC)
        for target in session.scalars(select(RefreshTarget).order_by(RefreshTarget.next_due_at)):
            if is_due(target, now):
                typer.echo(f"{target.entity_type}\t{target.entity_id}")


@refresh_app.command("run")
def refresh_run(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    from quant_recruiting.db.models import RefreshTarget
    from quant_recruiting.refresh import is_due

    with session_scope() as session:
        now = datetime.now(UTC)
        due = [target for target in session.scalars(select(RefreshTarget)) if is_due(target, now)]
        for target in due:
            typer.echo(
                f"{'would refresh' if dry_run else 'refreshing'} "
                f"{target.entity_type} {target.entity_id}"
            )
        typer.echo(f"Due targets: {len(due)}")


if __name__ == "__main__":
    app()
