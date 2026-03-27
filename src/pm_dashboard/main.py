from __future__ import annotations

import base64
import secrets
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from .config import Settings, get_settings
from .database import init_db, make_engine, make_session_factory
from .projects import repo_file_project_rows
from .repository import get_latest_snapshot, list_projects, list_resources, list_tasks_for_snapshot
from .seed import ensure_seed_projects
from .services import (
    ActionCreate,
    ProjectCreate,
    ResourceCreate,
    TaskCreate,
    DecisionCreate,
    RiskCreate,
    WeeklyUpdateCreate,
    accept_suggestion,
    accept_portfolio_summary_draft,
    attention_queue,
    cockpit_view,
    create_action,
    create_project,
    create_resource,
    create_decision,
    create_task,
    create_risk,
    dependencies_view,
    current_week_start,
    detect_resource_conflicts,
    dismiss_suggestion,
    dismiss_portfolio_summary_draft,
    get_action_or_404,
    get_decision_or_404,
    get_project_or_404,
    get_resource_or_404,
    get_risk_or_404,
    get_suggestion_or_404,
    get_task_or_404,
    get_weekly_update_or_404,
    import_history,
    import_schedule,
    parse_date,
    portfolio_view,
    create_portfolio_summary_draft,
    project_detail,
    project_workflow_view,
    resolve_project_for_import,
    save_upload,
    serialize_decision,
    serialize_project,
    serialize_resource,
    serialize_risk,
    serialize_suggestion,
    serialize_task,
    serialize_portfolio_summary_draft,
    serialize_weekly_update,
    truthy,
    update_action_status,
    update_decision,
    update_risk,
    update_weekly_update,
    upsert_weekly_update,
    delete_project,
    delete_resource,
    delete_task,
    get_portfolio_summary_draft_or_404,
)


AccessRole = Literal["editor", "viewer"]


def auth_accounts(settings: Settings) -> list[tuple[AccessRole, str, str]]:
    editor_username = settings.editor_username or settings.auth_username
    editor_password = settings.editor_password or settings.auth_password
    accounts: list[tuple[AccessRole, str, str]] = []
    if editor_username and editor_password:
        accounts.append(("editor", editor_username, editor_password))
    if settings.viewer_username and settings.viewer_password:
        accounts.append(("viewer", settings.viewer_username, settings.viewer_password))
    return accounts


def auth_enabled(settings: Settings) -> bool:
    return bool(auth_accounts(settings))


