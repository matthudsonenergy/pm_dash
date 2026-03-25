from __future__ import annotations

import hashlib
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile

from .config import Settings, get_settings
from .models import ActionItem, ImportRun, Milestone, Project, ScheduleSnapshot, Task
from .parser import ParsedProject, ParsedTask, parse_mpp_file
from .repository import (
    get_latest_snapshot,
    get_previous_snapshot,
    list_actions,
    list_critical_tasks_for_snapshot,
    list_import_runs,
    list_milestones_for_snapshot,
    list_projects,
    list_tasks_for_snapshot,
)
from .scoring import attention_score, confidence_score, is_stale, rag_from_confidence, working_days_between


@dataclass(frozen=True)
class ActionCreate:
    title: str
    owner: str
    due_date: Optional[date]
    notes: Optional[str]
    status: str = "open"


def ensure_storage(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)


def compute_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def material_slip_flag(task: ParsedTask, previous_finish: Optional[date], settings: Settings) -> tuple[bool, Optional[int], Optional[int]]:
    variance_previous = working_days_between(previous_finish, task.finish_date) if previous_finish else None
    variance_baseline = working_days_between(task.baseline_finish_date, task.finish_date)
    is_material = bool(
        (variance_previous is not None and variance_previous >= settings.slip_from_previous_days)
        or (variance_baseline is not None and variance_baseline >= settings.slip_from_baseline_days)
    )
    return is_material, variance_previous, variance_baseline


def import_schedule(
    session,
    project: Project,
    file_path: Path,
    source_filename: str,
    settings: Settings | None = None,
) -> ImportRun:
    settings = settings or get_settings()
    ensure_storage(settings)
    import_run = ImportRun(
        project_id=project.id,
        source_filename=source_filename,
        source_path=str(file_path),
        status="running",
    )
    session.add(import_run)
    session.commit()

    try:
        parsed = parse_mpp_file(file_path, settings)
        snapshot = _persist_snapshot(session, project, file_path, source_filename, parsed, settings)
        import_run.snapshot_id = snapshot.id
        import_run.status = "success"
        import_run.finished_at = datetime.now(UTC)

        if project.key == "pyrolysis-petal-2026" and project.name.startswith("Project"):
            project.name = parsed.title

        session.commit()
        session.refresh(import_run)
        return import_run
    except Exception as exc:
        import_run.status = "failed"
        import_run.error_message = str(exc)
        import_run.finished_at = datetime.now(UTC)
        session.commit()
        session.refresh(import_run)
        raise


def _persist_snapshot(
    session,
    project: Project,
    file_path: Path,
    source_filename: str,
    parsed: ParsedProject,
    settings: Settings,
) -> ScheduleSnapshot:
    checksum = compute_checksum(file_path)
    snapshot = ScheduleSnapshot(
        project_id=project.id,
        source_filename=source_filename,
        source_path=str(file_path),
        source_checksum=checksum,
        current_finish_date=parsed.current_finish_date,
        baseline_finish_date=parsed.baseline_finish_date,
        task_count=len(parsed.tasks),
        milestone_count=sum(1 for task in parsed.tasks if task.milestone_flag),
        critical_task_count=sum(1 for task in parsed.tasks if task.critical_flag),
    )
    session.add(snapshot)
    session.flush()

    previous_snapshot = get_previous_snapshot(session, project.id, snapshot.id)
    previous_milestones = {}
    if previous_snapshot:
        previous_milestones = {
            milestone.name: milestone for milestone in list_milestones_for_snapshot(session, previous_snapshot.id)
        }

    for task in parsed.tasks:
        session.add(
            Task(
                snapshot_id=snapshot.id,
                task_unique_id=task.unique_id,
                outline_level=task.outline_level,
                outline_path=task.outline_path,
                name=task.name,
                start_date=task.start_date,
                finish_date=task.finish_date,
                baseline_start_date=task.baseline_start_date,
                baseline_finish_date=task.baseline_finish_date,
                percent_complete=task.percent_complete,
                critical_flag=task.critical_flag,
                milestone_flag=task.milestone_flag,
                predecessor_refs=task.predecessor_refs,
                notes=task.notes,
            )
        )

        if task.milestone_flag:
            previous_finish = previous_milestones.get(task.name).finish_date if task.name in previous_milestones else None
            material_slip, variance_previous, variance_baseline = material_slip_flag(task, previous_finish, settings)
            session.add(
                Milestone(
                    snapshot_id=snapshot.id,
                    source_task_unique_id=task.unique_id,
                    name=task.name,
                    start_date=task.start_date,
                    finish_date=task.finish_date,
                    baseline_start_date=task.baseline_start_date,
                    baseline_finish_date=task.baseline_finish_date,
                    percent_complete=task.percent_complete,
                    critical_flag=task.critical_flag,
                    predecessor_refs=task.predecessor_refs,
                    variance_from_previous_days=variance_previous,
                    variance_from_baseline_days=variance_baseline,
                    material_slip=material_slip,
                )
            )

    session.commit()
    session.refresh(snapshot)
    return snapshot


