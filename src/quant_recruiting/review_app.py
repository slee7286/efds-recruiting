"""Small localhost-only review workspace for V6 artifacts."""

from __future__ import annotations

from html import escape
from urllib.parse import parse_qs
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from quant_recruiting.artifacts import (
    application_readiness,
    approve_answer,
    approve_artifact,
    edit_answer,
)
from quant_recruiting.db.models import Application, ApplicationAnswer, ApplicationArtifact
from quant_recruiting.storage import private_session_scope


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset='utf-8'><title>{escape(title)}</title>"
        "<style>body{font-family:system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:.5rem;text-align:left}"  # noqa: E501
        "a{color:#0645ad}textarea{width:100%;min-height:8rem} .ready{color:green}.blocked{color:#a00}"  # noqa: E501
        "</style></head><body>"
        f"{body}</body></html>"
    )


def create_review_app() -> FastAPI:
    app = FastAPI(title="Recruiting Intelligence Review Workspace", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> HTMLResponse:
        with private_session_scope() as session:
            rows = []
            for application in session.scalars(
                select(Application).join(Application.job).order_by(Application.updated_at.desc())
            ):
                readiness = application_readiness(session, application)
                state = (
                    "ready_to_apply" if readiness["status"] == "READY TO APPLY" else "needs_review"
                )
                rows.append(
                    f"<tr><td><a href='/applications/{application.id}'>{escape(application.job.company.name)}</a></td>"  # noqa: E501
                    f"<td>{escape(application.job.title)}</td><td>{escape(application.job.location_text or '-')}</td>"  # noqa: E501
                    f"<td>{escape(application.status)}</td><td class='{'ready' if state == 'ready_to_apply' else 'blocked'}'>{state}</td>"  # noqa: E501
                    f"<td>{len(readiness['blocking_gaps'])}</td></tr>"
                )
            body = "<h1>Application review workspace</h1><p>Local-only V6 review surface.</p>"
            body += "<table><tr><th>Company</th><th>Role</th><th>Location</th><th>Status</th><th>Review state</th><th>Blocking gaps</th></tr>"  # noqa: E501
            body += "".join(rows) + "</table>"
            return _page("Applications", body)

    @app.get("/applications/{application_id}", response_class=HTMLResponse)
    def application_page(application_id: UUID) -> HTMLResponse:
        with private_session_scope() as session:
            application = session.get(Application, application_id)
            if application is None:
                return _page("Not found", "<h1>Application not found</h1>")
            readiness = application_readiness(session, application)
            body = f"<p><a href='/'>Back</a></p><h1>{escape(application.job.company.name)} — {escape(application.job.title)}</h1>"  # noqa: E501
            body += f"<p>Role family: {escape(application.job.role_family)} | Status: {escape(application.status)}</p>"  # noqa: E501
            body += f"<h2>Readiness: <span class='{'ready' if readiness['status'] == 'READY TO APPLY' else 'blocked'}'>{readiness['status']}</span></h2>"  # noqa: E501
            body += f"<pre>{escape(str(readiness))}</pre><h2>Written answers</h2>"
            for answer in session.scalars(
                select(ApplicationAnswer)
                .join(ApplicationAnswer.question)
                .where(
                    ApplicationAnswer.application_question_id.in_(
                        [q.id for q in application.questions]
                    )
                )
                .order_by(ApplicationAnswer.created_at.desc())
            ):
                body += _answer_card(answer)
            body += "<h2>Artifacts</h2><ul>"
            for artifact in session.scalars(
                select(ApplicationArtifact)
                .where(ApplicationArtifact.application_id == application.id)
                .order_by(ApplicationArtifact.created_at.desc())
            ):
                body += f"<li>{escape(artifact.artifact_type)} v{artifact.version}: {escape(artifact.status)} ({escape(artifact.rendered_path or artifact.source_path or '-')})"  # noqa: E501
                if artifact.status == "validated":
                    body += f" <form method='post' action='/artifacts/{artifact.id}/approve' style='display:inline'><button>Approve</button></form>"  # noqa: E501
                body += "</li>"
            body += "</ul>"
            return _page("Application review", body)

    @app.post("/artifacts/{artifact_id}/approve")
    def artifact_approve(artifact_id: UUID) -> RedirectResponse:
        with private_session_scope() as session:
            artifact = approve_artifact(session, artifact_id, "reviewer")
            return RedirectResponse(f"/applications/{artifact.application_id}", status_code=303)

    @app.post("/answers/{answer_id}/approve")
    def answer_approve(answer_id: UUID) -> RedirectResponse:
        with private_session_scope() as session:
            answer = approve_answer(session, answer_id, "reviewer")
            return RedirectResponse(
                f"/applications/{answer.question.application_id}", status_code=303
            )

    @app.post("/answers/{answer_id}/edit")
    async def answer_edit(answer_id: UUID, request: Request) -> RedirectResponse:
        body = parse_qs((await request.body()).decode("utf-8"))
        text = body.get("answer_text", [""])[0]
        with private_session_scope() as session:
            answer = edit_answer(session, answer_id, text, "reviewer")
            return RedirectResponse(
                f"/applications/{answer.question.application_id}", status_code=303
            )

    return app


def _answer_card(answer: ApplicationAnswer) -> str:
    question = answer.question
    actions = ""
    if not answer.approved:
        actions += f"<form method='post' action='/answers/{answer.id}/approve'><button>Approve answer</button></form>"  # noqa: E501
    actions += f"<form method='post' action='/answers/{answer.id}/edit'><textarea name='answer_text'>{escape(answer.answer_text)}</textarea><button>Save new draft</button></form>"  # noqa: E501
    return f"<article><h3>{escape(question.question_text)}</h3><p>Category: {escape(question.category)} | Version: {answer.version} | Approved: {answer.approved}</p><p>{escape(answer.answer_text)}</p>{actions}</article><hr>"  # noqa: E501
