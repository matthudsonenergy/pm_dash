from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from pm_dashboard.models import ActionItem, DecisionItem, Project, RiskItem, SuggestionItem, WeeklyUpdate
from pm_dashboard.parser import ParsedProject, ParsedTask
from pm_dashboard.repository import list_suggestions
from pm_dashboard.services import (
    DecisionCreate,
    RiskCreate,
    WeeklyUpdateCreate,
    accept_suggestion,
    attention_queue,
    cockpit_view,
    create_decision,
    create_risk,
    dismiss_suggestion,
    import_schedule,
    project_workflow_view,
    upsert_weekly_update,
)


def fake_parsed_project(finish: date) -> ParsedProject:
    return ParsedProject(
        title="Pyrolysis Petal",
        current_finish_date=finish,
        baseline_finish_date=date(2026, 3, 28),
        tasks=[
            ParsedTask(
                unique_id=1,
                outline_level=1,
                outline_path="1",
                name="Startup SOP complete",
                start_date=date(2026, 3, 20),
                finish_date=finish,
                baseline_start_date=date(2026, 3, 17),
                baseline_finish_date=date(2026, 3, 24),
                percent_complete=40.0,
                critical_flag=True,
                milestone_flag=True,
                predecessor_refs=None,
                notes="Primary milestone",
            ),
            ParsedTask(
                unique_id=2,
                outline_level=2,
                outline_path="1.1",
                name="Review startup package",
                start_date=date(2026, 3, 18),
                finish_date=finish,
                baseline_start_date=date(2026, 3, 17),
                baseline_finish_date=date(2026, 3, 21),
                percent_complete=50.0,
                critical_flag=True,
                milestone_flag=False,
                predecessor_refs="1:FS",
                notes=None,
            ),
        ],
    )


def test_weekly_update_generates_suggestions_and_views(monkeypatch, app, tmp_path: Path):
    sample_file = tmp_path / "sample.mpp"
    sample_file.write_text("placeholder", encoding="utf-8")
    parsed_versions = [fake_parsed_project(date(2026, 3, 24)), fake_parsed_project(date(2026, 3, 31))]

    def fake_parse(*args, **kwargs):
        return parsed_versions.pop(0)

    monkeypatch.setattr("pm_dashboard.services.parse_mpp_file", fake_parse)

    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "pyrolysis-petal-2026").one()
        import_schedule(session, project, sample_file, source_filename=sample_file.name, settings=app.state.settings)
        import_schedule(session, project, sample_file, source_filename=sample_file.name, settings=app.state.settings)

        weekly_update = upsert_weekly_update(
            session,
            project,
            WeeklyUpdateCreate(
                week_start=date(2026, 3, 23),
                status_summary="Delivery is under pressure but recoverable.",
                blockers="Vendor approval missing",
                approvals_needed="Decision: approve weekend install | owner: Matt | due: 2026-03-27",
                follow_ups="Matt to send revised status by 2026-03-26",
                confidence_note="Confidence dropped after milestone slip.",
                meeting_notes="Action: Ana to confirm crane booking by 2026-03-25",
                status_notes="Risk: startup checklist may slip again",
                needs_escalation=True,
                leadership_watch=True,
            ),
            settings=app.state.settings,
        )
        workflow = project_workflow_view(session, project, settings=app.state.settings, week_start=date(2026, 3, 23))
        cockpit = cockpit_view(session, settings=app.state.settings, week_start=date(2026, 3, 23))

    assert isinstance(weekly_update, WeeklyUpdate)
    assert workflow["weekly_update"]["week_start"] == "2026-03-23"
    assert workflow["pending_suggestions"]
    assert any(item["suggestion_type"] == "summary" for item in workflow["suggestions"])
    assert cockpit["portfolio_summary"]
    assert cockpit["project_rows"][0]["milestone_changes"]


