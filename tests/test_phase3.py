from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pm_dashboard.models import Milestone, Project, ProjectDependency, ScheduleSnapshot
from pm_dashboard.parser import ParsedProject, ParsedTask
from pm_dashboard.repository import get_latest_snapshot, list_tasks_for_snapshot
from pm_dashboard.services import (
    DecisionCreate,
    RiskCreate,
    WeeklyUpdateCreate,
    accept_portfolio_summary_draft,
    attention_queue,
    create_decision,
    create_portfolio_summary_draft,
    create_risk,
    detect_resource_conflicts,
    dismiss_portfolio_summary_draft,
    generate_portfolio_executive_summary,
    health_trend,
    import_schedule,
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


def _seed_portfolio_signals(app) -> None:
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "p2c").one()
        create_risk(
            session,
            project,
            RiskCreate(
                title="Vendor FAT delay",
                description="Factory acceptance test moved.",
                severity="high",
                trend="worsening",
                source="manual",
            ),
        )
        create_decision(
            session,
            project,
            DecisionCreate(
                summary="Approve overtime package",
                context="Required to recover commissioning window.",
                owner="Matt",
                due_date=date(2026, 3, 27),
                status="pending",
                source="manual",
            ),
        )


def _parsed_with_external_ref(task_date: date) -> ParsedProject:
    return ParsedProject(
        title="Pyrolysis Petal",
        current_finish_date=task_date,
        baseline_finish_date=task_date,
        tasks=[
            ParsedTask(
                unique_id=11,
                outline_level=1,
                outline_path="1",
                name="Receive handoff package",
                start_date=task_date,
                finish_date=task_date,
                baseline_start_date=task_date,
                baseline_finish_date=task_date,
                percent_complete=25.0,
                critical_flag=True,
                milestone_flag=False,
                predecessor_refs="atlas:UP-45",
                notes="waiting on external project",
                resource_names=[],
                primary_owner=None,
                resource_key=None,
            )
        ],
    )


def _task(
    *,
    unique_id: int,
    name: str,
    start_date: date,
    finish_date: date,
    resource_names: list[str],
    primary_owner: str,
    resource_key: str,
    milestone_flag: bool = False,
) -> ParsedTask:
    return ParsedTask(
        unique_id=unique_id,
        outline_level=1,
        outline_path="1",
        name=name,
        start_date=start_date,
        finish_date=finish_date,
        baseline_start_date=start_date,
        baseline_finish_date=finish_date,
        percent_complete=10.0,
        critical_flag=True,
        milestone_flag=milestone_flag,
        predecessor_refs=None,
        notes=None,
        resource_names=resource_names,
        primary_owner=primary_owner,
        resource_key=resource_key,
    )


def test_health_trend_improving_trajectory(app):
    week_starts = [date(2026, 3, 2), date(2026, 3, 9), date(2026, 3, 16), date(2026, 3, 23)]
    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "p2c").one()
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
        project = session.query(Project).filter(Project.key == "p2c").one()
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
        project = session.query(Project).filter(Project.key == "p2c").one()
        _seed_weekly_updates(session, project, [date(2026, 3, 23)], settings=app.state.settings)
        _seed_snapshot(session, project, datetime(2026, 3, 23, 12, 0, tzinfo=UTC), material_slips=2)

        trend = health_trend(session, project.id, window_weeks=4, settings=app.state.settings, today=date(2026, 3, 26))

    assert trend["direction"] == "steady"
    assert trend["slope"] == 0.0
    assert trend["history_points"] == 1


def test_leadership_surprise_level_transitions(app):
    today = date(2026, 3, 25)

    with app.state.session_factory() as session:
        low_project = session.query(Project).filter(Project.key == "atlas").one()
        medium_project = session.query(Project).filter(Project.key == "mpm").one()
        high_project = session.query(Project).filter(Project.key == "iprd").one()

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
        high_project = session.query(Project).filter(Project.key == "propane-pyrolysis").one()
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

    assert any(item["project_key"] == "propane-pyrolysis" for item in high_only)
    assert any(
        item["category"] == "Leadership Surprise Risk" and item["project_name"] == "Propane Pyrolysis"
        for item in queue
    )


def test_dependency_created_from_external_predecessor(monkeypatch, app, tmp_path: Path):
    sample_file = tmp_path / "sample.mpp"
    sample_file.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr("pm_dashboard.services.parse_mpp_file", lambda *args, **kwargs: _parsed_with_external_ref(date.today()))

    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "p2c").one()
        import_schedule(session, project, sample_file, source_filename=sample_file.name, settings=app.state.settings)
        dependencies = session.query(ProjectDependency).all()

    assert len(dependencies) == 1
    assert dependencies[0].upstream_task_ref == "UP-45"
    assert dependencies[0].status == "blocked"


