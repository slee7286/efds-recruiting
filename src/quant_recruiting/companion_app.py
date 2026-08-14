"""Local-first Recruiting Assistant localhost companion UI."""

from __future__ import annotations

import secrets
from html import escape
from typing import cast
from urllib.parse import parse_qs
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from quant_recruiting.ai_workspace import list_conversations
from quant_recruiting.application_service import record_application_event
from quant_recruiting.ats_capabilities import capability_report
from quant_recruiting.browser_engine import (
    BrowserAutomationError,
    resolve_field,
    run_browser,
)
from quant_recruiting.config import Settings, get_settings
from quant_recruiting.db.models import (
    AITask,
    Application,
    CandidateProfile,
    Company,
    Job,
)
from quant_recruiting.local_models import (
    LocalApplicationReference,
    LocalAssessment,
    LocalBackgroundRun,
    LocalBrowserField,
    LocalBrowserRun,
    LocalEmailLink,
    LocalEmailMessage,
    LocalInterviewAppointment,
    LocalNotification,
    LocalPrepPlan,
    LocalTimelineEvent,
)
from quant_recruiting.local_ops import local_doctor
from quant_recruiting.storage import get_local_session, private_session_scope
from quant_recruiting.sync import sync_status


def _page(title: str, body: str, *, banner: str = "") -> HTMLResponse:
    banner_html = f"<aside class='banner'>{escape(banner)}</aside>" if banner else ""
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title)} — Recruiting Assistant</title>"
        "<style>body{font-family:system-ui;max-width:1180px;margin:0 auto;padding:1.5rem;"
        "color:#17202a}nav{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1.5rem}"
        "nav a{color:#0645ad}table{border-collapse:collapse;width:100%;margin:1rem 0}"
        "td,th{border:1px solid #d9dee3;padding:.55rem;text-align:left}"
        ".banner{background:#fff3cd;border:1px solid #ffe69c;padding:.7rem;margin-bottom:1rem}"
        ".card{border:1px solid #d9dee3;border-radius:.5rem;padding:1rem;margin:.8rem 0}"
        ".muted{color:#5f6b76}button{padding:.45rem .7rem}input{padding:.45rem}"
        "</style></head><body>"
        "<nav><a href='/'>Home</a><a href='/jobs'>Jobs</a><a href='/companies'>Companies</a>"
        "<a href='/applications'>Applications</a><a href='/email'>Email</a>"
        "<a href='/timeline'>Timeline</a><a href='/assessments'>Assessments</a>"
        "<a href='/interviews'>Interviews</a><a href='/preparation'>Preparation</a>"
        "<a href='/notifications'>Notifications</a><a href='/ai'>AI Workspace</a>"
        "<a href='/browser'>Browser Runs</a><a href='/background'>Background</a>"
        "<a href='/conversations'>Conversations</a><a href='/local-data'>Local Data</a>"
        "<a href='/settings'>Settings</a></nav>"
        f"{banner_html}{body}</body></html>"
    )


def _csrf(app: FastAPI) -> str:
    return cast(str, app.state.csrf_token)


def _require_csrf(app: FastAPI, request: Request) -> None:
    body = parse_qs((request.state.raw_body or b"").decode("utf-8"))
    if body.get("csrf", [""])[0] != _csrf(app):
        raise HTTPException(status_code=403, detail="invalid local form token")


async def _form_body(request: Request) -> None:
    request.state.raw_body = await request.body()


