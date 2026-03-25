from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pm_dashboard.models import Milestone, Project, ScheduleSnapshot
from pm_dashboard.services import (
    DecisionCreate,
    RiskCreate,
    WeeklyUpdateCreate,
    attention_queue,
    create_decision,
    create_risk,
    health_trend,
    leadership_surprise_indicator,
    portfolio_view,
    project_summary,
    upsert_weekly_update,
)


def _seed_weekly_updates(session, project: Project, week_starts: list[date], settings) -> None:
    for week_start in week_starts:
        upsert_weekly_update(
            session,
            project,
            WeeklyUpdateCreate(
                week_start=week_start,
                status_summary=f"Weekly update for {week_start.isoformat()}",
                blockers=None,
                approvals_needed=None,
                follow_ups=None,
                confidence_note=None,
                meeting_notes=None,
                status_notes=None,
            ),
            settings=settings,
        )


def _seed_snapshot(session, project: Project, imported_at: datetime, material_slips: int) -> None:
    snapshot = ScheduleSnapshot(
        project_id=project.id,
        imported_at=imported_at,
        source_filename=f"snapshot-{imported_at.date().isoformat()}.mpp",
        source_path=f"/tmp/snapshot-{imported_at.date().isoformat()}.mpp",
        source_checksum=f"checksum-{imported_at.isoformat()}",
        current_finish_date=imported_at.date(),
        baseline_finish_date=imported_at.date(),
        task_count=1,
        milestone_count=material_slips,
        critical_task_count=0,
    )
    session.add(snapshot)
    session.flush()
    for index in range(material_slips):
        session.add(
            Milestone(
                snapshot_id=snapshot.id,
                name=f"Milestone {index + 1}",
                finish_date=imported_at.date(),
                material_slip=True,
            )
        )
    session.commit()


def _add_snapshot(
    session,
    project: Project,
    *,
    imported_at: datetime,
    finish_date: date,
    material_slip: bool,
    variance_days: int,
) -> None:
    snapshot = ScheduleSnapshot(
        project_id=project.id,
        imported_at=imported_at,
        source_filename="synthetic.mpp",
        source_path="/tmp/synthetic.mpp",
        source_checksum=f"checksum-{project.id}-{imported_at.isoformat()}",
        current_finish_date=finish_date,
        baseline_finish_date=finish_date - timedelta(days=4),
        task_count=1,
        milestone_count=1,
        critical_task_count=0,
    )
    session.add(snapshot)
    session.flush()
    session.add(
        Milestone(
            snapshot_id=snapshot.id,
            name="Commissioning Gate",
            finish_date=finish_date,
            baseline_finish_date=finish_date - timedelta(days=4),
            material_slip=material_slip,
            variance_from_previous_days=variance_days,
            variance_from_baseline_days=variance_days,
            critical_flag=True,
            percent_complete=0.0,
        )
    )
    session.commit()


def test_health_trend_improving_trajectory(app):
    week_starts = [date(2026, 3, 2), date(2026, 3, 9), date(2026, 3, 16), date(2026, 3, 23)]
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "pyrolysis-petal-2026").one()
        _seed_weekly_updates(session, project, week_starts, settings=app.state.settings)
        _seed_snapshot(session, project, datetime(2026, 3, 2, 12, 0, tzinfo=UTC), material_slips=4)
        _seed_snapshot(session, project, datetime(2026, 3, 9, 12, 0, tzinfo=UTC), material_slips=3)
        _seed_snapshot(session, project, datetime(2026, 3, 16, 12, 0, tzinfo=UTC), material_slips=2)
        _seed_snapshot(session, project, datetime(2026, 3, 23, 12, 0, tzinfo=UTC), material_slips=1)

        trend = health_trend(session, project.id, window_weeks=4, settings=app.state.settings, today=date(2026, 3, 26))
        summary = project_summary(
            session,
            project,
            settings=app.state.settings,
            today=date(2026, 3, 26),
            include_health_history=True,
        )

    assert trend["direction"] == "improving"
    assert trend["slope"] < 0
    assert summary["health_trend_direction"] == "improving"
    assert len(summary["health_trend_history"]) == 4


def test_health_trend_deteriorating_trajectory(app):
    week_starts = [date(2026, 3, 2), date(2026, 3, 9), date(2026, 3, 16), date(2026, 3, 23)]
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "pyrolysis-petal-2026").one()
        _seed_weekly_updates(session, project, week_starts, settings=app.state.settings)
        _seed_snapshot(session, project, datetime(2026, 3, 2, 12, 0, tzinfo=UTC), material_slips=1)
        _seed_snapshot(session, project, datetime(2026, 3, 9, 12, 0, tzinfo=UTC), material_slips=2)
        _seed_snapshot(session, project, datetime(2026, 3, 16, 12, 0, tzinfo=UTC), material_slips=3)
        _seed_snapshot(session, project, datetime(2026, 3, 23, 12, 0, tzinfo=UTC), material_slips=4)

        trend = health_trend(session, project.id, window_weeks=4, settings=app.state.settings, today=date(2026, 3, 26))

    assert trend["direction"] == "deteriorating"
    assert trend["slope"] > 0


