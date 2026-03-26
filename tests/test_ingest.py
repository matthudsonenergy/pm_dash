from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pm_dashboard.models import Project
from pm_dashboard.parser import ParsedProject, ParsedTask
from pm_dashboard.services import import_schedule, infer_project_from_inputs, project_detail, project_summary


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
                resource_names=[],
                primary_owner=None,
                resource_key=None,
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
                resource_names=[],
                primary_owner=None,
                resource_key=None,
            ),
        ],
    )


def test_import_creates_snapshot_and_material_slip(monkeypatch, app, settings: Path, tmp_path: Path):
    sample_file = tmp_path / "sample.mpp"
    sample_file.write_text("placeholder", encoding="utf-8")

    parsed_versions = [fake_parsed_project(date(2026, 3, 24)), fake_parsed_project(date(2026, 3, 31))]

    def fake_parse(*args, **kwargs):
        return parsed_versions.pop(0)

    monkeypatch.setattr("pm_dashboard.services.parse_mpp_file", fake_parse)

    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "p2c").one()
        import_schedule(session, project, sample_file, source_filename=sample_file.name, settings=app.state.settings)
        import_schedule(session, project, sample_file, source_filename=sample_file.name, settings=app.state.settings)
        summary = project_summary(session, project, settings=app.state.settings, today=date(2026, 3, 25))
        detail = project_detail(session, project, settings=app.state.settings, today=date(2026, 3, 25))

    assert summary["material_slips_count"] == 1
    assert summary["needs_pm_attention_score"] > 0
    assert detail["milestones"][0]["material_slip"] is True
    assert detail["slipped_tasks"][0]["slip_days"] >= 3


def test_import_failure_is_recorded(monkeypatch, app, tmp_path: Path):
    sample_file = tmp_path / "broken.mpp"
    sample_file.write_text("broken", encoding="utf-8")

    def fake_parse(*args, **kwargs):
        raise RuntimeError("parser exploded")

    monkeypatch.setattr("pm_dashboard.services.parse_mpp_file", fake_parse)

    with app.state.session_factory() as session:
        project = session.query(Project).filter(Project.key == "p2c").one()
        with pytest.raises(RuntimeError):
            import_schedule(session, project, sample_file, source_filename=sample_file.name, settings=app.state.settings)
        latest_run = project.import_runs[-1]

    assert latest_run.status == "failed"
    assert "parser exploded" in latest_run.error_message


def test_infer_project_from_filename_aliases():
    assert infer_project_from_inputs("2026 Pyrolysis Petal - 24 Mar 2026.mpp") == "p2c"
    assert infer_project_from_inputs("Atlas_phase1_100h_13Mar-MH.mpp") == "atlas"
    assert infer_project_from_inputs("MPMProject324.mpp") == "mpm"
