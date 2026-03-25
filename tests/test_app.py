from __future__ import annotations

from datetime import date, timedelta

from starlette.requests import Request

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
    assert "Pyrolysis Petal 2026" in body


def test_attention_page_shows_overdue_actions(app):
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "pyrolysis-petal-2026").one()
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
        project = session.query(Project).filter(Project.key == "pyrolysis-petal-2026").one()
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
