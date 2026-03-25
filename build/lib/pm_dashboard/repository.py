from __future__ import annotations

from sqlalchemy import select

from .models import ActionItem, ImportRun, Milestone, Project, ScheduleSnapshot, Task


def list_projects(session):
    return session.scalars(select(Project).order_by(Project.id)).all()


def get_project(session, project_id: int):
    return session.get(Project, project_id)


def get_project_by_key(session, key: str):
    return session.scalar(select(Project).where(Project.key == key))


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
