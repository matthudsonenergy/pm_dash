from __future__ import annotations

import base64
import secrets
import tempfile
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
from .models import Project
from .projects import repo_file_project_rows
from .projects import PROJECTS
from .repository import get_latest_snapshot, list_projects, list_resources, list_tasks_for_snapshot
from .services import (
    ActionCreate,
    ProjectCreate,
    ResourceCreate,
    TaskCreate,
    DecisionCreate,
    EditorProfileUpdate,
    RiskCreate,
    WeeklyUpdateCreate,
    accept_suggestion,
    accept_portfolio_summary_draft,
    accept_outbound_draft,
    attention_queue,
    cockpit_view,
    create_action,
    create_project,
    create_resource,
    create_decision,
    create_task,
    create_risk,
    refresh_saved_projects,
    refresh_status_summary,
    dependencies_view,
    current_week_start,
    detect_resource_conflicts,
    dismiss_suggestion,
    dismiss_portfolio_summary_draft,
    dismiss_outbound_draft,
    effective_settings_for_profile,
    get_action_or_404,
    get_decision_or_404,
    get_or_create_editor_profile,
    get_project_or_404,
    get_resource_or_404,
    get_risk_or_404,
    get_suggestion_or_404,
    get_task_or_404,
    get_weekly_update_or_404,
    get_outbound_draft_or_404,
    generate_outbound_drafts,
    import_history,
    import_schedule,
    parse_date,
    portfolio_view,
    create_portfolio_summary_draft,
    project_detail,
    project_workflow_view,
    resolve_project_for_import,
    serialize_decision,
    serialize_project,
    serialize_resource,
    serialize_risk,
    serialize_suggestion,
    serialize_task,
    serialize_portfolio_summary_draft,
    serialize_outbound_draft,
    serialize_editor_profile,
    serialize_weekly_update,
    truthy,
    update_action_status,
    update_decision,
    update_risk,
    update_weekly_update,
    upsert_weekly_update,
    update_editor_profile,
    delete_project,
    delete_resource,
    delete_task,
    review_suggestions_batch,
    get_portfolio_summary_draft_or_404,
    serialize_project_file,
    upsert_project_file,
    materialize_project_file,
)


AccessRole = Literal["editor", "viewer"]


def save_upload(upload: UploadFile, settings: Settings) -> Path:
    suffix = Path(upload.filename or "project.mpp").suffix or ".mpp"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=settings.uploads_dir) as handle:
        while True:
            chunk = upload.file.read(65536)
            if not chunk:
                break
            handle.write(chunk)
    upload.file.seek(0)
    return Path(handle.name)


def seed_default_projects(session) -> None:
    existing = {project.key for project in list_projects(session)}
    created = False
    for definition in PROJECTS:
        if definition.key in existing:
            continue
        session.add(
            Project(
                key=definition.key,
                name=definition.name,
                description=definition.description,
            )
        )
        created = True
    if created:
        session.commit()


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


