from __future__ import annotations

import base64
from datetime import date, timedelta

from starlette.requests import Request

from pm_dashboard.main import request_is_authorized
from pm_dashboard.models import Project
from pm_dashboard.services import ActionCreate, create_action


def make_request(app, path: str = "/") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
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


def test_auth_rejects_invalid_credentials(auth_settings):
    assert request_is_authorized(basic_auth_headers(password="wrong")["Authorization"], auth_settings) is False
