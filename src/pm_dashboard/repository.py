from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select

from .models import (
    ActionItem,
    DecisionItem,
    ImportRun,
    Milestone,
    Project,
    ProjectDependency,
    ProjectFile,
    ResourceItem,
    RiskItem,
    ScheduleSnapshot,
    SuggestionItem,
    Task,
    WeeklyUpdate,
)


def list_projects(session):
    return session.scalars(select(Project).order_by(Project.id)).all()


def get_project(session, project_id: int):
    return session.get(Project, project_id)


def get_project_by_key(session, key: str):
    return session.scalar(select(Project).where(Project.key == key))


def get_project_file(session, project_id: int):
    return session.scalar(select(ProjectFile).where(ProjectFile.project_id == project_id).limit(1))


def list_project_files(session):
    return session.scalars(select(ProjectFile).order_by(ProjectFile.updated_at.desc(), ProjectFile.id.desc())).all()


def get_resource(session, resource_id: int):
    return session.get(ResourceItem, resource_id)


def get_task(session, task_id: int):
    return session.get(Task, task_id)


def list_resources(session, project_id: int | None = None):
    stmt = select(ResourceItem)
    if project_id is not None:
        stmt = stmt.where(ResourceItem.project_id == project_id)
    return session.scalars(stmt.order_by(ResourceItem.name, ResourceItem.id)).all()


def get_latest_snapshot(session, project_id: int):
    return session.scalar(
        select(ScheduleSnapshot)
        .where(ScheduleSnapshot.project_id == project_id)
        .order_by(ScheduleSnapshot.imported_at.desc(), ScheduleSnapshot.id.desc())
        .limit(1)
    )


def get_previous_snapshot(session, project_id: int, exclude_snapshot_id: int):
    return session.scalar(
        select(ScheduleSnapshot)
        .where(ScheduleSnapshot.project_id == project_id, ScheduleSnapshot.id != exclude_snapshot_id)
        .order_by(ScheduleSnapshot.imported_at.desc(), ScheduleSnapshot.id.desc())
        .limit(1)
    )


def list_tasks_for_snapshot(session, snapshot_id: int):
    return session.scalars(select(Task).where(Task.snapshot_id == snapshot_id).order_by(Task.name)).all()


def list_critical_tasks_for_snapshot(session, snapshot_id: int):
    return session.scalars(
        select(Task)
        .where(Task.snapshot_id == snapshot_id, Task.critical_flag.is_(True))
        .order_by(Task.finish_date, Task.name)
    ).all()


def list_milestones_for_snapshot(session, snapshot_id: int):
    return session.scalars(
        select(Milestone).where(Milestone.snapshot_id == snapshot_id).order_by(Milestone.finish_date, Milestone.name)
    ).all()


def list_import_runs(session, limit: int = 30):
    return session.scalars(select(ImportRun).order_by(ImportRun.started_at.desc()).limit(limit)).all()


def list_actions(session, project_id: int, include_closed: bool = True):
    stmt = select(ActionItem).where(ActionItem.project_id == project_id)
    if not include_closed:
        stmt = stmt.where(ActionItem.status != "done")
    return session.scalars(stmt.order_by(ActionItem.due_date, ActionItem.created_at)).all()


def get_weekly_update(session, project_id: int, week_start):
    return session.scalar(
        select(WeeklyUpdate).where(WeeklyUpdate.project_id == project_id, WeeklyUpdate.week_start == week_start).limit(1)
    )


def list_weekly_updates(session, project_id: int | None = None, limit: int = 12):
    stmt = select(WeeklyUpdate)
    if project_id is not None:
        stmt = stmt.where(WeeklyUpdate.project_id == project_id)
    return session.scalars(stmt.order_by(WeeklyUpdate.week_start.desc(), WeeklyUpdate.updated_at.desc()).limit(limit)).all()


def list_risks(session, project_id: int | None = None, include_closed: bool = True):
    stmt = select(RiskItem)
    if project_id is not None:
        stmt = stmt.where(RiskItem.project_id == project_id)
    if not include_closed:
        stmt = stmt.where(RiskItem.status != "closed")
    return session.scalars(stmt.order_by(RiskItem.updated_at.desc(), RiskItem.id.desc())).all()


def list_decisions(session, project_id: int | None = None, include_closed: bool = True):
    stmt = select(DecisionItem)
    if project_id is not None:
        stmt = stmt.where(DecisionItem.project_id == project_id)
    if not include_closed:
        stmt = stmt.where(DecisionItem.status.not_in(["done", "closed"]))
    return session.scalars(stmt.order_by(DecisionItem.due_date, DecisionItem.updated_at.desc())).all()


def list_suggestions(
    session,
    project_id: int | None = None,
    weekly_update_id: int | None = None,
    status: str | None = None,
):
    stmt = select(SuggestionItem)
    if project_id is not None:
        stmt = stmt.where(SuggestionItem.project_id == project_id)
    if weekly_update_id is not None:
        stmt = stmt.where(SuggestionItem.weekly_update_id == weekly_update_id)
    if status is not None:
        stmt = stmt.where(SuggestionItem.status == status)
    return session.scalars(stmt.order_by(SuggestionItem.created_at.desc(), SuggestionItem.id.desc())).all()


def get_suggestion(session, suggestion_id: int):
    return session.get(SuggestionItem, suggestion_id)


def get_risk(session, risk_id: int):
    return session.get(RiskItem, risk_id)


def get_decision(session, decision_id: int):
    return session.get(DecisionItem, decision_id)


def get_weekly_update_by_id(session, update_id: int):
    return session.get(WeeklyUpdate, update_id)


def list_dependencies(
    session,
    include_closed: bool = True,
    source: str | None = None,
    status: str | None = None,
):
    stmt = select(ProjectDependency)
    if not include_closed:
        stmt = stmt.where(ProjectDependency.status.not_in(["closed", "resolved", "done"]))
    if source is not None:
        stmt = stmt.where(ProjectDependency.source == source)
    if status is not None:
        stmt = stmt.where(ProjectDependency.status == status)
    return session.scalars(stmt.order_by(ProjectDependency.needed_by_date, ProjectDependency.id)).all()


def list_dependencies_for_project(session, project_id: int, include_closed: bool = True):
    stmt = select(ProjectDependency).where(
        or_(
            ProjectDependency.upstream_project_id == project_id,
            ProjectDependency.downstream_project_id == project_id,
        )
    )
    if not include_closed:
        stmt = stmt.where(ProjectDependency.status.not_in(["closed", "resolved", "done"]))
    return session.scalars(stmt.order_by(ProjectDependency.needed_by_date, ProjectDependency.id)).all()


def list_overdue_dependencies(session, today: date | None = None):
    today = today or date.today()
    return session.scalars(
        select(ProjectDependency)
        .where(
            ProjectDependency.needed_by_date.is_not(None),
            ProjectDependency.needed_by_date < today,
            ProjectDependency.status.not_in(["closed", "resolved", "done"]),
        )
        .order_by(ProjectDependency.needed_by_date, ProjectDependency.id)
    ).all()