def test_project_summary_counts_overdue_dependencies(app):
    today = date(2026, 3, 26)
    with app.state.session_factory() as session:
        downstream = session.query(Project).filter(Project.key == "p2c").one()
        upstream = session.query(Project).filter(Project.key == "atlas").one()
        session.add(
            ProjectDependency(
                upstream_project_id=upstream.id,
                downstream_project_id=downstream.id,
                upstream_task_ref="EXT-22",
                downstream_task_ref="Install reactor",
                needed_by_date=today - timedelta(days=2),
                status="open",
                owner="Ana",
                source="manual",
            )
        )
        session.commit()

        summary = project_summary(session, downstream, settings=app.state.settings, today=today)

    assert summary["overdue_dependencies_count"] == 1


def test_attention_queue_flags_blocked_cross_project_dependencies(app):
    today = date(2026, 3, 26)
    with app.state.session_factory() as session:
        downstream = session.query(Project).filter(Project.key == "p2c").one()
        upstream = session.query(Project).filter(Project.key == "atlas").one()
        session.add(
            ProjectDependency(
                upstream_project_id=upstream.id,
                downstream_project_id=downstream.id,
                upstream_task_ref="EXT-99",
                downstream_task_ref="Commissioning prep",
                needed_by_date=today - timedelta(days=1),
                status="blocked",
                owner="Matt",
                source="manual",
            )
        )
        session.commit()

        queue = attention_queue(session, settings=app.state.settings, today=today)

    categories = {item["category"] for item in queue}
    assert "Blocked Cross-Project Dependencies" in categories


def test_phase3_ingests_resource_fields(monkeypatch, app, tmp_path: Path):
    sample_file = tmp_path / "sample.mpp"
    sample_file.write_text("placeholder", encoding="utf-8")

    parsed_project = ParsedProject(
        title="Resource Demo",
        current_finish_date=date(2026, 4, 2),
        baseline_finish_date=date(2026, 4, 1),
        tasks=[
            _task(
                unique_id=100,
                name="Critical install",
                start_date=date(2026, 3, 29),
                finish_date=date(2026, 4, 2),
                resource_names=["Alex Kim", "Ops Team"],
                primary_owner="Alex Kim",
                resource_key="alexkim",
            )
        ],
    )

    monkeypatch.setattr("pm_dashboard.services.parse_mpp_file", lambda *args, **kwargs: parsed_project)

    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "p2c").one()
        import_schedule(session, project, sample_file, source_filename=sample_file.name, settings=app.state.settings)

        snapshot = get_latest_snapshot(session, project.id)
        tasks = list_tasks_for_snapshot(session, snapshot.id)

    assert tasks[0].resource_names == "Alex Kim, Ops Team"
    assert tasks[0].primary_owner == "Alex Kim"
    assert tasks[0].resource_key == "alexkim"


def test_phase3_detects_cross_project_resource_overlap(monkeypatch, app, tmp_path: Path):
    project_a_file = tmp_path / "p2c.mpp"
    project_b_file = tmp_path / "atlas.mpp"
    project_a_file.write_text("placeholder-a", encoding="utf-8")
    project_b_file.write_text("placeholder-b", encoding="utf-8")

    parsed_by_project = {
        "p2c": ParsedProject(
            title="Project A",
            current_finish_date=date(2026, 4, 3),
            baseline_finish_date=date(2026, 4, 1),
            tasks=[
                _task(
                    unique_id=1,
                    name="Startup critical path",
                    start_date=date(2026, 3, 28),
                    finish_date=date(2026, 4, 3),
                    resource_names=["Sam Lee"],
                    primary_owner="Sam Lee",
                    resource_key="samlee",
                    milestone_flag=True,
                )
            ],
        ),
        "atlas": ParsedProject(
            title="Project B",
            current_finish_date=date(2026, 4, 2),
            baseline_finish_date=date(2026, 4, 1),
            tasks=[
                _task(
                    unique_id=2,
                    name="Commissioning gate",
                    start_date=date(2026, 3, 30),
                    finish_date=date(2026, 4, 2),
                    resource_names=["Sam Lee"],
                    primary_owner="Sam Lee",
                    resource_key="samlee",
                )
            ],
        ),
    }

    def fake_parse(file_path, settings):
        return parsed_by_project[file_path.stem]

    monkeypatch.setattr("pm_dashboard.services.parse_mpp_file", fake_parse)

    with app.state.session_factory() as session:
        project_a = session.query(Project).filter(Project.key == "p2c").one()
        project_b = session.query(Project).filter(Project.key == "atlas").one()

        import_schedule(
            session,
            project_a,
            project_a_file,
            source_filename="p2c.mpp",
            settings=app.state.settings,
        )
        import_schedule(
            session,
            project_b,
            project_b_file,
            source_filename="atlas.mpp",
            settings=app.state.settings,
        )

        clusters = detect_resource_conflicts(session, settings=app.state.settings)

    assert clusters
    top = clusters[0]
    assert top["resource_key"] == "samlee"
    assert {"P2C", "Atlas"}.issubset(set(top["impacted_projects"]))