def request_basic_auth_username(authorization_header: str | None) -> str | None:
    if not authorization_header or not authorization_header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(authorization_header.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return None
    username, separator, _password = decoded.partition(":")
    if not separator:
        return None
    return username


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
        seed_default_projects(session)

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

    def request_username(request: Request) -> str:
        username = request_basic_auth_username(request.headers.get("authorization"))
        if username:
            return username
        return settings.editor_username or settings.auth_username or "local-editor"

    def require_editor(request: Request) -> None:
        if request_role(request) != "editor":
            raise HTTPException(status_code=403, detail="Editor access required")

    def request_editor_profile(request: Request, session):
        if request_role(request) != "editor":
            return None
        return get_or_create_editor_profile(session, request_username(request), settings)

    def request_settings(request: Request, session):
        return effective_settings_for_profile(settings, request_editor_profile(request, session))

    def base_context(request: Request, session=None):
        role = request_role(request)
        editor_profile = request_editor_profile(request, session) if session is not None else None
        return {
            "request": request,
            "today": date.today().isoformat(),
            "current_week_start": current_week_start().isoformat(),
            "access_role": role,
            "can_edit": role == "editor",
            "editor_profile": serialize_editor_profile(editor_profile) if editor_profile else None,
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
        active_settings = request_settings(request, session)
        projects = portfolio_view(session, settings=active_settings)
        resource_conflicts = detect_resource_conflicts(session, settings=active_settings)
        return templates.TemplateResponse(
            request,
            "portfolio.html",
            {
                **base_context(request, session),
                "projects": projects,
                "resource_conflicts": resource_conflicts,
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/cockpit", response_class=HTMLResponse)
    def cockpit_page(request: Request, session=Depends(get_session)):
        week_start = parse_date(request.query_params.get("week_start")) or current_week_start()
        cockpit = cockpit_view(session, settings=request_settings(request, session), week_start=week_start)
        return templates.TemplateResponse(
            request,
            "cockpit.html",
            {
                **base_context(request, session),
                "cockpit": cockpit,
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    def project_page(project_id: int, request: Request, session=Depends(get_session)):
        project = get_project_or_404(session, project_id)
        detail = project_detail(session, project, settings=request_settings(request, session), consume_task_diff=True)
        return templates.TemplateResponse(
            request,
            "project_detail.html",
            {
                **base_context(request, session),
                "project": project,
                "detail": detail,
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/projects/{project_id}/workflow", response_class=HTMLResponse)
    def project_workflow_page(project_id: int, request: Request, session=Depends(get_session)):
        project = get_project_or_404(session, project_id)
        week_start = parse_date(request.query_params.get("week_start")) or current_week_start()
        workflow = project_workflow_view(session, project, settings=request_settings(request, session), week_start=week_start)
        return templates.TemplateResponse(
            request,
            "project_workflow.html",
            {
                **base_context(request, session),
                "project": project,
                "workflow": workflow,
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/attention", response_class=HTMLResponse)
    def attention_page(request: Request, session=Depends(get_session)):
        queue = attention_queue(session, settings=request_settings(request, session))
        return templates.TemplateResponse(
            request,
            "attention.html",
            {
                **base_context(request, session),
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
                **base_context(request, session),
                "dependency_data": dependency_data,
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, session=Depends(get_session)):
        require_editor(request)
        profile = request_editor_profile(request, session)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                **base_context(request, session),
                "profile": serialize_editor_profile(profile),
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
                **base_context(request, session),
                "projects": projects,
                "runs": import_history(session),
                "sample_mpp": str(app.state.settings.sample_mpp),
                "sample_mpp_exists": app.state.settings.sample_mpp.exists(),
                "repo_mpp_files": repo_file_project_rows(app.state.settings.repo_root),
                "parser_ready": app.state.settings.parser_jar.exists(),
                "project_tasks": project_tasks,
                "project_resources": {project.id: list_resources(session, project.id) for project in projects},
                "project_files": {project.id: serialize_project_file(project.project_files[0] if project.project_files else None) for project in projects},
                "refresh_summary": refresh_status_summary(session, settings=request_settings(request, session)),
                "projects_nav": projects,
            },
        )

    @app.get("/api/projects")
    def projects_api(request: Request, session=Depends(get_session)):
        return portfolio_view(session, settings=request_settings(request, session))

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
    def resource_conflicts_api(request: Request, session=Depends(get_session)):
        return detect_resource_conflicts(session, settings=request_settings(request, session))

    @app.get("/api/projects/{project_id}")
    def project_api(project_id: int, request: Request, session=Depends(get_session)):
        project = get_project_or_404(session, project_id)
        return project_detail(session, project, settings=request_settings(request, session))

    @app.get("/api/cockpit")
    def cockpit_api(request: Request, week_start: str | None = None, session=Depends(get_session)):
        selected_week = parse_date(week_start) or current_week_start()
        return cockpit_view(session, settings=request_settings(request, session), week_start=selected_week)

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
            settings=request_settings(request, session),
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
        weekly_update = update_weekly_update(session, weekly_update, payload, settings=request_settings(request, session))
        return serialize_weekly_update(weekly_update)

    @app.get("/api/projects/{project_id}/suggestions")
    def project_suggestions_api(project_id: int, request: Request, week_start: str | None = None, session=Depends(get_session)):
        project = get_project_or_404(session, project_id)
        selected_week = parse_date(week_start) or current_week_start()
        workflow = project_workflow_view(session, project, settings=request_settings(request, session), week_start=selected_week)
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

    @app.post("/api/suggestions/batch-review")
    async def batch_review_suggestions_api(request: Request, session=Depends(get_session)):
        require_editor(request)
        data = await request_data(request)
        suggestion_ids_raw = data.get("suggestion_ids") or []
        if isinstance(suggestion_ids_raw, str):
            suggestion_ids_raw = [item.strip() for item in suggestion_ids_raw.split(",") if item.strip()]
        suggestion_ids = [int(item) for item in suggestion_ids_raw]
        action = data.get("action")
        payload_overrides_raw = data.get("payload_overrides") if isinstance(data.get("payload_overrides"), dict) else {}
        payload_overrides = {int(key): value for key, value in payload_overrides_raw.items()}
        reviewed = review_suggestions_batch(
            session,
            suggestion_ids=suggestion_ids,
            action=action,
            payload_overrides=payload_overrides,
        )
        return {"count": len(reviewed), "suggestions": reviewed}

    @app.post("/api/portfolio/executive-summary/generate")
    def generate_executive_summary_api(request: Request, week_start: str | None = None, session=Depends(get_session)):
        require_editor(request)
        profile = request_editor_profile(request, session)
        if profile and not profile.auto_generate_executive_summary:
            raise HTTPException(status_code=400, detail="Executive summary generation is disabled in the editor profile")
        selected_week = parse_date(week_start) or current_week_start()
        draft = create_portfolio_summary_draft(session, selected_week, settings=request_settings(request, session))
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

    @app.get("/api/outbound-drafts")
    def outbound_drafts_api(project_id: int | None = None, week_start: str | None = None, status: str | None = None, session=Depends(get_session)):
        from .repository import list_outbound_drafts

        selected_week = parse_date(week_start) if week_start else None
        return [
            serialize_outbound_draft(item)
            for item in list_outbound_drafts(session, project_id=project_id, week_start=selected_week, status=status)
        ]

    @app.post("/api/outbound-drafts/generate")
    def generate_outbound_drafts_api(
        request: Request,
        week_start: str | None = None,
        project_id: int | None = None,
        session=Depends(get_session),
    ):
        require_editor(request)
        profile = request_editor_profile(request, session)
        if profile and not profile.auto_generate_outbound_drafts:
            raise HTTPException(status_code=400, detail="Outbound draft generation is disabled in the editor profile")
        selected_week = parse_date(week_start) or current_week_start()
        drafts = generate_outbound_drafts(session, week_start=selected_week, settings=request_settings(request, session), project_id=project_id)
        return {"count": len(drafts), "drafts": drafts}

    @app.post("/api/outbound-drafts/{draft_id}/accept")
    async def accept_outbound_draft_api(draft_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        draft = get_outbound_draft_or_404(session, draft_id)
        data = await request_data(request)
        draft = accept_outbound_draft(
            session,
            draft,
            title=data.get("title"),
            message_text=data.get("message_text"),
            audience_label=data.get("audience_label"),
        )
        return serialize_outbound_draft(draft)

    @app.post("/api/outbound-drafts/{draft_id}/dismiss")
    def dismiss_outbound_draft_api(draft_id: int, request: Request, session=Depends(get_session)):
        require_editor(request)
        draft = get_outbound_draft_or_404(session, draft_id)
        draft = dismiss_outbound_draft(session, draft)
        return serialize_outbound_draft(draft)

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
            file_bytes = await file.read()
            project_file = upsert_project_file(
                session,
                project,
                filename=source_filename or f"{project.key}.mpp",
                content=file_bytes,
                content_type=file.content_type,
            )
            try:
                try:
                    run = import_schedule(
                        session,
                        project,
                        saved_file,
                        source_filename=project_file.filename,
                        settings=request_settings(request, session),
                        source_path=f"db://project-files/{project_file.id}/{project_file.filename}",
                        source_checksum=project_file.checksum,
                    )
                except TypeError as exc:
                    if "unexpected keyword argument" not in str(exc):
                        raise
                    run = import_schedule(
                        session,
                        project,
                        saved_file,
                        source_filename=project_file.filename,
                        settings=request_settings(request, session),
                    )
                results.append(
                    {
                        "import_run_id": run.id,
                        "status": run.status,
                        "project_id": project.id,
                        "project_name": project.name,
                        "source_filename": run.source_filename,
                        "project_file": serialize_project_file(project_file),
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "error": str(exc),
                        "project_id": project.id,
                        "project_name": project.name,
                        "source_filename": project_file.filename,
                    }
                )
            finally:
                saved_file.unlink(missing_ok=True)

        if errors:
            return JSONResponse(status_code=400, content={"results": results, "errors": errors})

        return {"results": results, "count": len(results)}

    @app.get("/api/imports/refresh-status")
    def refresh_status_api(request: Request, session=Depends(get_session)):
        return refresh_status_summary(session, settings=request_settings(request, session))

    @app.get("/api/editor-profile")
    def editor_profile_api(request: Request, session=Depends(get_session)):
        require_editor(request)
        return serialize_editor_profile(request_editor_profile(request, session))

    @app.patch("/api/editor-profile")
    async def update_editor_profile_api(request: Request, session=Depends(get_session)):
        require_editor(request)
        profile = request_editor_profile(request, session)
        data = await request_data(request)
        updated = update_editor_profile(
            session,
            profile,
            EditorProfileUpdate(
                display_name=(data.get("display_name") or profile.display_name),
                stale_plan_days=int(data.get("stale_plan_days") or profile.stale_plan_days),
                upcoming_milestone_days=int(data.get("upcoming_milestone_days") or profile.upcoming_milestone_days),
                slip_from_previous_days=int(data.get("slip_from_previous_days") or profile.slip_from_previous_days),
                slip_from_baseline_days=int(data.get("slip_from_baseline_days") or profile.slip_from_baseline_days),
                auto_refresh_enabled=truthy(data.get("auto_refresh_enabled", profile.auto_refresh_enabled)),
                auto_generate_outbound_drafts=truthy(data.get("auto_generate_outbound_drafts", profile.auto_generate_outbound_drafts)),
                auto_generate_executive_summary=truthy(data.get("auto_generate_executive_summary", profile.auto_generate_executive_summary)),
                show_attention_explainers=truthy(data.get("show_attention_explainers", profile.show_attention_explainers)),
            ),
        )
        return serialize_editor_profile(updated)

    @app.post("/api/imports/refresh")
    def refresh_saved_files_api(request: Request, project_id: int | None = None, session=Depends(get_session)):
        require_editor(request)
        profile = request_editor_profile(request, session)
        if profile and not profile.auto_refresh_enabled:
            raise HTTPException(status_code=400, detail="Saved-file refresh is disabled in the editor profile")
        payload = refresh_saved_projects(session, settings=request_settings(request, session), project_id=project_id)
        if payload["errors"]:
            return JSONResponse(status_code=400, content=payload)
        return payload

    return app


app = create_app()
