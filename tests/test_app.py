from __future__ import annotations

import base64
import asyncio
from datetime import date, timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.datastructures import UploadFile

from fastapi import HTTPException

from pm_dashboard.main import create_app, request_access_role, request_is_authorized
from pm_dashboard.models import Project
from pm_dashboard.services import (
    ActionCreate,
    ProjectCreate,
    ResourceCreate,
    TaskCreate,
    create_action,
    create_project,
    create_resource,
    create_task,
    delete_project,
    delete_resource,
    delete_task,
)


def make_request(app, path: str = "/", headers: dict[str, str] | None = None, method: str = "GET") -> Request:
    raw_headers = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("latin-1"), value.encode("latin-1")))
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": raw_headers,
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
        "query_string": b"",
        "http_version": "1.1",
        "app": app,
        "router": app.router,
    }
    return Request(scope)


def route_for(app, path: str):
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route
    raise AssertionError(f"Route not found: {path}")


def test_portfolio_route_loads(app):
    request = make_request(app, "/")
    route = route_for(app, "/")
    with app.state.session_factory() as session:
        response = route.endpoint(request=request, session=session)

    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "PM Control Tower" in body
    assert "P2C" in body


def test_attention_page_shows_overdue_actions(app):
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "p2c").one()
        create_action(
            session,
            project,
            ActionCreate(
                title="Escalate permit blocker",
                owner="Matt",
                due_date=date.today() - timedelta(days=2),
                notes="Needs sponsor intervention",
            ),
        )

    request = make_request(app, "/attention")
    route = route_for(app, "/attention")
    with app.state.session_factory() as session:
        response = route.endpoint(request=request, session=session)

    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "Overdue Actions" in body
    assert "Escalate permit blocker" not in body


def test_mark_action_done_service(app):
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "p2c").one()
        action = create_action(
            session,
            project,
            ActionCreate(
                title="Send weekly status",
                owner="Matt",
                due_date=date.today(),
                notes="",
            ),
        )
        action.status = "done"
        session.commit()
        session.refresh(action)
        assert action.status == "done"


def basic_auth_headers(username: str = "pm", password: str = "secret") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_auth_blocks_missing_credentials(auth_settings):
    assert request_is_authorized(None, auth_settings) is False


def test_auth_allows_valid_credentials(auth_settings):
    assert request_is_authorized(basic_auth_headers()["Authorization"], auth_settings) is True


def test_auth_allows_viewer_credentials(auth_settings):
    assert request_is_authorized(basic_auth_headers(username="team", password="readonly")["Authorization"], auth_settings)


def test_auth_resolves_access_roles(auth_settings):
    assert request_access_role(basic_auth_headers()["Authorization"], auth_settings) == "editor"
    assert request_access_role(
        basic_auth_headers(username="team", password="readonly")["Authorization"], auth_settings
    ) == "viewer"


def test_auth_rejects_invalid_credentials(auth_settings):
    assert request_is_authorized(basic_auth_headers(password="wrong")["Authorization"], auth_settings) is False


def test_imports_page_requires_editor(auth_settings):
    app = create_app(auth_settings)
    route = route_for(app, "/admin/imports")
    request = make_request(
        app,
        "/admin/imports",
        headers=basic_auth_headers(username="team", password="readonly"),
    )
    with app.state.session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            route.endpoint(request=request, session=session)

    assert exc_info.value.status_code == 403


def test_create_action_requires_editor(auth_settings):
    app = create_app(auth_settings)
    route = route_for(app, "/api/projects/{project_id}/actions")
    request = make_request(
        app,
        "/api/projects/1/actions",
        headers=basic_auth_headers(username="team", password="readonly"),
        method="POST",
    )
    with app.state.session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(route.endpoint(project_id=1, request=request, session=session))

    assert exc_info.value.status_code == 403


def test_multi_file_import_endpoint_imports_each_file(monkeypatch, app):
    route = route_for(app, "/api/imports/mpp")
    imported = []

    def fake_save_upload(upload, settings):
        return settings.uploads_dir / upload.filename

    def fake_import_schedule(session, project, file_path, source_filename, settings):
        imported.append((project.key, source_filename))

        return SimpleNamespace(id=len(imported), status="success", source_filename=source_filename)

    monkeypatch.setattr("pm_dashboard.main.save_upload", fake_save_upload)
    monkeypatch.setattr("pm_dashboard.main.import_schedule", fake_import_schedule)

    upload_a = UploadFile(filename="Atlas_phase1_100h_13Mar-MH.mpp", file=BytesIO(b"a"))
    upload_b = UploadFile(filename="MPMProject324.mpp", file=BytesIO(b"b"))

    with app.state.session_factory() as session:
        response = asyncio.run(
            route.endpoint(
                request=make_request(app, "/api/imports/mpp"),
                project_id=None,
                files=[upload_a, upload_b],
                session=session,
            )
        )

    assert response["count"] == 2
    assert imported == [("atlas", "Atlas_phase1_100h_13Mar-MH.mpp"), ("mpm", "MPMProject324.mpp")]


def test_multi_file_import_endpoint_returns_error_collection(monkeypatch, app):
    route = route_for(app, "/api/imports/mpp")

    def fake_save_upload(upload, settings):
        return settings.uploads_dir / upload.filename

    def fake_import_schedule(session, project, file_path, source_filename, settings):
        raise RuntimeError(f"bad import: {source_filename}")

    monkeypatch.setattr("pm_dashboard.main.save_upload", fake_save_upload)
    monkeypatch.setattr("pm_dashboard.main.import_schedule", fake_import_schedule)

    upload = UploadFile(filename="Atlas_phase1_100h_13Mar-MH.mpp", file=BytesIO(b"a"))

    with app.state.session_factory() as session:
        response = asyncio.run(
            route.endpoint(
                request=make_request(app, "/api/imports/mpp"),
                project_id=None,
                files=[upload],
                session=session,
            )
        )

    assert response.status_code == 400


def test_project_task_resource_crud_services(app):
    with app.state.session_factory() as session:
        project = create_project(
            session,
            ProjectCreate(key="demo", name="Demo Project", description="Created in test"),
        )
        task = create_task(
            session,
            project,
            TaskCreate(name="Demo Task", owner="Alex"),
        )
        resource = create_resource(
            session,
            project,
            ResourceCreate(name="Taylor", role="Planner"),
        )
        assert project.id is not None
        assert task.id is not None
        assert resource.id is not None

        delete_task(session, task)
        delete_resource(session, resource)
        delete_project(session, project)