def test_phase3_ranks_conflicts_by_severity(monkeypatch, app, tmp_path: Path):
    project_a_file = tmp_path / "p2c.mpp"
    project_b_file = tmp_path / "atlas.mpp"
    project_a_file.write_text("placeholder-a", encoding="utf-8")
    project_b_file.write_text("placeholder-b", encoding="utf-8")

    parsed_by_project = {
        "p2c": ParsedProject(
            title="Project A",
            current_finish_date=date(2026, 4, 4),
            baseline_finish_date=date(2026, 4, 1),
            tasks=[
                _task(
                    unique_id=1,
                    name="A1",
                    start_date=date(2026, 3, 29),
                    finish_date=date(2026, 4, 4),
                    resource_names=["Taylor"],
                    primary_owner="Taylor",
                    resource_key="taylor",
                    milestone_flag=True,
                ),
                _task(
                    unique_id=2,
                    name="A2",
                    start_date=date(2026, 4, 8),
                    finish_date=date(2026, 4, 10),
                    resource_names=["Jordan"],
                    primary_owner="Jordan",
                    resource_key="jordan",
                ),
            ],
        ),
        "atlas": ParsedProject(
            title="Project B",
            current_finish_date=date(2026, 4, 4),
            baseline_finish_date=date(2026, 4, 1),
            tasks=[
                _task(
                    unique_id=3,
                    name="B1",
                    start_date=date(2026, 3, 30),
                    finish_date=date(2026, 4, 3),
                    resource_names=["Taylor"],
                    primary_owner="Taylor",
                    resource_key="taylor",
                ),
                _task(
                    unique_id=4,
                    name="B2",
                    start_date=date(2026, 4, 9),
                    finish_date=date(2026, 4, 11),
                    resource_names=["Jordan"],
                    primary_owner="Jordan",
                    resource_key="jordan",
                ),
            ],
        ),
    }

    def fake_parse(file_path, settings):
        return parsed_by_project[file_path.stem]

    monkeypatch.setattr("pm_dashboard.services.parse_mpp_file", fake_parse)

    with app.state.session_factory() as session:
        project_a = session.query(Project).filter(Project.key == "p2c").one()
        project_b = session.query(Project).filter(Project.key == "atlas").one()

        import_schedule(
            session,
            project_a,
            project_a_file,
            source_filename="p2c.mpp",
            settings=app.state.settings,
        )
        import_schedule(
            session,
            project_b,
            project_b_file,
            source_filename="atlas.mpp",
            settings=app.state.settings,
        )

        clusters = detect_resource_conflicts(session, settings=app.state.settings)

    by_key = {item["resource_key"]: item for item in clusters}
    assert by_key["taylor"]["severity_score"] > by_key["jordan"]["severity_score"]


def test_generate_portfolio_executive_summary_sections(app):
    _seed_portfolio_signals(app)
    with app.state.session_factory() as session:
        payload = generate_portfolio_executive_summary(session, date(2026, 3, 23), settings=app.state.settings)

    assert payload["overall_status"]
    assert payload["changes_since_last_week"]
    assert isinstance(payload["top_3_risks"], list)
    assert isinstance(payload["decision_asks"], list)
    assert isinstance(payload["next_week_watchlist"], list)


def test_accept_and_dismiss_portfolio_executive_summary_drafts(app):
    _seed_portfolio_signals(app)
    with app.state.session_factory() as session:
        draft = create_portfolio_summary_draft(session, date(2026, 3, 23), settings=app.state.settings)
        accepted = accept_portfolio_summary_draft(
            session,
            draft,
            final_payload={
                **(generate_portfolio_executive_summary(session, date(2026, 3, 23), settings=app.state.settings)),
                "overall_status": "PM final: watch two slips; decisions due this week.",
            },
        )
        dismissed = dismiss_portfolio_summary_draft(
            session,
            create_portfolio_summary_draft(session, date(2026, 3, 30), settings=app.state.settings),
        )

    assert accepted.status == "accepted"
    assert accepted.final_payload
    assert "PM final" in accepted.final_payload
    assert dismissed.status == "dismissed"