def save_upload(upload: UploadFile, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    ensure_storage(settings)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    safe_name = upload.filename or f"upload-{timestamp}.mpp"
    destination = settings.uploads_dir / f"{timestamp}-{safe_name}"
    with destination.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return destination


def create_action(session, project: Project, payload: ActionCreate) -> ActionItem:
    action = ActionItem(
        project_id=project.id,
        title=payload.title,
        owner=payload.owner,
        due_date=payload.due_date,
        notes=payload.notes,
        status=payload.status,
    )
    session.add(action)
    session.commit()
    session.refresh(action)
    return action


def update_action_status(session, action: ActionItem, status: str) -> ActionItem:
    action.status = status
    if status == "done":
        action.completed_at = datetime.now(UTC)
    session.commit()
    session.refresh(action)
    return action


def serialize_action(action: ActionItem) -> dict:
    return {
        "id": action.id,
        "title": action.title,
        "owner": action.owner,
        "due_date": action.due_date.isoformat() if action.due_date else None,
        "status": action.status,
        "notes": action.notes,
    }


def project_summary(session, project: Project, settings: Settings | None = None, today: Optional[date] = None) -> dict:
    settings = settings or get_settings()
    today = today or date.today()
    snapshot = get_latest_snapshot(session, project.id)
    actions = list_actions(session, project.id, include_closed=False)
    overdue_actions = [action for action in actions if action.due_date and action.due_date < today]
    latest_import_date = snapshot.imported_at.date() if snapshot else None
    stale_plan = is_stale(today, latest_import_date, settings.stale_plan_days)

    material_slips = 0
    upcoming_milestones = 0
    next_milestone = None
    recent_schedule_movement = "No recent schedule data"
    overdue_critical_tasks = 0
    latest_finish = snapshot.current_finish_date if snapshot else None

    if snapshot:
        milestones = list_milestones_for_snapshot(session, snapshot.id)
        critical_tasks = list_critical_tasks_for_snapshot(session, snapshot.id)
        material_slips = sum(1 for milestone in milestones if milestone.material_slip)
        overdue_critical_tasks = sum(
            1
            for task in critical_tasks
            if task.finish_date and task.finish_date < today and (task.percent_complete or 0.0) < 100.0
        )
        future_milestones = [milestone for milestone in milestones if milestone.finish_date and milestone.finish_date >= today]
        if future_milestones:
            next_milestone = future_milestones[0]
        upcoming_milestones = sum(
            1
            for milestone in future_milestones
            if (milestone.finish_date - today).days <= settings.upcoming_milestone_days
        )
        recent_schedule_movement = (
            f"{material_slips} material milestone slip(s)"
            if material_slips
            else "No material milestone slips"
        )

    confidence = confidence_score(
        material_slips=material_slips,
        overdue_critical_tasks=overdue_critical_tasks,
        overdue_actions=len(overdue_actions),
        stale_plan=stale_plan,
    )
    attention = attention_score(
        material_slips=material_slips,
        overdue_critical_tasks=overdue_critical_tasks,
        overdue_actions=len(overdue_actions),
        stale_plan=stale_plan,
        upcoming_milestones=upcoming_milestones,
    )

    return {
        "project_id": project.id,
        "project_key": project.key,
        "project_name": project.name,
        "rag_status": rag_from_confidence(confidence),
        "milestone_confidence": confidence,
        "next_major_milestone": next_milestone.name if next_milestone else None,
        "next_major_milestone_date": next_milestone.finish_date.isoformat() if next_milestone and next_milestone.finish_date else None,
        "days_to_next_milestone": (next_milestone.finish_date - today).days if next_milestone and next_milestone.finish_date else None,
        "overdue_actions_count": len(overdue_actions),
        "overdue_dependencies_count": 0,
        "open_decisions_count": 0,
        "recent_schedule_movement": recent_schedule_movement,
        "needs_pm_attention_score": attention,
        "stale_plan": stale_plan,
        "latest_finish_date": latest_finish.isoformat() if latest_finish else None,
        "latest_imported_at": snapshot.imported_at.isoformat() if snapshot else None,
        "material_slips_count": material_slips,
        "overdue_critical_tasks_count": overdue_critical_tasks,
        "top_risks": [],
        "budget_variance": None,
        "confidence_drivers": {
            "material_slips": material_slips,
            "overdue_critical_tasks": overdue_critical_tasks,
            "overdue_actions": len(overdue_actions),
            "stale_plan": stale_plan,
        },
    }


def portfolio_view(session, settings: Settings | None = None, today: Optional[date] = None) -> list[dict]:
    settings = settings or get_settings()
    summaries = [project_summary(session, project, settings, today=today) for project in list_projects(session)]
    ranked = sorted(summaries, key=lambda item: item["needs_pm_attention_score"], reverse=True)
    for index, summary in enumerate(ranked, start=1):
        summary["needs_attention_rank"] = index
    return ranked


def project_detail(session, project: Project, settings: Settings | None = None, today: Optional[date] = None) -> dict:
    settings = settings or get_settings()
    today = today or date.today()
    summary = project_summary(session, project, settings, today=today)
    snapshot = get_latest_snapshot(session, project.id)
    actions = [serialize_action(action) for action in list_actions(session, project.id, include_closed=True)]

    milestones = []
    critical_tasks = []
    slipped_tasks = []

    if snapshot:
        milestone_rows = list_milestones_for_snapshot(session, snapshot.id)
        milestones = [
            {
                "name": row.name,
                "finish_date": row.finish_date.isoformat() if row.finish_date else None,
                "baseline_finish_date": row.baseline_finish_date.isoformat() if row.baseline_finish_date else None,
                "variance_from_previous_days": row.variance_from_previous_days,
                "variance_from_baseline_days": row.variance_from_baseline_days,
                "material_slip": row.material_slip,
            }
            for row in milestone_rows
        ]

        task_rows = list_critical_tasks_for_snapshot(session, snapshot.id)
        critical_tasks = [
            {
                "name": row.name,
                "finish_date": row.finish_date.isoformat() if row.finish_date else None,
                "percent_complete": row.percent_complete,
                "predecessor_refs": row.predecessor_refs,
            }
            for row in task_rows[:15]
        ]

        previous_snapshot = get_previous_snapshot(session, project.id, snapshot.id)
        previous_tasks = {}
        if previous_snapshot:
            previous_tasks = {task.name: task for task in list_tasks_for_snapshot(session, previous_snapshot.id)}
            for task in list_tasks_for_snapshot(session, snapshot.id):
                previous_task = previous_tasks.get(task.name)
                if not previous_task:
                    continue
                slip_days = working_days_between(previous_task.finish_date, task.finish_date)
                if slip_days and slip_days > 0:
                    slipped_tasks.append(
                        {
                            "name": task.name,
                            "previous_finish_date": previous_task.finish_date.isoformat() if previous_task.finish_date else None,
                            "finish_date": task.finish_date.isoformat() if task.finish_date else None,
                            "slip_days": slip_days,
                        }
                    )
        slipped_tasks = sorted(slipped_tasks, key=lambda item: item["slip_days"], reverse=True)[:15]

    return {
        "summary": summary,
        "actions": actions,
        "milestones": milestones,
        "critical_tasks": critical_tasks,
        "slipped_tasks": slipped_tasks,
    }


def attention_queue(session, settings: Settings | None = None, today: Optional[date] = None) -> list[dict]:
    settings = settings or get_settings()
    today = today or date.today()
    queue = []

    for summary in portfolio_view(session, settings, today=today):
        if summary["stale_plan"]:
            queue.append(
                {
                    "project_name": summary["project_name"],
                    "category": "Stale Plan",
                    "detail": "Latest successful import is older than 7 days or missing",
                    "score": 12,
                }
            )

        if summary["overdue_actions_count"]:
            queue.append(
                {
                    "project_name": summary["project_name"],
                    "category": "Overdue Actions",
                    "detail": f"{summary['overdue_actions_count']} action(s) overdue",
                    "score": summary["overdue_actions_count"] * 4,
                }
            )

        project = session.get(Project, summary["project_id"])
        snapshot = get_latest_snapshot(session, project.id)
        if not snapshot:
            continue
        for milestone in list_milestones_for_snapshot(session, snapshot.id):
            if milestone.finish_date and 0 <= (milestone.finish_date - today).days <= settings.upcoming_milestone_days:
                queue.append(
                    {
                        "project_name": project.name,
                        "category": "Upcoming Milestone",
                        "detail": f"{milestone.name} due {milestone.finish_date.isoformat()}",
                        "score": 3,
                    }
                )
            if milestone.material_slip:
                queue.append(
                    {
                        "project_name": project.name,
                        "category": "Material Slip",
                        "detail": f"{milestone.name} slipped by {milestone.variance_from_previous_days or milestone.variance_from_baseline_days} working day(s)",
                        "score": 10,
                    }
                )

    return sorted(queue, key=lambda item: item["score"], reverse=True)


def import_history(session) -> list[dict]:
    rows = []
    for item in list_import_runs(session):
        rows.append(
            {
                "id": item.id,
                "project_name": item.project.name if item.project else str(item.project_id),
                "status": item.status,
                "source_filename": item.source_filename,
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "finished_at": item.finished_at.isoformat() if item.finished_at else None,
                "error_message": item.error_message,
            }
        )
    return rows


def get_project_or_404(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def get_action_or_404(session, action_id: int) -> ActionItem:
    action = session.get(ActionItem, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    return action