def create_companion_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    app = FastAPI(title="Recruiting Assistant", docs_url=None, redoc_url=None)
    app.state.csrf_token = secrets.token_urlsafe(32)
    allowed_hosts = [config.local_host, "localhost"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    def banner() -> str:
        if config.offline_mode:
            return "OFFLINE — using cached shared intelligence; local workflows remain available."
        statuses = sync_status(config)
        if not statuses:
            return "Shared intelligence has not been synchronized yet."
        return "Shared intelligence cache available; freshness is shown in Local Data."

    @app.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        with get_local_session(config) as session:
            counts = {
                "applications": session.scalar(select(func.count()).select_from(Application)) or 0,
                "jobs": session.scalar(select(func.count()).select_from(Job)) or 0,
                "companies": session.scalar(select(func.count()).select_from(Company)) or 0,
                "tasks": session.scalar(select(func.count()).select_from(AITask)) or 0,
            }
        body = "<h1>Recruiting Assistant</h1>"
        body += "<p>Your CVs, applications, answers, AI conversations, browser activity, "
        body += "and preparation history are stored locally on this device by default.</p>"
        body += "<div class='card'><h2>Workspace</h2><ul>"
        links = {
            "applications": "/applications",
            "jobs": "/jobs",
            "companies": "/companies",
            "tasks": "/ai",
        }
        body += "".join(
            f"<li><a href='{links[key]}'>{key.title()}</a>: {value}</li>"
            for key, value in counts.items()
        )
        body += "</ul></div>"
        body += "<div class='card'><h2>Get started</h2><p><a href='/jobs'>Browse synced jobs</a> · "
        body += "<a href='/onboarding'>Complete local onboarding</a> · "
        body += "<a href='/local-data'>Check local storage</a></p></div>"
        return _page("Home", body, banner=banner())

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs() -> HTMLResponse:
        with private_session_scope(config) as session:
            rows = list(session.scalars(select(Job).order_by(Job.updated_at.desc()).limit(100)))
        body = (
            "<h1>Jobs</h1><p class='muted'>Public jobs cached locally from shared intelligence.</p>"
        )
        body += "<table><tr><th>Company</th><th>Role</th><th>Location</th><th>Status</th><th>Action</th></tr>"  # noqa: E501
        for job in rows:
            body += "<tr>"
            body += f"<td>{escape(job.company.name)}</td><td>{escape(job.title)}</td>"
            body += f"<td>{escape(job.location_text or '-')}</td><td>{escape(job.status)}</td>"
            body += f"<td><form method='post' action='/jobs/{job.id}/apply'>"
            body += f"<input type='hidden' name='csrf' value='{escape(_csrf(app))}'>"
            body += "<button>Create local application</button></form></td></tr>"
        body += "</table>"
        return _page("Jobs", body, banner=banner())

    @app.post("/jobs/{job_id}/apply")
    async def create_application(job_id: UUID, request: Request) -> RedirectResponse:
        await _form_body(request)
        _require_csrf(app, request)
        with private_session_scope(config) as session:
            job = session.get(Job, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="job not found in local cache")
            application = session.scalar(select(Application).where(Application.job_id == job.id))
            if application is None:
                application = Application(job=job, application_url=job.job_url)
                session.add(application)
                session.flush()
                record_application_event(
                    session,
                    application,
                    event_type="created",
                    source_type="local_ui",
                    new_status="discovered",
                )
                session.add(
                    LocalApplicationReference(
                        application_id=application.id,
                        shared_company_id=str(job.company_id),
                        shared_job_id=str(job.id),
                        shared_source_server="shared-cache",
                    )
                )
            return RedirectResponse(f"/applications/{application.id}", status_code=303)

    @app.get("/companies", response_class=HTMLResponse)
    def companies() -> HTMLResponse:
        with private_session_scope(config) as session:
            rows = list(session.scalars(select(Company).order_by(Company.name).limit(100)))
        body = "<h1>Companies</h1><table><tr><th>Name</th><th>Domain</th><th>Jobs</th></tr>"
        for company in rows:
            body += f"<tr><td>{escape(company.name)}</td><td>{escape(company.primary_domain or '-')}</td>"  # noqa: E501
            body += f"<td>{len(company.jobs)}</td></tr>"
        return _page("Companies", body + "</table>", banner=banner())

    @app.get("/applications", response_class=HTMLResponse)
    def applications() -> HTMLResponse:
        with private_session_scope(config) as session:
            rows = list(
                session.scalars(select(Application).order_by(Application.updated_at.desc()))
            )
        body = "<h1>Applications</h1><table><tr><th>Company</th><th>Role</th><th>Status</th><th>Priority</th></tr>"  # noqa: E501
        for item in rows:
            body += f"<tr><td><a href='/applications/{item.id}'>{escape(item.job.company.name)}</a></td>"  # noqa: E501
            body += f"<td>{escape(item.job.title)}</td><td>{escape(item.status)}</td><td>{item.priority}</td></tr>"  # noqa: E501
        return _page("Applications", body + "</table>", banner=banner())

    @app.get("/applications/{application_id}", response_class=HTMLResponse)
    def application(application_id: UUID) -> HTMLResponse:
        with private_session_scope(config) as session:
            item = session.get(Application, application_id)
            if item is None:
                raise HTTPException(status_code=404, detail="application not found")
            body = f"<h1>{escape(item.job.company.name)} — {escape(item.job.title)}</h1>"
            body += f"<p>Status: <strong>{escape(item.status)}</strong> · <a href='{escape(item.job.job_url)}'>Job URL</a></p>"  # noqa: E501
            body += "<p>Use the existing local review workspace for artifact approval and readiness gates.</p>"  # noqa: E501
            body += (
                f"<p><a href='/applications/{item.id}/browser'>Browser autofill</a> · "
                "<a href='/'>Back to dashboard</a> · <a href='/ai'>Prepare AI task</a></p>"
            )
            return _page("Application", body, banner=banner())

    @app.get("/applications/{application_id}/browser", response_class=HTMLResponse)
    def browser_page(application_id: UUID) -> HTMLResponse:
        with get_local_session(config) as session:
            item = session.get(Application, application_id)
            if item is None:
                raise HTTPException(status_code=404, detail="application not found")
            runs = list(
                session.scalars(
                    select(LocalBrowserRun)
                    .where(LocalBrowserRun.application_id == application_id)
                    .order_by(LocalBrowserRun.created_at.desc())
                    .limit(20)
                )
            )
            fields = (
                list(
                    session.scalars(
                        select(LocalBrowserField)
                        .where(LocalBrowserField.run_id == runs[0].id)
                        .order_by(LocalBrowserField.created_at)
                    )
                )
                if runs
                else []
            )
        body = (
            f"<h1>Browser autofill — {escape(item.job.company.name)} / "
            f"{escape(item.job.title)}</h1>"
        )
        body += "<p>Browser automation is local-only and always stops before final submission.</p>"
        body += (
            f"<form method='post' action='/applications/{application_id}/browser/start'>"
            f"<input type='hidden' name='csrf' value='{escape(_csrf(app))}'>"
            "<button>Start autofill</button></form>"
        )
        body += (
            "<h2>Run history</h2><table><tr><th>Run</th><th>ATS</th>"
            "<th>Status</th><th>Step</th></tr>"
        )
        for run in runs:
            body += (
                f"<tr><td>{run.id}</td><td>{escape(run.detected_ats or '-')}</td>"
                f"<td>{escape(run.status)}</td><td>{escape(run.current_step or '-')}</td></tr>"
            )
        if fields:
            body += "</table><h2>Unresolved fields</h2>"
            unresolved = [
                field
                for field in fields
                if field.required
                or field.field_type in {"sensitive", "legal_attestation", "consent"}
            ]
            if unresolved:
                for field in unresolved:
                    body += (
                        f"<div class='card'><strong>{escape(field.original_label)}</strong> "
                        f"<span class='muted'>({escape(field.field_type)})</span>"
                        f"<form method='post' action='/applications/"
                        f"{application_id}/browser/resolve'>"
                        f"<input type='hidden' name='csrf' value='{escape(_csrf(app))}'>"
                        f"<input type='hidden' name='run_id' value='{field.run_id}'>"
                        f"<input type='hidden' name='field_key' value='{escape(field.field_key)}'>"
                        "<input name='value' required placeholder='Explicit answer'>"
                        "<button>Save locally</button></form></div>"
                    )
            else:
                body += "<p>No unresolved fields surfaced.</p>"
        body += "<p><a href='/applications/" + str(application_id) + "'>Back to application</a></p>"
        return _page("Browser autofill", body, banner=banner())

    @app.post("/applications/{application_id}/browser/resolve")
    async def browser_resolve(application_id: UUID, request: Request) -> RedirectResponse:
        await _form_body(request)
        _require_csrf(app, request)
        form = parse_qs(request.state.raw_body.decode("utf-8"))
        run_id = UUID(form.get("run_id", [""])[0])
        result = resolve_field(
            run_id,
            form.get("field_key", [""])[0],
            form.get("value", [""])[0],
            settings=config,
        )
        if result["run_id"] != str(run_id) or result["application_id"] != str(application_id):
            raise HTTPException(status_code=400, detail="invalid browser run")
        return RedirectResponse(f"/applications/{application_id}/browser", status_code=303)

    @app.post("/applications/{application_id}/browser/start")
    async def browser_start(application_id: UUID, request: Request) -> HTMLResponse:
        await _form_body(request)
        _require_csrf(app, request)
        try:
            result = run_browser(application_id, config)
            message = str(result)
        except BrowserAutomationError as exc:
            message = str(exc)
        return _page(
            "Browser autofill",
            f"<h1>Browser run</h1><pre>{escape(message)}</pre>"
            f"<p><a href='/applications/{application_id}/browser'>Refresh</a></p>",
            banner=banner(),
        )

    @app.get("/browser", response_class=HTMLResponse)
    def browser_runs() -> HTMLResponse:
        with get_local_session(config) as session:
            runs = list(
                session.scalars(
                    select(LocalBrowserRun).order_by(LocalBrowserRun.updated_at.desc()).limit(100)
                )
            )
        body = "<h1>Browser Runs</h1><p class='muted'>All runs and diagnostics are local-only.</p>"
        body += "<p><a href='/browser/capabilities'>ATS capability registry</a></p>"
        body += (
            "<table><tr><th>Run</th><th>Application</th><th>ATS</th>"
            "<th>Status</th><th>Step</th></tr>"
        )
        for run in runs:
            body += (
                f"<tr><td>{run.id}</td><td><a href='/applications/{run.application_id}'>"
                f"{run.application_id}</a></td><td>{escape(run.detected_ats or '-')}</td>"
                f"<td>{escape(run.status)}</td><td>{escape(run.current_step or '-')}</td></tr>"
            )
        return _page("Browser Runs", body + "</table>", banner=banner())

    @app.get("/browser/capabilities", response_class=HTMLResponse)
    def browser_capabilities() -> HTMLResponse:
        body = "<h1>ATS Capabilities</h1><table><tr><th>Provider</th><th>Detection</th>"
        body += (
            "<th>Documents</th><th>Questions</th><th>Verification</th>"
            "<th>Fixtures</th><th>Real</th><th>Notes</th></tr>"
        )
        for item in capability_report(config):
            body += (
                f"<tr><td>{escape(str(item['provider']))}</td>"
                f"<td>{escape(str(item['detection']))}</td>"
                f"<td>{escape(str(item['documents']))}</td>"
                f"<td>{escape(str(item['custom_questions']))}</td>"
                f"<td>{escape(str(item['verification']))}</td>"
                f"<td>{item['fixture_count']}</td><td>{item['real_world_fixture_count']}</td>"
                f"<td>{escape(str(item['notes']))}</td></tr>"
            )
        return _page("ATS Capabilities", body + "</table>", banner=banner())

    @app.get("/background", response_class=HTMLResponse)
    def background() -> HTMLResponse:
        with get_local_session(config) as session:
            runs = list(
                session.scalars(
                    select(LocalBackgroundRun)
                    .order_by(LocalBackgroundRun.started_at.desc())
                    .limit(30)
                )
            )
        body = (
            "<h1>Background Services</h1><p class='muted'>Email, reminders, alerts, "
            "and public sync run locally.</p>"
        )
        body += "<table><tr><th>Started</th><th>Trigger</th><th>Status</th><th>Completed</th></tr>"
        for run in runs:
            body += (
                f"<tr><td>{escape(str(run.started_at))}</td><td>{escape(run.trigger)}</td>"
                f"<td>{escape(run.status)}</td><td>{escape(str(run.completed_at or '-'))}</td></tr>"
            )
        return _page("Background Services", body + "</table>", banner=banner())

    @app.get("/ai", response_class=HTMLResponse)
    def ai_workspace() -> HTMLResponse:
        with private_session_scope(config) as session:
            tasks = list(
                session.scalars(select(AITask).order_by(AITask.created_at.desc()).limit(50))
            )
        body = "<h1>AI Workspace</h1><p>Tasks and provider handoff remain local. "
        body += "<a href='/conversations'>Search conversations</a></p><table>"
        body += "<tr><th>Task</th><th>Type</th><th>Status</th><th>Entity</th></tr>"
        for task in tasks:
            body += f"<tr><td>{task.id}</td><td>{escape(task.task_type)}</td>"
            body += f"<td>{escape(task.status)}</td><td>{escape(task.entity_type)}</td></tr>"
        return _page("AI Workspace", body + "</table>", banner=banner())

    @app.get("/conversations", response_class=HTMLResponse)
    def conversations() -> HTMLResponse:
        rows = list_conversations(config)[:50]
        body = "<h1>Conversation Library</h1><p class='muted'>Local-only imported AI context.</p><table>"  # noqa: E501
        body += "<tr><th>Provider</th><th>Title</th><th>Captured</th><th>Linked</th></tr>"
        for row in rows:
            body += f"<tr><td>{escape(str(row.get('provider', '-')))}</td>"
            body += f"<td>{escape(str(row.get('title', '-')))}</td>"
            body += f"<td>{escape(str(row.get('captured_at', '-')))}</td>"
            body += f"<td>{escape(str(row.get('application_id', '-')))}</td></tr>"
        return _page("Conversations", body + "</table>", banner=banner())

    @app.get("/email", response_class=HTMLResponse)
    def email_inbox() -> HTMLResponse:
        with get_local_session(config) as session:
            rows = list(
                session.scalars(
                    select(LocalEmailMessage)
                    .order_by(LocalEmailMessage.received_at.desc())
                    .limit(100)
                )
            )
            links = {
                link.message_id: link for link in session.scalars(select(LocalEmailLink)).all()
            }
        body = (
            "<h1>Recruiting Email</h1><p class='muted'>"
            "Email content is stored and processed locally.</p>"
        )
        body += (
            "<table><tr><th>Date</th><th>From</th><th>Subject</th>"
            "<th>Classification</th><th>Application</th></tr>"
        )
        for message in rows:
            link = links.get(message.id)
            body += (
                f"<tr><td>{escape(str(message.received_at))}</td>"
                f"<td>{escape(message.sender_email or '-')}</td>"
                f"<td>{escape(message.subject or '-')}</td>"
                f"<td>{escape(str(message.metadata_.get('classification', 'unknown')))}</td>"
                f"<td>{escape(str(link.application_id if link else 'unresolved'))}</td></tr>"
            )
        return _page("Recruiting Email", body + "</table>", banner=banner())

    @app.get("/timeline", response_class=HTMLResponse)
    def timeline() -> HTMLResponse:
        with get_local_session(config) as session:
            rows = list(
                session.scalars(
                    select(LocalTimelineEvent)
                    .order_by(LocalTimelineEvent.occurred_at.desc())
                    .limit(100)
                )
            )
        body = (
            "<h1>Recruiting Timeline</h1><p class='muted'>"
            "Local operational events and deadlines.</p>"
        )
        body += "<table><tr><th>When</th><th>Event</th><th>Deadline</th><th>Source</th></tr>"
        for row in rows:
            body += (
                f"<tr><td>{escape(str(row.occurred_at or '-'))}</td>"
                f"<td>{escape(row.title)}</td><td>{escape(str(row.deadline_at or '-'))}</td>"
                f"<td>{escape(str(row.source_type) + ':' + str(row.source_id or '-'))}</td></tr>"
            )
        return _page("Timeline", body + "</table>", banner=banner())

    @app.get("/assessments", response_class=HTMLResponse)
    def assessments() -> HTMLResponse:
        with get_local_session(config) as session:
            rows = list(session.scalars(select(LocalAssessment).order_by(LocalAssessment.due_at)))
        body = (
            "<h1>Assessments</h1><table><tr><th>Provider</th><th>Type</th>"
            "<th>Due</th><th>Status</th></tr>"
        )
        for row in rows:
            body += (
                f"<tr><td>{escape(row.provider)}</td>"
                f"<td>{escape(row.assessment_type)}</td>"
                f"<td>{escape(str(row.due_at or '-'))}</td>"
                f"<td>{escape(row.status)}</td></tr>"
            )
        return _page("Assessments", body + "</table>", banner=banner())

    @app.get("/interviews", response_class=HTMLResponse)
    def interviews() -> HTMLResponse:
        with get_local_session(config) as session:
            rows = list(
                session.scalars(
                    select(LocalInterviewAppointment).order_by(LocalInterviewAppointment.starts_at)
                )
            )
        body = (
            "<h1>Interviews</h1><table><tr><th>Stage</th><th>When</th>"
            "<th>Timezone</th><th>Status</th></tr>"
        )
        for row in rows:
            body += (
                f"<tr><td>{escape(row.interview_stage)}</td>"
                f"<td>{escape(str(row.starts_at))}</td>"
                f"<td>{escape(row.timezone_name)}</td>"
                f"<td>{escape(row.confirmation_status)}</td></tr>"
            )
        return _page("Interviews", body + "</table>", banner=banner())

    @app.get("/preparation", response_class=HTMLResponse)
    def preparation() -> HTMLResponse:
        with get_local_session(config) as session:
            rows = list(
                session.scalars(select(LocalPrepPlan).order_by(LocalPrepPlan.created_at.desc()))
            )
        body = (
            "<h1>Preparation</h1><p class='muted'>Plans are deterministic and use "
            "local/shared cached intelligence.</p>"
        )
        body += "<table><tr><th>Plan</th><th>Status</th><th>Daily minutes</th><th>Due</th></tr>"
        for row in rows:
            body += (
                f"<tr><td>{escape(row.title)}</td><td>{escape(row.status)}</td>"
                f"<td>{row.daily_minutes or 0}</td>"
                f"<td>{escape(str(row.due_at or '-'))}</td></tr>"
            )
        return _page("Preparation", body + "</table>", banner=banner())

    @app.get("/notifications", response_class=HTMLResponse)
    def notifications() -> HTMLResponse:
        with get_local_session(config) as session:
            rows = list(
                session.scalars(
                    select(LocalNotification)
                    .where(LocalNotification.dismissed_at.is_(None))
                    .order_by(LocalNotification.created_at.desc())
                    .limit(100)
                )
            )
        body = (
            "<h1>Notifications</h1><table><tr><th>Created</th>"
            "<th>Type</th><th>Title</th><th>State</th></tr>"
        )
        for row in rows:
            state = "read" if row.read_at else "unread"
            body += (
                f"<tr><td>{escape(str(row.created_at))}</td>"
                f"<td>{escape(row.notification_type)}</td>"
                f"<td>{escape(row.title)}</td><td>{state}</td></tr>"
            )
        return _page("Notifications", body + "</table>", banner=banner())

    @app.get("/local-data", response_class=HTMLResponse)
    def local_data() -> HTMLResponse:
        diagnostics = local_doctor(config)
        body = (
            "<h1>Local Data & Privacy</h1><p>Private data is not uploaded by this application.</p>"
        )
        body += "<div class='card'><pre>" + escape(str(diagnostics)) + "</pre></div>"
        body += f"<p>Local directory: <code>{escape(str(config.local_data_dir))}</code></p>"
        body += "<p><a href='/settings'>Settings</a> · use the CLI for backup/export/doctor/cleanup.</p>"  # noqa: E501
        return _page("Local Data", body, banner=banner())

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page() -> HTMLResponse:
        body = "<h1>Settings</h1><table>"
        for label, value in (
            ("Shared transport", config.shared_transport),
            ("Shared API URL", config.shared_api_url or "not configured"),
            ("Default AI provider", config.ai_default_provider),
            ("Offline mode", config.offline_mode),
            ("Local host", config.local_host),
            ("Local port", config.local_port),
        ):
            body += f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        body += "</table><p>Credentials are intentionally not displayed here.</p>"
        return _page("Settings", body)

    @app.get("/onboarding", response_class=HTMLResponse)
    def onboarding() -> HTMLResponse:
        with private_session_scope(config) as session:
            profile = session.scalar(select(CandidateProfile).order_by(CandidateProfile.created_at))
        if profile:
            return _page(
                "Onboarding", "<h1>Onboarding complete</h1><p>Your profile is stored locally.</p>"
            )
        csrf = escape(_csrf(app))
        body = "<h1>Welcome</h1><p>Set up optional local profile basics. Nothing is sent to the shared service.</p>"  # noqa: E501
        body += (
            "<form method='post' action='/onboarding'><input type='hidden' name='csrf' value='"
            + csrf
            + "'>"
        )
        for name, label in (
            ("preferred_name", "Preferred name"),
            ("email", "Email"),
            ("university", "University"),
        ):
            body += f"<p><label>{label}<br><input name='{name}'></label></p>"
        body += "<button>Save locally</button></form>"
        return _page("Onboarding", body)

    @app.post("/onboarding")
    async def save_onboarding(request: Request) -> RedirectResponse:
        await _form_body(request)
        _require_csrf(app, request)
        form = parse_qs(request.state.raw_body.decode("utf-8"))
        with private_session_scope(config) as session:
            session.add(
                CandidateProfile(
                    preferred_name=form.get("preferred_name", [None])[0] or None,
                    email=form.get("email", [None])[0] or None,
                    university=form.get("university", [None])[0] or None,
                )
            )
        return RedirectResponse("/", status_code=303)

    return app