def test_accept_action_suggestion_creates_action(monkeypatch, app):
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "pyrolysis-petal-2026").one()
        weekly_update = upsert_weekly_update(
            session,
            project,
            WeeklyUpdateCreate(
                week_start=date(2026, 3, 24),
                status_summary="On track",
                blockers=None,
                approvals_needed=None,
                follow_ups="Matt to send weekly status by 2026-03-28",
                confidence_note=None,
                meeting_notes=None,
                status_notes=None,
            ),
            settings=app.state.settings,
        )
        suggestion = next(item for item in list_suggestions(session, weekly_update_id=weekly_update.id) if item.suggestion_type == "action")
        accept_suggestion(session, suggestion)
        actions = session.query(ActionItem).all()

    assert len(actions) == 1
    assert actions[0].title.startswith("send weekly status")


def test_risk_and_decision_suggestions_materialize(monkeypatch, app):
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "pyrolysis-petal-2026").one()
        weekly_update = upsert_weekly_update(
            session,
            project,
            WeeklyUpdateCreate(
                week_start=date(2026, 3, 24),
                status_summary="Need decisions.",
                blockers="Blocked on vendor sign-off",
                approvals_needed="Decision: approve recovery budget | owner: Matt | due: 2026-03-29",
                follow_ups=None,
                confidence_note="Uncertain until approval lands.",
                meeting_notes=None,
                status_notes=None,
                needs_escalation=True,
                leadership_watch=False,
            ),
            settings=app.state.settings,
        )
        suggestions = list_suggestions(session, weekly_update_id=weekly_update.id)
        for suggestion in suggestions:
            if suggestion.suggestion_type in {"risk", "decision"}:
                accept_suggestion(session, suggestion)

        risks = session.query(RiskItem).all()
        decisions = session.query(DecisionItem).all()

    assert risks
    assert decisions
    assert risks[0].source == "suggested"
    assert decisions[0].source == "suggested"


def test_dismiss_suggestion_leaves_no_downstream_record(app):
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "pyrolysis-petal-2026").one()
        weekly_update = upsert_weekly_update(
            session,
            project,
            WeeklyUpdateCreate(
                week_start=date(2026, 3, 24),
                status_summary="On track",
                blockers=None,
                approvals_needed=None,
                follow_ups="Action: close permit gap",
                confidence_note=None,
                meeting_notes=None,
                status_notes=None,
            ),
            settings=app.state.settings,
        )
        suggestion = next(item for item in list_suggestions(session, weekly_update_id=weekly_update.id) if item.suggestion_type == "action")
        dismiss_suggestion(session, suggestion)
        action_count = session.query(ActionItem).count()
        suggestion = session.get(SuggestionItem, suggestion.id)

    assert action_count == 0
    assert suggestion.status == "dismissed"


def test_duplicate_weekly_update_reuses_same_row(app):
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "pyrolysis-petal-2026").one()
        first = upsert_weekly_update(
            session,
            project,
            WeeklyUpdateCreate(
                week_start=date(2026, 3, 24),
                status_summary="Initial draft",
                blockers=None,
                approvals_needed=None,
                follow_ups=None,
                confidence_note=None,
                meeting_notes=None,
                status_notes=None,
            ),
            settings=app.state.settings,
        )
        second = upsert_weekly_update(
            session,
            project,
            WeeklyUpdateCreate(
                week_start=date(2026, 3, 24),
                status_summary="Revised draft",
                blockers=None,
                approvals_needed=None,
                follow_ups=None,
                confidence_note=None,
                meeting_notes=None,
                status_notes=None,
            ),
            settings=app.state.settings,
        )
        count = session.query(WeeklyUpdate).count()

    assert first.id == second.id
    assert count == 1


def test_attention_queue_includes_phase2_signals(app):
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "pyrolysis-petal-2026").one()
        create_risk(
            session,
            project,
            RiskCreate(
                title="Escalating vendor delay",
                description="Worsening blocker",
                severity="high",
                trend="worsening",
                source="manual",
            ),
        )
        create_decision(
            session,
            project,
            DecisionCreate(
                summary="Approve recovery budget",
                context="Needed this week",
                owner="Matt",
                due_date=date.today() - timedelta(days=1),
                status="pending",
                source="manual",
            ),
        )
        queue = attention_queue(session, settings=app.state.settings, today=date.today())

    categories = {item["category"] for item in queue}
    assert "Missing Weekly Update" in categories
    assert "Overdue Decisions" in categories
    assert "Worsening Risks" in categories