def test_health_trend_insufficient_history_fallback(app):
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "pyrolysis-petal-2026").one()
        _seed_weekly_updates(session, project, [date(2026, 3, 23)], settings=app.state.settings)
        _seed_snapshot(session, project, datetime(2026, 3, 23, 12, 0, tzinfo=UTC), material_slips=2)

        trend = health_trend(session, project.id, window_weeks=4, settings=app.state.settings, today=date(2026, 3, 26))

    assert trend["direction"] == "steady"
    assert trend["slope"] == 0.0
    assert trend["history_points"] == 1


def test_leadership_surprise_level_transitions(app):
    today = date(2026, 3, 25)

    with app.state.session_factory() as session:
        low_project = session.query(Project).filter(Project.key == "project-2").one()
        medium_project = session.query(Project).filter(Project.key == "project-3").one()
        high_project = session.query(Project).filter(Project.key == "project-4").one()

        _add_snapshot(
            session,
            low_project,
            imported_at=datetime(2026, 3, 24, tzinfo=UTC),
            finish_date=date(2026, 4, 20),
            material_slip=False,
            variance_days=0,
        )

        _add_snapshot(
            session,
            medium_project,
            imported_at=datetime(2026, 3, 24, tzinfo=UTC),
            finish_date=date(2026, 4, 8),
            material_slip=False,
            variance_days=0,
        )
        create_risk(
            session,
            medium_project,
            RiskCreate(
                title="Safety integration defects rising",
                description=None,
                severity="high",
                trend="worsening",
                source="manual",
            ),
        )
        create_decision(
            session,
            medium_project,
            DecisionCreate(
                summary="Approve overtime budget",
                context=None,
                due_date=today - timedelta(days=1),
                status="pending",
                source="manual",
            ),
        )

        _add_snapshot(
            session,
            high_project,
            imported_at=datetime(2026, 3, 10, tzinfo=UTC),
            finish_date=date(2026, 4, 1),
            material_slip=True,
            variance_days=4,
        )
        _add_snapshot(
            session,
            high_project,
            imported_at=datetime(2026, 3, 15, tzinfo=UTC),
            finish_date=date(2026, 4, 3),
            material_slip=True,
            variance_days=3,
        )
        _add_snapshot(
            session,
            high_project,
            imported_at=datetime(2026, 3, 16, tzinfo=UTC),
            finish_date=date(2026, 4, 5),
            material_slip=True,
            variance_days=3,
        )
        create_risk(
            session,
            high_project,
            RiskCreate(
                title="Cutover vendor failure risk",
                description=None,
                severity="critical",
                trend="worsening",
                source="manual",
            ),
        )
        create_decision(
            session,
            high_project,
            DecisionCreate(
                summary="Sign emergency recovery PO",
                context=None,
                due_date=today - timedelta(days=2),
                status="pending",
                source="manual",
            ),
        )

        low = leadership_surprise_indicator(low_project, today=today, settings=app.state.settings)
        medium = leadership_surprise_indicator(medium_project, today=today, settings=app.state.settings)
        high = leadership_surprise_indicator(high_project, today=today, settings=app.state.settings)

    assert low["level"] == "low"
    assert medium["level"] == "medium"
    assert high["level"] == "high"


def test_portfolio_filter_and_attention_category_for_leadership_surprise(app):
    today = date(2026, 3, 25)

    with app.state.session_factory() as session:
        high_project = session.query(Project).filter(Project.key == "project-5").one()
        _add_snapshot(
            session,
            high_project,
            imported_at=datetime(2026, 3, 10, tzinfo=UTC),
            finish_date=date(2026, 4, 2),
            material_slip=True,
            variance_days=4,
        )
        _add_snapshot(
            session,
            high_project,
            imported_at=datetime(2026, 3, 12, tzinfo=UTC),
            finish_date=date(2026, 4, 4),
            material_slip=True,
            variance_days=4,
        )
        create_risk(
            session,
            high_project,
            RiskCreate(
                title="Vendor mobilization failure",
                description=None,
                severity="critical",
                trend="worsening",
                source="manual",
            ),
        )
        create_decision(
            session,
            high_project,
            DecisionCreate(
                summary="Approve alternate site",
                context=None,
                due_date=today - timedelta(days=1),
                status="pending",
                source="manual",
            ),
        )

        high_only = portfolio_view(session, settings=app.state.settings, today=today, leadership_level="high")
        queue = attention_queue(session, settings=app.state.settings, today=today)

    assert any(item["project_key"] == "project-5" for item in high_only)
    assert any(
        item["category"] == "Leadership Surprise Risk" and item["project_name"] == "Project 5"
        for item in queue
    )
