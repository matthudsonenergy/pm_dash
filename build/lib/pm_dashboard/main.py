from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Settings, get_settings
from .database import init_db, make_engine, make_session_factory
from .repository import list_projects
from .seed import ensure_seed_projects
from .services import (
    ActionCreate,
    attention_queue,
    create_action,
    get_action_or_404,
    get_project_or_404,
    import_history,
    import_schedule,
    portfolio_view,
    project_detail,
    save_upload,
    update_action_status,
)


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

    def get_session():
        session = app.state.session_factory()
        try:
            yield session
        finally:
            session.close()

    def base_context(request: Request):
        return {
            "request": request,
            "today": date.today().isoformat(),
        }

    async def request_data(request: Request) -> dict:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            return await request.json()
        form = await request.form()
        return dict(form)

    @app.get("/", response_class=HTMLResponse)
    def portfolio_page(request: Request, session=Depends(get_session)):
        projects = portfolio_view(session, settings=app.state.settings)
        return templates.TemplateResponse(
            request,
            "portfolio.html",
            {
                **base_context(request),
                "projects": projects,
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    def project_page(project_id: int, request: Request, session=Depends(get_session)):
        project = get_project_or_404(session, project_id)
        detail = project_detail(session, project, settings=app.state.settings)
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

    @app.get("/admin/imports", response_class=HTMLResponse)
    def imports_page(request: Request, session=Depends(get_session)):
        return templates.TemplateResponse(
            request,
            "imports.html",
            {
                **base_context(request),
                "projects": list_projects(session),
                "runs": import_history(session),
                "sample_mpp": str(app.state.settings.sample_mpp),
                "parser_ready": app.state.settings.parser_jar.exists(),
                "projects_nav": list_projects(session),
            },
        )

    @app.get("/api/projects")
    def projects_api(session=Depends(get_session)):
        return portfolio_view(session, settings=app.state.settings)

    @app.get("/api/projects/{project_id}")
    def project_api(project_id: int, session=Depends(get_session)):
        project = get_project_or_404(session, project_id)
        return project_detail(session, project, settings=app.state.settings)

    @app.post("/api/projects/{project_id}/actions")
    async def create_action_api(project_id: int, request: Request, session=Depends(get_session)):
        project = get_project_or_404(session, project_id)
        data = await request_data(request)
        due_date = date.fromisoformat(data["due_date"]) if data.get("due_date") else None
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

    @app.patch("/api/actions/{action_id}")
    async def update_action_api(action_id: int, request: Request, session=Depends(get_session)):
        action = get_action_or_404(session, action_id)
        data = await request_data(request)
        status = data.get("status")
        if not status:
            raise HTTPException(status_code=400, detail="status is required")
        action = update_action_status(session, action, status)
        return {"id": action.id, "status": action.status}

    @app.post("/api/imports/mpp")
    async def import_api(
        request: Request,
        project_id: int,
        file: UploadFile = File(...),
        session=Depends(get_session),
    ):
        project = get_project_or_404(session, project_id)
        saved_file = save_upload(file, app.state.settings)
        try:
            run = import_schedule(
                session,
                project,
                saved_file,
                source_filename=file.filename or saved_file.name,
                settings=app.state.settings,
            )
            return {
                "import_run_id": run.id,
                "status": run.status,
                "project_id": project.id,
                "source_filename": run.source_filename,
            }
        except Exception as exc:
            return JSONResponse(status_code=400, content={"error": str(exc), "project_id": project.id})

    return app


app = create_app()