def request_access_role(authorization_header: str | None, settings: Settings) -> AccessRole | None:
    if not auth_enabled(settings):
        return "editor"
    if not authorization_header or not authorization_header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(authorization_header.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    for role, expected_username, expected_password in auth_accounts(settings):
        if secrets.compare_digest(username, expected_username) and secrets.compare_digest(password, expected_password):
            return role
    return None


def request_is_authorized(authorization_header: str | None, settings: Settings) -> bool:
    return request_access_role(authorization_header, settings) is not None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="PM Dashboard")

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)

    engine = make_engine(settings.db_url)
    session_factory = make_session_factory(engine)
    init_db(engine)
    with session_factory() as session:
        ensure_seed_projects(session)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory

    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")

    def unauthorized_response(request: Request):
        headers = {"WWW-Authenticate": 'Basic realm="PM Dashboard"'}
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"}, headers=headers)
        return PlainTextResponse("Unauthorized", status_code=401, headers=headers)

    @app.middleware("http")
    async def require_basic_auth(request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        if request_access_role(request.headers.get("authorization"), settings):
            return await call_next(request)
        return unauthorized_response(request)

    def get_session():
        session = app.state.session_factory()
        try:
            yield session
        finally:
            session.close()

    def request_role(request: Request) -> AccessRole:
        role = request_access_role(request.headers.get("authorization"), settings)
        return role or "viewer"

    def require_editor(request: Request) -> None:
        if request_role(request) != "editor":
            raise HTTPException(status_code=403, detail="Editor access required")

    def base_context(request: Request):
        role = request_role(request)
        return {
            "request": request,
            "today": date.today().isoformat(),
            "current_week_start": current_week_start().isoformat(),
            "access_role": role,
            "can_edit": role == "editor",
        }

    async def request_data(request: Request) -> dict:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            return await request.json()
        form = await request.form()
        return dict(form)

    def weekly_update_payload_from_data(data: dict) -> WeeklyUpdateCreate:
        week_start = parse_date(data.get("week_start")) or current_week_start()
        return WeeklyUpdateCreate(
            week_start=week_start,
            status_summary=data.get("status_summary"),
            blockers=data.get("blockers"),
            approvals_needed=data.get("approvals_needed"),
            follow_ups=data.get("follow_ups"),
            confidence_note=data.get("confidence_note"),
            meeting_notes=data.get("meeting_notes"),
            status_notes=data.get("status_notes"),
            needs_escalation=truthy(data.get("needs_escalation")),
            leadership_watch=truthy(data.get("leadership_watch")),
        )

    @app.get("/healthz")
    def healthcheck():
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        with app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "parser_ready": app.state.settings.parser_jar.exists(),
            "auth_enabled": auth_enabled(settings),
        }

    @app.get("/", response_class=HTMLResponse)
    def portfolio_page(request: Request, session=Depends(get_session)):
        projects = portfolio_view(session, settings=app.state.settings)
        resource_conflicts = detect_resource_conflicts(session, settings=app.state.settings)
        return templates.TemplateResponse(
            request,
            "portfolio.html",
            {
                **base_context(request),
                "projects": projects,
                "resource_conflicts": resource_conflicts,
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/cockpit", response_class=HTMLResponse)
    def cockpit_page(request: Request, session=Depends(get_session)):
        week_start = parse_date(request.query_params.get("week_start")) or current_week_start()
        cockpit = cockpit_view(session, settings=app.state.settings, week_start=week_start)
        return templates.TemplateResponse(
            request,
            "cockpit.html",
            {
                **base_context(request),
                "cockpit": cockpit,
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    def project_page(project_id: int, request: Request, session=Depends(get_session)):
        project = get_project_or_404(session, project_id)
        detail = project_detail(session, project, settings=app.state.settings, consume_task_diff=True)
        return templates.TemplateResponse(
            request,
            "project_detail.html",
            {
                **base_context(request),
                "project": project,
                "detail": detail,
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/projects/{project_id}/workflow", response_class=HTMLResponse)
    def project_workflow_page(project_id: int, request: Request, session=Depends(get_session)):
        project = get_project_or_404(session, project_id)
        week_start = parse_date(request.query_params.get("week_start")) or current_week_start()
        workflow = project_workflow_view(session, project, settings=app.state.settings, week_start=week_start)
        return templates.TemplateResponse(
            request,
            "project_workflow.html",
            {
                **base_context(request),
                "project": project,
                "workflow": workflow,
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/attention", response_class=HTMLResponse)
    def attention_page(request: Request, session=Depends(get_session)):
        queue = attention_queue(session, settings=app.state.settings)
        return templates.TemplateResponse(
            request,
            "attention.html",
            {
                **base_context(request),
                "queue": queue,
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/dependencies", response_class=HTMLResponse)
    def dependencies_page(request: Request, session=Depends(get_session)):
        dependency_data = dependencies_view(session)
        return templates.TemplateResponse(
            request,
            "dependencies.html",
            {
                **base_context(request),
                "dependency_data": dependency_data,
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/admin/imports", response_class=HTMLResponse)
    def imports_page(request: Request, session=Depends(get_session)):
        require_editor(request)
        projects = list_projects(session)
        project_tasks = {
            project.id: (list_tasks_for_snapshot(session, snapshot.id) if (snapshot := get_latest_snapshot(session, project.id)) else [])
            for project in projects
        }
        return templates.TemplateResponse(
            request,
            "imports.html",
            {
                **base_context(request),
                "projects": projects,
                "runs": import_history(session),
                "sample_mpp": str(app.state.settings.sample_mpp),
                "sample_mpp_exists": app.state.settings.sample_mpp.exists(),
                "repo_mpp_files": repo_file_project_rows(app.state.settings.repo_root),
                "parser_ready": app.state.settings.parser_jar.exists(),
                "project_tasks": project_tasks,
                "project_resources": {project.id: list_resources(session, project.id) for project in projects},
                "projects_nav": projects,
            },
        )

    @app.get("/api/projects")
    def projects_api(session=Depends(get_session)):
        return portfolio_view(session, settings=app.state.settings)

    @app.post("/api/projects")
    async def create_project_api(request: Request, session=Depends(get_session)):
        require_editor(request)
        data = await request_data(request)
        project = create_project(
            session,
            ProjectCreate(
                key=data.get("key", ""),
                name=data.get("name", ""),
                description=data.get("description"),
            ),
        )
        return serialize_project(project)

    @app.delete("/api/projects/{project_id}")
    def delete_project_api(project_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        project = get_project_or_404(session, project_id)
        delete_project(session, project)
        return {"status": "deleted", "project_id": project_id}

    @app.get("/api/portfolio/resource-conflicts")
    def resource_conflicts_api(session=Depends(get_session)):
        return detect_resource_conflicts(session, settings=app.state.settings)

    @app.get("/api/projects/{project_id}")
    def project_api(project_id: int, session=Depends(get_session)):
        project = get_project_or_404(session, project_id)
        return project_detail(session, project, settings=app.state.settings)

    @app.get("/api/cockpit")
    def cockpit_api(week_start: str | None = None, session=Depends(get_session)):
        selected_week = parse_date(week_start) or current_week_start()
        return cockpit_view(session, settings=app.state.settings, week_start=selected_week)

    @app.get("/api/dependencies")
    def dependencies_api(project_id: int | None = None, session=Depends(get_session)):
        return dependencies_view(session, project_id=project_id)

    @app.post("/api/projects/{project_id}/actions")
    async def create_action_api(project_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        project = get_project_or_404(session, project_id)
        data = await request_data(request)
        due_date = parse_date(data.get("due_date"))
        action = create_action(
            session,
            project,
            ActionCreate(
                title=data["title"],
                owner=data["owner"],
                due_date=due_date,
                notes=data.get("notes"),
                status=data.get("status", "open"),
            ),
        )
        return JSONResponse(
            {
                "id": action.id,
                "title": action.title,
                "owner": action.owner,
                "due_date": action.due_date.isoformat() if action.due_date else None,
                "status": action.status,
                "notes": action.notes,
            }
        )

    @app.post("/api/projects/{project_id}/tasks")
    async def create_task_api(project_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        project = get_project_or_404(session, project_id)
        data = await request_data(request)
        task = create_task(
            session,
            project,
            TaskCreate(
                name=data["name"],
                start_date=parse_date(data.get("start_date")),
                finish_date=parse_date(data.get("finish_date")),
                owner=data.get("owner"),
                resource_key=data.get("resource_key"),
                percent_complete=float(data.get("percent_complete") or 0.0),
                notes=data.get("notes"),
            ),
        )
        return serialize_task(task)

    @app.delete("/api/tasks/{task_id}")
    def delete_task_api(task_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        task = get_task_or_404(session, task_id)
        delete_task(session, task)
        return {"status": "deleted", "task_id": task_id}

    @app.post("/api/projects/{project_id}/resources")
    async def create_resource_api(project_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        project = get_project_or_404(session, project_id)
        data = await request_data(request)
        resource = create_resource(
            session,
            project,
            ResourceCreate(
                name=data["name"],
                role=data.get("role"),
                key=data.get("key"),
            ),
        )
        return serialize_resource(resource)

    @app.delete("/api/resources/{resource_id}")
    def delete_resource_api(resource_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        resource = get_resource_or_404(session, resource_id)
        delete_resource(session, resource)
        return {"status": "deleted", "resource_id": resource_id}

    @app.patch("/api/actions/{action_id}")
    async def update_action_api(action_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        action = get_action_or_404(session, action_id)
        data = await request_data(request)
        status = data.get("status")
        if not status:
            raise HTTPException(status_code=400, detail="status is required")
        action = update_action_status(session, action, status)
        return {"id": action.id, "status": action.status}

    @app.post("/api/projects/{project_id}/weekly-updates")
    async def create_weekly_update_api(project_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        project = get_project_or_404(session, project_id)
        data = await request_data(request)
        weekly_update = upsert_weekly_update(
            session,
            project,
            weekly_update_payload_from_data(data),
            settings=app.state.settings,
        )
        return serialize_weekly_update(weekly_update)

    @app.patch("/api/weekly-updates/{update_id}")
    async def update_weekly_update_api(update_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        weekly_update = get_weekly_update_or_404(session, update_id)
        data = await request_data(request)
        payload = weekly_update_payload_from_data(
            {
                "week_start": data.get("week_start") or weekly_update.week_start.isoformat(),
                "status_summary": data.get("status_summary", weekly_update.status_summary),
                "blockers": data.get("blockers", weekly_update.blockers),
                "approvals_needed": data.get("approvals_needed", weekly_update.approvals_needed),
                "follow_ups": data.get("follow_ups", weekly_update.follow_ups),
                "confidence_note": data.get("confidence_note", weekly_update.confidence_note),
                "meeting_notes": data.get("meeting_notes", weekly_update.meeting_notes),
                "status_notes": data.get("status_notes", weekly_update.status_notes),
                "needs_escalation": data.get("needs_escalation", weekly_update.needs_escalation),
                "leadership_watch": data.get("leadership_watch", weekly_update.leadership_watch),
            }
        )
        weekly_update = update_weekly_update(session, weekly_update, payload, settings=app.state.settings)
        return serialize_weekly_update(weekly_update)

    @app.get("/api/projects/{project_id}/suggestions")
    def project_suggestions_api(project_id: int, week_start: str | None = None, session=Depends(get_session)):
        project = get_project_or_404(session, project_id)
        selected_week = parse_date(week_start) or current_week_start()
        workflow = project_workflow_view(session, project, settings=app.state.settings, week_start=selected_week)
        return workflow["suggestions"]

    @app.post("/api/suggestions/{suggestion_id}/accept")
    async def accept_suggestion_api(suggestion_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        suggestion = get_suggestion_or_404(session, suggestion_id)
        data = await request_data(request)
        payload_override = data.get("payload") if isinstance(data.get("payload"), dict) else None
        suggestion = accept_suggestion(session, suggestion, payload_override=payload_override)
        return serialize_suggestion(suggestion)

    @app.post("/api/suggestions/{suggestion_id}/dismiss")
    def dismiss_suggestion_api(suggestion_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        suggestion = get_suggestion_or_404(session, suggestion_id)
        suggestion = dismiss_suggestion(session, suggestion)
        return serialize_suggestion(suggestion)

    @app.post("/api/portfolio/executive-summary/generate")
    def generate_executive_summary_api(request: Request, week_start: str | None = None, session=Depends(get_session)):
        require_editor(request)
        selected_week = parse_date(week_start) or current_week_start()
        draft = create_portfolio_summary_draft(session, selected_week, settings=app.state.settings)
        return serialize_portfolio_summary_draft(draft)

    @app.post("/api/portfolio/executive-summary/{draft_id}/accept")
    async def accept_executive_summary_api(draft_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        draft = get_portfolio_summary_draft_or_404(session, draft_id)
        data = await request_data(request)
        final_payload = data.get("final_payload") if isinstance(data.get("final_payload"), dict) else None
        draft = accept_portfolio_summary_draft(session, draft, final_payload=final_payload)
        return serialize_portfolio_summary_draft(draft)

    @app.post("/api/portfolio/executive-summary/{draft_id}/dismiss")
    def dismiss_executive_summary_api(draft_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        draft = get_portfolio_summary_draft_or_404(session, draft_id)
        draft = dismiss_portfolio_summary_draft(session, draft)
        return serialize_portfolio_summary_draft(draft)

    @app.post("/api/projects/{project_id}/risks")
    async def create_risk_api(project_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        project = get_project_or_404(session, project_id)
        data = await request_data(request)
        risk = create_risk(
            session,
            project,
            RiskCreate(
                title=data["title"],
                description=data.get("description"),
                category=data.get("category", "risk"),
                severity=data.get("severity", "medium"),
                owner=data.get("owner"),
                due_date=parse_date(data.get("due_date")),
                status=data.get("status", "open"),
                mitigation=data.get("mitigation"),
                source=data.get("source", "manual"),
                trend=data.get("trend", "steady"),
            ),
        )
        return serialize_risk(risk)

    @app.patch("/api/risks/{risk_id}")
    async def update_risk_api(risk_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        risk = get_risk_or_404(session, risk_id)
        data = await request_data(request)
        risk = update_risk(
            session,
            risk,
            {
                "title": data.get("title"),
                "description": data.get("description"),
                "category": data.get("category"),
                "severity": data.get("severity"),
                "owner": data.get("owner"),
                "due_date": parse_date(data.get("due_date")) if "due_date" in data else risk.due_date,
                "status": data.get("status"),
                "mitigation": data.get("mitigation"),
                "source": data.get("source"),
                "trend": data.get("trend"),
            },
        )
        return serialize_risk(risk)

    @app.post("/api/projects/{project_id}/decisions")
    async def create_decision_api(project_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        project = get_project_or_404(session, project_id)
        data = await request_data(request)
        decision = create_decision(
            session,
            project,
            DecisionCreate(
                summary=data["summary"],
                context=data.get("context"),
                owner=data.get("owner"),
                due_date=parse_date(data.get("due_date")),
                status=data.get("status", "pending"),
                impact=data.get("impact"),
                source=data.get("source", "manual"),
            ),
        )
        return serialize_decision(decision)

    @app.patch("/api/decisions/{decision_id}")
    async def update_decision_api(decision_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        decision = get_decision_or_404(session, decision_id)
        data = await request_data(request)
        decision = update_decision(
            session,
            decision,
            {
                "summary": data.get("summary"),
                "context": data.get("context"),
                "owner": data.get("owner"),
                "due_date": parse_date(data.get("due_date")) if "due_date" in data else decision.due_date,
                "status": data.get("status"),
                "impact": data.get("impact"),
                "source": data.get("source"),
            },
        )
        return serialize_decision(decision)

    @app.post("/api/imports/mpp")
    async def import_api(
        request: Request,
        project_id: int | None = None,
        files: list[UploadFile] = File(...),
        session=Depends(get_session),
    ):
        require_editor(request)
        if not files:
            return JSONResponse(status_code=400, content={"error": "At least one .mpp file is required"})

        results = []
        errors = []

        for file in files:
            source_filename = file.filename or ""
            project = resolve_project_for_import(session, source_filename=source_filename, project_id=project_id)
            saved_file = save_upload(file, app.state.settings)
            try:
                run = import_schedule(
                    session,
                    project,
                    saved_file,
                    source_filename=source_filename or saved_file.name,
                    settings=app.state.settings,
                )
                results.append(
                    {
                        "import_run_id": run.id,
                        "status": run.status,
                        "project_id": project.id,
                        "project_name": project.name,
                        "source_filename": run.source_filename,
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "error": str(exc),
                        "project_id": project.id,
                        "project_name": project.name,
                        "source_filename": source_filename or saved_file.name,
                    }
                )

        if errors:
            return JSONResponse(status_code=400, content={"results": results, "errors": errors})

        return {"results": results, "count": len(results)}

    return app


app = create_app()
