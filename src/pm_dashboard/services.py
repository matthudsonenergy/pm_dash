from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy import select

from .config import Settings, get_settings
from .models import (
    ActionItem,
    DecisionItem,
    ImportRun,
    Milestone,
    Project,
    ProjectDependency,
    PortfolioSummaryDraft,
    RiskItem,
    ScheduleSnapshot,
    SuggestionItem,
    Task,
    WeeklyUpdate,
)
from .parser import ParsedProject, ParsedTask, parse_mpp_file
from .repository import (
    get_decision,
    get_latest_snapshot,
    get_previous_snapshot,
    get_risk,
    get_suggestion,
    get_weekly_update,
    get_weekly_update_by_id,
    list_actions,
    list_critical_tasks_for_snapshot,
    list_decisions,
    list_dependencies,
    list_dependencies_for_project,
    list_import_runs,
    list_milestones_for_snapshot,
    list_projects,
    list_risks,
    list_suggestions,
    list_tasks_for_snapshot,
    list_overdue_dependencies,
    list_weekly_updates,
)
from .scoring import attention_score, confidence_score, is_stale, rag_from_confidence, working_days_between


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
ACTION_OWNER_RE = re.compile(r"owner\s*[:=]\s*([^;|]+)", re.IGNORECASE)
ACTION_DUE_RE = re.compile(r"(?:due|by)\s*[:=]?\s*(20\d{2}-\d{2}-\d{2})", re.IGNORECASE)
ACTION_LEADING_OWNER_RE = re.compile(r"^\s*([A-Z][A-Za-z .'-]{1,60})\s+to\s+(.+)$")
TEXT_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
DEPENDENCY_REF_RE = re.compile(r"([a-z0-9-]+)\s*[:/#]\s*([A-Za-z0-9_.-]+)", re.IGNORECASE)


@dataclass(frozen=True)
class ActionCreate:
    title: str
    owner: str
    due_date: Optional[date]
    notes: Optional[str]
    status: str = "open"


@dataclass(frozen=True)
class WeeklyUpdateCreate:
    week_start: date
    status_summary: Optional[str]
    blockers: Optional[str]
    approvals_needed: Optional[str]
    follow_ups: Optional[str]
    confidence_note: Optional[str]
    meeting_notes: Optional[str]
    status_notes: Optional[str]
    needs_escalation: bool = False
    leadership_watch: bool = False


@dataclass(frozen=True)
class RiskCreate:
    title: str
    description: Optional[str]
    category: str = "risk"
    severity: str = "medium"
    owner: Optional[str] = None
    due_date: Optional[date] = None
    status: str = "open"
    mitigation: Optional[str] = None
    source: str = "manual"
    trend: str = "steady"
    weekly_update_id: Optional[int] = None


@dataclass(frozen=True)
class DecisionCreate:
    summary: str
    context: Optional[str]
    owner: Optional[str] = None
    due_date: Optional[date] = None
    status: str = "pending"
    impact: Optional[str] = None
    source: str = "manual"
    weekly_update_id: Optional[int] = None


def ensure_storage(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)


def compute_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_week_start(today: Optional[date] = None) -> date:
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def week_end(week_start: date) -> date:
    return week_start + timedelta(days=6)


def parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(value)


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def is_open_dependency_status(status: str) -> bool:
    return (status or "").lower() not in {"closed", "resolved", "done"}


def parse_external_dependency_ref(value: Optional[str]) -> Optional[tuple[str, str]]:
    if not value:
        return None
    match = DEPENDENCY_REF_RE.search(value)
    if not match:
        return None
    return match.group(1).lower(), match.group(2).strip()


def _json_dumps(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True)


def _json_loads(payload: str) -> dict:
    return json.loads(payload) if payload else {}


def _clean_line(line: str) -> str:
    return re.sub(r"^[-*]\s*", "", line).strip()


def split_lines(*sections: Optional[str]) -> list[str]:
    lines: list[str] = []
    for section in sections:
        if not section:
            continue
        for line in section.splitlines():
            cleaned = _clean_line(line)
            if cleaned:
                lines.append(cleaned)
    return lines


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.get((severity or "").lower(), 99)


def material_slip_flag(task: ParsedTask, previous_finish: Optional[date], settings: Settings) -> tuple[bool, Optional[int], Optional[int]]:
    variance_previous = working_days_between(previous_finish, task.finish_date) if previous_finish else None
    variance_baseline = working_days_between(task.baseline_finish_date, task.finish_date)
    is_material = bool(
        (variance_previous is not None and variance_previous >= settings.slip_from_previous_days)
        or (variance_baseline is not None and variance_baseline >= settings.slip_from_baseline_days)
    )
    return is_material, variance_previous, variance_baseline


def save_upload(upload: UploadFile, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    ensure_storage(settings)
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    safe_name = upload.filename or f"upload-{timestamp}.mpp"
    destination = settings.uploads_dir / f"{timestamp}-{safe_name}"
    with destination.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return destination


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
                resource_names=", ".join(task.resource_names) if task.resource_names else None,
                primary_owner=task.primary_owner,
                resource_key=task.resource_key,
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

    session.flush()
    _refresh_cross_project_dependencies(session, project, snapshot.id)
    session.commit()
    session.refresh(snapshot)
    return snapshot

def _refresh_cross_project_dependencies(session, downstream_project: Project, snapshot_id: int) -> None:
    session.query(ProjectDependency).filter(
        ProjectDependency.downstream_project_id == downstream_project.id,
        ProjectDependency.source == "import",
    ).delete(synchronize_session=False)

    tasks = list_tasks_for_snapshot(session, snapshot_id)
    known_projects = {item.key.lower(): item.id for item in list_projects(session)}

    for task in tasks:
        parsed_ref = parse_external_dependency_ref(task.predecessor_refs)
        if not parsed_ref:
            continue
        upstream_key, upstream_task_ref = parsed_ref
        upstream_project_id = known_projects.get(upstream_key)
        if not upstream_project_id or upstream_project_id == downstream_project.id:
            continue
        dependency = ProjectDependency(
            upstream_project_id=upstream_project_id,
            downstream_project_id=downstream_project.id,
            upstream_task_ref=upstream_task_ref,
            downstream_task_ref=task.name,
            needed_by_date=task.start_date or task.finish_date,
            status="blocked" if (task.percent_complete or 0.0) < 100.0 else "resolved",
            owner=None,
            source="import",
        )
        session.add(dependency)


def _normalize_resource_key(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return "".join(char.lower() for char in value if char.isalnum())


def _task_window(task: Task) -> tuple[Optional[date], Optional[date]]:
    if task.start_date and task.finish_date:
        start, finish = sorted([task.start_date, task.finish_date])
        return start, finish
    point = task.finish_date or task.start_date
    return point, point


def _overlap_days(start_a: date, end_a: date, start_b: date, end_b: date) -> int:
    latest_start = max(start_a, start_b)
    earliest_end = min(end_a, end_b)
    if earliest_end < latest_start:
        return 0
    return (earliest_end - latest_start).days + 1


def detect_resource_conflicts(
    session,
    settings: Settings | None = None,
    today: Optional[date] = None,
    due_window_days: int = 14,
) -> list[dict]:
    settings = settings or get_settings()
    today = today or date.today()
    entries_by_resource: dict[str, list[dict]] = defaultdict(list)

    for project in list_projects(session):
        snapshot = get_latest_snapshot(session, project.id)
        if not snapshot:
            continue
        for task in list_critical_tasks_for_snapshot(session, snapshot.id):
            start, finish = _task_window(task)
            if not start or not finish:
                continue
            resource_key = task.resource_key or _normalize_resource_key(task.primary_owner)
            if not resource_key and task.resource_names:
                resource_key = _normalize_resource_key(task.resource_names.split(",")[0].strip())
            if not resource_key:
                continue
            label = task.primary_owner or (task.resource_names.split(",")[0].strip() if task.resource_names else resource_key)
            entries_by_resource[resource_key].append(
                {
                    "resource_key": resource_key,
                    "resource_label": label,
                    "project_id": project.id,
                    "project_name": project.name,
                    "task_name": task.name,
                    "start_date": start,
                    "finish_date": finish,
                    "critical_flag": bool(task.critical_flag),
                    "milestone_flag": bool(task.milestone_flag),
                }
            )

    clusters: list[dict] = []
    for resource_key, entries in entries_by_resource.items():
        if len({entry["project_id"] for entry in entries}) < 2:
            continue
        conflicts: list[dict] = []
        for left, right in combinations(entries, 2):
            if left["project_id"] == right["project_id"]:
                continue
            overlap_days = _overlap_days(left["start_date"], left["finish_date"], right["start_date"], right["finish_date"])
            due_gap_days = abs((left["finish_date"] - right["finish_date"]).days)
            due_window_overlap = due_gap_days <= due_window_days
            if overlap_days <= 0 and not due_window_overlap:
                continue
            criticality_weight = 4 if left["critical_flag"] and right["critical_flag"] else 2
            if left["milestone_flag"] or right["milestone_flag"]:
                criticality_weight += 1
            overlap_weight = overlap_days * 1.5 if overlap_days else 0.5
            due_window_weight = max(0.0, (due_window_days - due_gap_days) / max(due_window_days, 1))
            severity = round(criticality_weight + overlap_weight + due_window_weight, 2)
            conflicts.append(
                {
                    "projects": [left["project_name"], right["project_name"]],
                    "tasks": [left["task_name"], right["task_name"]],
                    "start_date": min(left["start_date"], right["start_date"]).isoformat(),
                    "finish_date": max(left["finish_date"], right["finish_date"]).isoformat(),
                    "overlap_days": overlap_days,
                    "due_gap_days": due_gap_days,
                    "severity": severity,
                }
            )
        if not conflicts:
            continue
        conflicts.sort(key=lambda item: item["severity"], reverse=True)
        projects = sorted({project for item in conflicts for project in item["projects"]})
        clusters.append(
            {
                "resource_key": resource_key,
                "resource_label": entries[0]["resource_label"],
                "severity_score": round(sum(item["severity"] for item in conflicts), 2),
                "conflict_count": len(conflicts),
                "impacted_projects": projects,
                "window_start": min(item["start_date"] for item in conflicts),
                "window_end": max(item["finish_date"] for item in conflicts),
                "conflicts": conflicts,
            }
        )

    return sorted(clusters, key=lambda item: (item["severity_score"], item["conflict_count"]), reverse=True)


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


def create_risk(session, project: Project, payload: RiskCreate) -> RiskItem:
    risk = RiskItem(
        project_id=project.id,
        weekly_update_id=payload.weekly_update_id,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        severity=payload.severity,
        owner=payload.owner,
        due_date=payload.due_date,
        status=payload.status,
        mitigation=payload.mitigation,
        source=payload.source,
        trend=payload.trend,
    )
    session.add(risk)
    session.commit()
    session.refresh(risk)
    return risk


def update_risk(session, risk: RiskItem, updates: dict[str, Any]) -> RiskItem:
    for field in ["title", "description", "category", "severity", "owner", "status", "mitigation", "source", "trend"]:
        if field in updates and updates[field] is not None:
            setattr(risk, field, updates[field])
    if "due_date" in updates:
        risk.due_date = updates["due_date"]
    session.commit()
    session.refresh(risk)
    return risk


def create_decision(session, project: Project, payload: DecisionCreate) -> DecisionItem:
    decision = DecisionItem(
        project_id=project.id,
        weekly_update_id=payload.weekly_update_id,
        summary=payload.summary,
        context=payload.context,
        owner=payload.owner,
        due_date=payload.due_date,
        status=payload.status,
        impact=payload.impact,
        source=payload.source,
    )
    session.add(decision)
    session.commit()
    session.refresh(decision)
    return decision


def update_decision(session, decision: DecisionItem, updates: dict[str, Any]) -> DecisionItem:
    for field in ["summary", "context", "owner", "status", "impact", "source"]:
        if field in updates and updates[field] is not None:
            setattr(decision, field, updates[field])
    if "due_date" in updates:
        decision.due_date = updates["due_date"]
    session.commit()
    session.refresh(decision)
    return decision


def serialize_action(action: ActionItem) -> dict:
    return {
        "id": action.id,
        "title": action.title,
        "owner": action.owner,
        "due_date": action.due_date.isoformat() if action.due_date else None,
        "status": action.status,
        "notes": action.notes,
    }


def serialize_risk(risk: RiskItem) -> dict:
    return {
        "id": risk.id,
        "title": risk.title,
        "description": risk.description,
        "category": risk.category,
        "severity": risk.severity,
        "owner": risk.owner,
        "due_date": risk.due_date.isoformat() if risk.due_date else None,
        "status": risk.status,
        "mitigation": risk.mitigation,
        "source": risk.source,
        "trend": risk.trend,
    }


def serialize_decision(decision: DecisionItem) -> dict:
    return {
        "id": decision.id,
        "summary": decision.summary,
        "context": decision.context,
        "owner": decision.owner,
        "due_date": decision.due_date.isoformat() if decision.due_date else None,
        "status": decision.status,
        "impact": decision.impact,
        "source": decision.source,
    }


def serialize_weekly_update(update: WeeklyUpdate) -> dict:
    return {
        "id": update.id,
        "week_start": update.week_start.isoformat(),
        "status_summary": update.status_summary,
        "blockers": update.blockers,
        "approvals_needed": update.approvals_needed,
        "follow_ups": update.follow_ups,
        "confidence_note": update.confidence_note,
        "meeting_notes": update.meeting_notes,
        "status_notes": update.status_notes,
        "needs_escalation": update.needs_escalation,
        "leadership_watch": update.leadership_watch,
        "updated_at": update.updated_at.isoformat() if update.updated_at else None,
    }


def serialize_suggestion(suggestion: SuggestionItem) -> dict:
    payload = _json_loads(suggestion.proposed_payload)
    return {
        "id": suggestion.id,
        "project_id": suggestion.project_id,
        "weekly_update_id": suggestion.weekly_update_id,
        "suggestion_type": suggestion.suggestion_type,
        "title": suggestion.title,
        "payload": payload,
        "rationale": suggestion.rationale,
        "status": suggestion.status,
        "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
        "reviewed_at": suggestion.reviewed_at.isoformat() if suggestion.reviewed_at else None,
    }

def serialize_dependency(item: ProjectDependency) -> dict:
    return {
        "id": item.id,
        "upstream_project_id": item.upstream_project_id,
        "upstream_project_name": item.upstream_project.name if item.upstream_project else None,
        "downstream_project_id": item.downstream_project_id,
        "downstream_project_name": item.downstream_project.name if item.downstream_project else None,
        "upstream_task_ref": item.upstream_task_ref,
        "downstream_task_ref": item.downstream_task_ref,
        "needed_by_date": item.needed_by_date.isoformat() if item.needed_by_date else None,
        "status": item.status,
        "owner": item.owner,
        "source": item.source,
    }


def serialize_portfolio_summary_draft(draft: PortfolioSummaryDraft) -> dict:
    return {
        "id": draft.id,
        "week_start": draft.week_start.isoformat(),
        "draft": _json_loads(draft.draft_payload),
        "final": _json_loads(draft.final_payload) if draft.final_payload else None,
        "status": draft.status,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "reviewed_at": draft.reviewed_at.isoformat() if draft.reviewed_at else None,
    }


def _extract_owner_due_title(line: str) -> tuple[str, Optional[str], Optional[date], list[str]]:
    raw = line.strip()
    missing: list[str] = []
    owner = None
    due_date = None
    title = raw

    owner_match = ACTION_OWNER_RE.search(raw)
    if owner_match:
        owner = owner_match.group(1).strip()
        title = ACTION_OWNER_RE.sub("", title).strip(" |;,-")

    due_match = ACTION_DUE_RE.search(raw)
    if due_match:
        due_date = parse_date(due_match.group(1))
        title = ACTION_DUE_RE.sub("", title).strip(" |;,-")

    if not owner:
        leading_owner = ACTION_LEADING_OWNER_RE.match(raw)
        if leading_owner:
            owner = leading_owner.group(1).strip()
            title = leading_owner.group(2).strip()

    if not due_date:
        embedded_date = TEXT_DATE_RE.search(raw)
        if embedded_date:
            due_date = parse_date(embedded_date.group(1))
            title = title.replace(embedded_date.group(1), "").strip(" |;,-")

    title = re.sub(r"^(action|decision|risk)\s*:\s*", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"\s{2,}", " ", title)

    if not owner:
        missing.append("owner")
    if not due_date:
        missing.append("due date")

    return title or raw, owner, due_date, missing


def _suggestion_title(prefix: str, body: str) -> str:
    clean = body.strip()
    if len(clean) > 80:
        clean = clean[:77].rstrip() + "..."
    return f"{prefix}: {clean}"


def _add_suggestion(
    session,
    *,
    project_id: int,
    weekly_update_id: Optional[int],
    suggestion_type: str,
    title: str,
    payload: dict,
    rationale: str,
) -> SuggestionItem:
    suggestion = SuggestionItem(
        project_id=project_id,
        weekly_update_id=weekly_update_id,
        suggestion_type=suggestion_type,
        title=title,
        proposed_payload=_json_dumps(payload),
        rationale=rationale,
        status="pending",
    )
    session.add(suggestion)
    return suggestion


def build_milestone_change_summary(session, project: Project, settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    snapshot = get_latest_snapshot(session, project.id)
    if not snapshot:
        return []
    previous_snapshot = get_previous_snapshot(session, project.id, snapshot.id)
    if not previous_snapshot:
        return []

    previous_tasks = {task.name: task for task in list_tasks_for_snapshot(session, previous_snapshot.id)}
    changes: list[str] = []
    for task in list_tasks_for_snapshot(session, snapshot.id):
        previous_task = previous_tasks.get(task.name)
        if not previous_task:
            continue
        slip_days = working_days_between(previous_task.finish_date, task.finish_date)
        if slip_days and slip_days > 0:
            changes.append(f"{task.name} slipped by {slip_days} working day(s)")
    return changes[:5]


def generate_weekly_suggestions(
    session,
    project: Project,
    weekly_update: WeeklyUpdate,
    settings: Settings | None = None,
) -> list[SuggestionItem]:
    settings = settings or get_settings()
    for suggestion in list_suggestions(session, weekly_update_id=weekly_update.id, status="pending"):
        session.delete(suggestion)
    session.flush()

    suggestions: list[SuggestionItem] = []

    for line in split_lines(weekly_update.follow_ups):
        title, owner, due_date, missing = _extract_owner_due_title(line)
        rationale = "Created from follow-up text."
        if missing:
            rationale += f" Missing {' and '.join(missing)}."
        suggestions.append(
            _add_suggestion(
                session,
                project_id=project.id,
                weekly_update_id=weekly_update.id,
                suggestion_type="action",
                title=_suggestion_title("Action", title),
                payload={
                    "title": title,
                    "owner": owner or "Unassigned",
                    "due_date": due_date.isoformat() if due_date else None,
                    "notes": f"Suggested from weekly update {weekly_update.week_start.isoformat()}",
                    "status": "open",
                },
                rationale=rationale,
            )
        )

    for line in split_lines(weekly_update.meeting_notes, weekly_update.status_notes):
        if line.lower().startswith("action:"):
            title, owner, due_date, missing = _extract_owner_due_title(line)
            rationale = "Detected explicit action marker in notes."
            if missing:
                rationale += f" Missing {' and '.join(missing)}."
            suggestions.append(
                _add_suggestion(
                    session,
                    project_id=project.id,
                    weekly_update_id=weekly_update.id,
                    suggestion_type="action",
                    title=_suggestion_title("Action", title),
                    payload={
                        "title": title,
                        "owner": owner or "Unassigned",
                        "due_date": due_date.isoformat() if due_date else None,
                        "notes": f"Suggested from notes for week {weekly_update.week_start.isoformat()}",
                        "status": "open",
                    },
                    rationale=rationale,
                )
            )

    risk_lines = split_lines(weekly_update.blockers)
    for line in split_lines(weekly_update.status_notes, weekly_update.meeting_notes):
        lowered = line.lower()
        if lowered.startswith("risk:") or "blocker" in lowered or "at risk" in lowered:
            risk_lines.append(line)

    seen_risk_lines = set()
    for line in risk_lines:
        normalized = line.lower()
        if normalized in seen_risk_lines:
            continue
        seen_risk_lines.add(normalized)
        severity = "high" if weekly_update.needs_escalation or weekly_update.leadership_watch else "medium"
        trend = "worsening" if weekly_update.needs_escalation or "delay" in normalized or "slip" in normalized else "new"
        title = re.sub(r"^(risk|blocker)\s*:\s*", "", line, flags=re.IGNORECASE).strip()
        suggestions.append(
            _add_suggestion(
                session,
                project_id=project.id,
                weekly_update_id=weekly_update.id,
                suggestion_type="risk",
                title=_suggestion_title("Risk", title),
                payload={
                    "title": title,
                    "description": line,
                    "category": "issue" if "blocker" in normalized else "risk",
                    "severity": severity,
                    "owner": None,
                    "due_date": None,
                    "status": "open",
                    "mitigation": None,
                    "source": "suggested",
                    "trend": trend,
                },
                rationale="Derived from blockers or risk language in the weekly update.",
            )
        )

    decision_lines = split_lines(weekly_update.approvals_needed)
    for line in split_lines(weekly_update.meeting_notes, weekly_update.status_notes):
        if line.lower().startswith("decision:"):
            decision_lines.append(line)

    for line in decision_lines:
        title, owner, due_date, missing = _extract_owner_due_title(line)
        rationale = "Derived from approvals needed or explicit decision marker."
        if missing:
            rationale += f" Missing {' and '.join(missing)}."
        suggestions.append(
            _add_suggestion(
                session,
                project_id=project.id,
                weekly_update_id=weekly_update.id,
                suggestion_type="decision",
                title=_suggestion_title("Decision", title),
                payload={
                    "summary": title,
                    "context": line,
                    "owner": owner,
                    "due_date": due_date.isoformat() if due_date else None,
                    "status": "pending",
                    "impact": weekly_update.confidence_note,
                    "source": "suggested",
                },
                rationale=rationale,
            )
        )

    milestone_changes = build_milestone_change_summary(session, project, settings)
    overdue_actions = [
        action for action in list_actions(session, project.id, include_closed=False) if action.due_date and action.due_date < date.today()
    ]
    summary_parts = []
    if weekly_update.status_summary:
        summary_parts.append(weekly_update.status_summary.strip())
    if milestone_changes:
        summary_parts.append("Milestone changes: " + "; ".join(milestone_changes))
    if weekly_update.blockers:
        summary_parts.append("Blockers: " + "; ".join(split_lines(weekly_update.blockers)))
    if overdue_actions:
        summary_parts.append(f"{len(overdue_actions)} overdue action(s) require follow-up.")
    if weekly_update.confidence_note:
        summary_parts.append("Confidence note: " + weekly_update.confidence_note.strip())
    if not summary_parts:
        summary_parts.append("No weekly narrative provided.")

    suggestions.append(
        _add_suggestion(
            session,
            project_id=project.id,
            weekly_update_id=weekly_update.id,
            suggestion_type="summary",
            title=f"Weekly status draft for {project.name}",
            payload={
                "summary_text": " ".join(summary_parts),
                "week_start": weekly_update.week_start.isoformat(),
                "milestone_changes": milestone_changes,
            },
            rationale="Generated from the weekly update form and schedule snapshot comparison.",
        )
    )

    reminder_parts = []
    if split_lines(weekly_update.approvals_needed):
        reminder_parts.append("Chase approvals: " + "; ".join(split_lines(weekly_update.approvals_needed)[:3]))
    if split_lines(weekly_update.follow_ups):
        reminder_parts.append("Follow up on actions: " + "; ".join(split_lines(weekly_update.follow_ups)[:3]))
    if overdue_actions:
        reminder_parts.append(f"Overdue actions open: {len(overdue_actions)}")
    if reminder_parts:
        suggestions.append(
            _add_suggestion(
                session,
                project_id=project.id,
                weekly_update_id=weekly_update.id,
                suggestion_type="reminder",
                title=f"Reminder draft for {project.name}",
                payload={
                    "message_text": " | ".join(reminder_parts),
                    "audience_label": "Project owners",
                    "week_start": weekly_update.week_start.isoformat(),
                },
                rationale="Generated from approvals, follow-ups, and overdue actions.",
            )
        )

    session.commit()
    for suggestion in suggestions:
        session.refresh(suggestion)
    return suggestions


def upsert_weekly_update(
    session,
    project: Project,
    payload: WeeklyUpdateCreate,
    settings: Settings | None = None,
) -> WeeklyUpdate:
    settings = settings or get_settings()
    weekly_update = get_weekly_update(session, project.id, payload.week_start)
    if not weekly_update:
        weekly_update = WeeklyUpdate(project_id=project.id, week_start=payload.week_start)
        session.add(weekly_update)
        session.flush()

    weekly_update.status_summary = payload.status_summary
    weekly_update.blockers = payload.blockers
    weekly_update.approvals_needed = payload.approvals_needed
    weekly_update.follow_ups = payload.follow_ups
    weekly_update.confidence_note = payload.confidence_note
    weekly_update.meeting_notes = payload.meeting_notes
    weekly_update.status_notes = payload.status_notes
    weekly_update.needs_escalation = payload.needs_escalation
    weekly_update.leadership_watch = payload.leadership_watch

    session.commit()
    session.refresh(weekly_update)
    generate_weekly_suggestions(session, project, weekly_update, settings=settings)
    session.refresh(weekly_update)
    return weekly_update


def update_weekly_update(
    session,
    weekly_update: WeeklyUpdate,
    payload: WeeklyUpdateCreate,
    settings: Settings | None = None,
) -> WeeklyUpdate:
    project = weekly_update.project
    existing = get_weekly_update(session, weekly_update.project_id, payload.week_start)
    if existing and existing.id != weekly_update.id:
        raise HTTPException(status_code=400, detail="A weekly update already exists for that project/week")

    weekly_update.week_start = payload.week_start
    weekly_update.status_summary = payload.status_summary
    weekly_update.blockers = payload.blockers
    weekly_update.approvals_needed = payload.approvals_needed
    weekly_update.follow_ups = payload.follow_ups
    weekly_update.confidence_note = payload.confidence_note
    weekly_update.meeting_notes = payload.meeting_notes
    weekly_update.status_notes = payload.status_notes
    weekly_update.needs_escalation = payload.needs_escalation
    weekly_update.leadership_watch = payload.leadership_watch
    session.commit()
    session.refresh(weekly_update)
    generate_weekly_suggestions(session, project, weekly_update, settings=settings)
    session.refresh(weekly_update)
    return weekly_update


def accept_suggestion(session, suggestion: SuggestionItem, payload_override: Optional[dict] = None) -> SuggestionItem:
    if suggestion.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending suggestions can be accepted")

    payload = _json_loads(suggestion.proposed_payload)
    if payload_override:
        payload.update(payload_override)

    project = suggestion.project
    if suggestion.suggestion_type == "action":
        create_action(
            session,
            project,
            ActionCreate(
                title=payload["title"],
                owner=payload.get("owner") or "Unassigned",
                due_date=parse_date(payload.get("due_date")),
                notes=payload.get("notes"),
                status=payload.get("status", "open"),
            ),
        )
    elif suggestion.suggestion_type == "risk":
        create_risk(
            session,
            project,
            RiskCreate(
                title=payload["title"],
                description=payload.get("description"),
                category=payload.get("category", "risk"),
                severity=payload.get("severity", "medium"),
                owner=payload.get("owner"),
                due_date=parse_date(payload.get("due_date")),
                status=payload.get("status", "open"),
                mitigation=payload.get("mitigation"),
                source=payload.get("source", "suggested"),
                trend=payload.get("trend", "steady"),
                weekly_update_id=suggestion.weekly_update_id,
            ),
        )
    elif suggestion.suggestion_type == "decision":
        create_decision(
            session,
            project,
            DecisionCreate(
                summary=payload["summary"],
                context=payload.get("context"),
                owner=payload.get("owner"),
                due_date=parse_date(payload.get("due_date")),
                status=payload.get("status", "pending"),
                impact=payload.get("impact"),
                source=payload.get("source", "suggested"),
                weekly_update_id=suggestion.weekly_update_id,
            ),
        )

    suggestion.proposed_payload = _json_dumps(payload)
    suggestion.status = "accepted"
    suggestion.reviewed_at = datetime.now(UTC)
    session.commit()
    session.refresh(suggestion)
    return suggestion


def dismiss_suggestion(session, suggestion: SuggestionItem) -> SuggestionItem:
    if suggestion.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending suggestions can be dismissed")
    suggestion.status = "dismissed"
    suggestion.reviewed_at = datetime.now(UTC)
    session.commit()
    session.refresh(suggestion)
    return suggestion


def _health_score(
    *,
    material_slips: int,
    overdue_actions: int,
    stale_plan: bool,
    unresolved_risks_decisions: int,
) -> int:
    return (material_slips * 5) + (overdue_actions * 3) + (8 if stale_plan else 0) + (unresolved_risks_decisions * 2)


def project_health_history(
    session,
    project_id: int,
    window_weeks: int = 4,
    settings: Settings | None = None,
    today: Optional[date] = None,
) -> list[dict]:
    settings = settings or get_settings()
    today = today or date.today()
    if window_weeks < 1:
        return []

    current_week = current_week_start(today)
    week_starts = [current_week - timedelta(weeks=offset) for offset in range(window_weeks - 1, -1, -1)]
    weekly_by_start = {item.week_start: item for item in list_weekly_updates(session, project_id, limit=window_weeks * 3)}
    if not weekly_by_start:
        return []

    snapshots = session.scalars(
        select(ScheduleSnapshot)
        .where(ScheduleSnapshot.project_id == project_id)
        .order_by(ScheduleSnapshot.imported_at.asc(), ScheduleSnapshot.id.asc())
    ).all()

    actions = list_actions(session, project_id, include_closed=True)
    risks = list_risks(session, project_id, include_closed=True)
    decisions = list_decisions(session, project_id, include_closed=True)

    history: list[dict] = []
    for week_start in week_starts:
        weekly_update = weekly_by_start.get(week_start)
        if not weekly_update:
            continue
        week_finish = week_end(week_start)
        week_finish_dt = datetime.combine(week_finish, datetime.max.time(), tzinfo=UTC)

        snapshot = None
        for candidate in snapshots:
            if candidate.imported_at.date() <= week_finish:
                snapshot = candidate
            else:
                break

        material_slips = 0
        latest_import_date = None
        if snapshot:
            latest_import_date = snapshot.imported_at.date()
            material_slips = sum(1 for milestone in list_milestones_for_snapshot(session, snapshot.id) if milestone.material_slip)

        overdue_actions = len(
            [
                action
                for action in actions
                if action.created_at <= week_finish_dt
                and action.due_date
                and action.due_date < week_finish
                and action.status != "done"
            ]
        )
        unresolved_risks_decisions = len(
            [
                risk
                for risk in risks
                if risk.created_at <= week_finish_dt and risk.status != "closed"
            ]
        ) + len(
            [
                decision
                for decision in decisions
                if decision.created_at <= week_finish_dt and decision.status not in {"done", "closed"}
            ]
        )
        stale_plan = is_stale(week_finish, latest_import_date, settings.stale_plan_days)
        health_score = _health_score(
            material_slips=material_slips,
            overdue_actions=overdue_actions,
            stale_plan=stale_plan,
            unresolved_risks_decisions=unresolved_risks_decisions,
        )

        history.append(
            {
                "week_start": week_start.isoformat(),
                "health_score": health_score,
                "material_slips": material_slips,
                "overdue_actions": overdue_actions,
                "stale_plan": stale_plan,
                "unresolved_risks_decisions": unresolved_risks_decisions,
            }
        )
    return history


def health_trend(
    session,
    project_id: int,
    window_weeks: int = 4,
    settings: Settings | None = None,
    today: Optional[date] = None,
) -> dict:
    history = project_health_history(session, project_id, window_weeks=window_weeks, settings=settings, today=today)
    if len(history) < 2:
        return {"direction": "steady", "slope": 0.0, "history_points": len(history), "history": history}

    y_values = [point["health_score"] for point in history]
    x_values = list(range(len(y_values)))
    mean_x = sum(x_values) / len(x_values)
    mean_y = sum(y_values) / len(y_values)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
    denominator = sum((x - mean_x) ** 2 for x in x_values) or 1.0
    slope = numerator / denominator

    if slope >= 0.5:
        direction = "deteriorating"
    elif slope <= -0.5:
        direction = "improving"
    else:
        direction = "steady"
    return {"direction": direction, "slope": round(slope, 3), "history_points": len(history), "history": history}


def project_summary(
    session,
    project: Project,
    settings: Settings | None = None,
    today: Optional[date] = None,
    include_health_history: bool = False,
) -> dict:
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

    open_risks = [risk for risk in list_risks(session, project.id, include_closed=False) if risk.status != "closed"]
    open_decisions = [
        decision
        for decision in list_decisions(session, project.id, include_closed=False)
        if decision.status not in {"done", "closed"}
    ]
    current_update = get_weekly_update(session, project.id, current_week_start(today))
    overdue_dependencies_count = len(
        [
            item
            for item in list_dependencies_for_project(session, project.id, include_closed=False)
            if item.needed_by_date and item.needed_by_date < today and is_open_dependency_status(item.status)
        ]
    )

    confidence = confidence_score(
        material_slips=material_slips,
        overdue_critical_tasks=overdue_critical_tasks,
        overdue_actions=len(overdue_actions),
        stale_plan=stale_plan,
        overdue_dependencies=overdue_dependencies_count,
    )
    attention = attention_score(
        material_slips=material_slips,
        overdue_critical_tasks=overdue_critical_tasks,
        overdue_actions=len(overdue_actions),
        stale_plan=stale_plan,
        upcoming_milestones=upcoming_milestones,
    )
    attention += len([risk for risk in open_risks if risk.trend == "worsening"]) * 3
    attention += len([decision for decision in open_decisions if decision.due_date and decision.due_date <= today]) * 4
    if not current_update:
        attention += 6

    top_risks = sorted(open_risks, key=lambda item: (severity_rank(item.severity), item.updated_at), reverse=False)[:3]
    trend = health_trend(session, project.id, window_weeks=4, settings=settings, today=today)
    leadership_surprise = leadership_surprise_indicator(project, today=today, settings=settings)

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
        "overdue_dependencies_count": overdue_dependencies_count,
        "open_decisions_count": len(open_decisions),
        "recent_schedule_movement": recent_schedule_movement,
        "needs_pm_attention_score": attention,
        "stale_plan": stale_plan,
        "latest_finish_date": latest_finish.isoformat() if latest_finish else None,
        "latest_imported_at": snapshot.imported_at.isoformat() if snapshot else None,
        "material_slips_count": material_slips,
        "overdue_critical_tasks_count": overdue_critical_tasks,
        "top_risks": [serialize_risk(risk) for risk in top_risks],
        "budget_variance": None,
        "confidence_drivers": {
            "material_slips": material_slips,
            "overdue_critical_tasks": overdue_critical_tasks,
            "overdue_actions": len(overdue_actions),
            "overdue_dependencies": overdue_dependencies_count,
            "stale_plan": stale_plan,
        },
        "missing_weekly_update": current_update is None,
        "health_trend_direction": trend["direction"],
        "health_trend_score": trend["slope"],
        "health_trend_history": trend["history"] if include_health_history else None,
        "leadership_surprise_indicator": leadership_surprise,
    }


def portfolio_view(
    session,
    settings: Settings | None = None,
    today: Optional[date] = None,
    leadership_level: Optional[str] = None,
) -> list[dict]:
    settings = settings or get_settings()
    summaries = [project_summary(session, project, settings, today=today) for project in list_projects(session)]
    if leadership_level:
        normalized_level = leadership_level.strip().lower()
        summaries = [
            item
            for item in summaries
            if item["leadership_surprise_indicator"]["level"] == normalized_level
        ]

    ranked = sorted(
        summaries,
        key=lambda item: (
            item["leadership_surprise_indicator"]["score"],
            item["needs_pm_attention_score"],
        ),
        reverse=True,
    )
    for index, summary in enumerate(ranked, start=1):
        summary["needs_attention_rank"] = index
    return ranked

def deteriorating_projects(session, settings: Settings | None = None, today: Optional[date] = None) -> list[dict]:
    settings = settings or get_settings()
    today = today or date.today()
    results: list[dict] = []
    for project in list_projects(session):
        trend = health_trend(session, project.id, window_weeks=4, settings=settings, today=today)
        if trend["direction"] == "deteriorating" and 2 <= trend["history_points"] <= 4:
            results.append(
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "health_trend_direction": trend["direction"],
                    "health_trend_score": trend["slope"],
                    "history_points": trend["history_points"],
                }
            )
    return sorted(results, key=lambda item: item["health_trend_score"], reverse=True)


def dependencies_view(session, project_id: int | None = None, today: Optional[date] = None) -> dict:
    today = today or date.today()
    rows = (
        list_dependencies_for_project(session, project_id, include_closed=True)
        if project_id is not None
        else list_dependencies(session, include_closed=True)
    )
    return {
        "today": today.isoformat(),
        "dependencies": [serialize_dependency(item) for item in rows],
        "overdue": [serialize_dependency(item) for item in list_overdue_dependencies(session, today=today)],
    }


def project_detail(session, project: Project, settings: Settings | None = None, today: Optional[date] = None) -> dict:
    settings = settings or get_settings()
    today = today or date.today()
    summary = project_summary(session, project, settings, today=today)
    snapshot = get_latest_snapshot(session, project.id)
    actions = [serialize_action(action) for action in list_actions(session, project.id, include_closed=True)]
    risks = [serialize_risk(risk) for risk in list_risks(session, project.id, include_closed=True)[:10]]
    decisions = [serialize_decision(decision) for decision in list_decisions(session, project.id, include_closed=True)[:10]]

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
        "risks": risks,
        "decisions": decisions,
        "milestones": milestones,
        "critical_tasks": critical_tasks,
        "slipped_tasks": slipped_tasks,
    }


def project_workflow_view(
    session,
    project: Project,
    settings: Settings | None = None,
    week_start: Optional[date] = None,
) -> dict:
    settings = settings or get_settings()
    selected_week = week_start or current_week_start()
    weekly_update = get_weekly_update(session, project.id, selected_week)
    history = [serialize_weekly_update(item) for item in list_weekly_updates(session, project.id, limit=8)]
    suggestions = [
        serialize_suggestion(item)
        for item in list_suggestions(session, project_id=project.id)
        if not item.weekly_update_id or (item.weekly_update and item.weekly_update.week_start == selected_week)
    ]
    risks = [serialize_risk(item) for item in list_risks(session, project.id, include_closed=True)]
    decisions = [serialize_decision(item) for item in list_decisions(session, project.id, include_closed=True)]
    milestone_changes = build_milestone_change_summary(session, project, settings)
    return {
        "selected_week_start": selected_week.isoformat(),
        "weekly_update": serialize_weekly_update(weekly_update) if weekly_update else None,
        "weekly_update_history": history,
        "suggestions": suggestions,
        "pending_suggestions": [item for item in suggestions if item["status"] == "pending"],
        "risks": risks,
        "decisions": decisions,
        "milestone_changes": milestone_changes,
        "summary": project_summary(session, project, settings=settings),
    }


def cockpit_view(session, settings: Settings | None = None, week_start: Optional[date] = None) -> dict:
    settings = settings or get_settings()
    selected_week = week_start or current_week_start()
    selected_week_end = week_end(selected_week)
    today = date.today()
    projects = list_projects(session)

    project_rows = []
    review_queue = []
    all_due_actions = []
    overdue_actions = []
    decisions_to_force = []
    risks_watch = []
    reminders = []
    total_material_slips = 0

    for project in projects:
        summary = project_summary(session, project, settings=settings, today=today)
        weekly_update = get_weekly_update(session, project.id, selected_week)
        suggestions = [
            item
            for item in list_suggestions(session, project_id=project.id)
            if item.weekly_update_id and item.weekly_update and item.weekly_update.week_start == selected_week
        ]
        pending_suggestions = [serialize_suggestion(item) for item in suggestions if item.status == "pending"]
        review_queue.extend(pending_suggestions)

        project_actions = [action for action in list_actions(session, project.id, include_closed=False) if action.status != "done"]
        due_this_week = [
            serialize_action(action)
            for action in project_actions
            if action.due_date and selected_week <= action.due_date <= selected_week_end
        ]
        overdue = [serialize_action(action) for action in project_actions if action.due_date and action.due_date < today]

        project_decisions = [
            serialize_decision(decision)
            for decision in list_decisions(session, project.id, include_closed=False)
            if decision.status not in {"done", "closed"} and decision.due_date and decision.due_date <= selected_week_end
        ]
        project_risks = [
            serialize_risk(risk)
            for risk in list_risks(session, project.id, include_closed=False)
            if risk.status != "closed" and (risk.trend == "worsening" or risk.severity in {"high", "critical"})
        ]

        milestone_changes = build_milestone_change_summary(session, project, settings)
        total_material_slips += summary["material_slips_count"]
        summary_draft = next(
            (
                suggestion["payload"]["summary_text"]
                for suggestion in pending_suggestions
                if suggestion["suggestion_type"] == "summary"
            ),
            None,
        )
        project_reminders = [
            suggestion for suggestion in pending_suggestions if suggestion["suggestion_type"] == "reminder"
        ]
        reminders.extend(project_reminders)
        all_due_actions.extend(due_this_week)
        overdue_actions.extend(overdue)
        decisions_to_force.extend(project_decisions)
        risks_watch.extend(project_risks)

        project_rows.append(
            {
                "project_id": project.id,
                "project_name": project.name,
                "summary": summary,
                "weekly_update": serialize_weekly_update(weekly_update) if weekly_update else None,
                "milestone_changes": milestone_changes,
                "actions_due_this_week": due_this_week,
                "overdue_actions": overdue,
                "decisions_to_force": project_decisions,
                "risks_watch": project_risks,
                "summary_draft": summary_draft,
                "reminders": project_reminders,
                "pending_suggestions": pending_suggestions,
            }
        )

    updates_received = sum(1 for row in project_rows if row["weekly_update"])
    missing_updates = len(project_rows) - updates_received
    portfolio_summary = (
        f"Week of {selected_week.isoformat()}: {updates_received}/{len(project_rows)} project update(s) submitted, "
        f"{total_material_slips} material slip(s), {len(overdue_actions)} overdue action(s), "
        f"{len(decisions_to_force)} decision(s) due, {len(risks_watch)} risk(s) on watch, "
        f"{missing_updates} missing weekly update(s)."
    )
    deteriorating = deteriorating_projects(session, settings=settings, today=today)

    return {
        "week_start": selected_week.isoformat(),
        "week_end": selected_week_end.isoformat(),
        "project_rows": project_rows,
        "review_queue": sorted(review_queue, key=lambda item: (item["suggestion_type"], item["project_id"])),
        "actions_due_this_week": sorted(all_due_actions, key=lambda item: item["due_date"] or ""),
        "overdue_actions": sorted(overdue_actions, key=lambda item: item["due_date"] or ""),
        "decisions_to_force": sorted(decisions_to_force, key=lambda item: item["due_date"] or ""),
        "risks_watch": sorted(risks_watch, key=lambda item: (severity_rank(item["severity"]), item["title"])),
        "reminders": reminders,
        "portfolio_summary": portfolio_summary,
        "deteriorating_projects": deteriorating,
        "executive_summary_draft": get_latest_portfolio_summary_draft(session, selected_week, status="pending"),
        "executive_summary_final": get_latest_portfolio_summary_draft(session, selected_week, status="accepted"),
    }


def generate_portfolio_executive_summary(
    session,
    week_start: date,
    settings: Settings | None = None,
) -> dict:
    settings = settings or get_settings()
    week_data = cockpit_view(session, settings=settings, week_start=week_start)
    last_week_data = cockpit_view(session, settings=settings, week_start=week_start - timedelta(days=7))
    projects = list_projects(session)

    open_risks: list[RiskItem] = []
    open_decisions: list[DecisionItem] = []
    for project in projects:
        open_risks.extend([item for item in list_risks(session, project.id, include_closed=False) if item.status != "closed"])
        open_decisions.extend(
            [
                item
                for item in list_decisions(session, project.id, include_closed=False)
                if item.status not in {"done", "closed"}
            ]
        )

    top_risks = sorted(
        open_risks,
        key=lambda item: (severity_rank(item.severity), item.updated_at),
    )[:3]
    decision_asks = sorted(
        [item for item in open_decisions if item.due_date and item.due_date <= week_end(week_start)],
        key=lambda item: item.due_date or date.max,
    )[:5]
    next_week_watchlist = sorted(
        [item for item in open_risks if item.trend == "worsening" or item.severity in {"high", "critical"}],
        key=lambda item: (severity_rank(item.severity), item.title),
    )[:5]

    payload = {
        "overall_status": week_data["portfolio_summary"],
        "changes_since_last_week": (
            f"Updates received: {sum(1 for row in week_data['project_rows'] if row['weekly_update'])}"
            f" (prev {sum(1 for row in last_week_data['project_rows'] if row['weekly_update'])}); "
            f"material slips: {sum(row['summary']['material_slips_count'] for row in week_data['project_rows'])}"
            f" (prev {sum(row['summary']['material_slips_count'] for row in last_week_data['project_rows'])}); "
            f"overdue actions: {len(week_data['overdue_actions'])}"
            f" (prev {len(last_week_data['overdue_actions'])})."
        ),
        "top_3_risks": [
            f"{risk.project.name}: {risk.title} [{risk.severity}] ({risk.trend})"
            for risk in top_risks
        ],
        "decision_asks": [
            f"{decision.project.name}: {decision.summary} (owner: {decision.owner or 'Unassigned'}, due: {decision.due_date.isoformat() if decision.due_date else 'TBD'})"
            for decision in decision_asks
        ],
        "next_week_watchlist": [
            f"{risk.project.name}: {risk.title}"
            for risk in next_week_watchlist
        ],
    }
    return payload


def create_portfolio_summary_draft(session, week_start: date, settings: Settings | None = None) -> PortfolioSummaryDraft:
    for existing in (
        session.query(PortfolioSummaryDraft)
        .filter(PortfolioSummaryDraft.week_start == week_start, PortfolioSummaryDraft.status == "pending")
        .all()
    ):
        session.delete(existing)
    session.flush()

    payload = generate_portfolio_executive_summary(session, week_start, settings=settings)
    draft = PortfolioSummaryDraft(
        week_start=week_start,
        draft_payload=_json_dumps(payload),
        status="pending",
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


def get_portfolio_summary_draft_or_404(session, draft_id: int) -> PortfolioSummaryDraft:
    draft = session.get(PortfolioSummaryDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Portfolio summary draft not found")
    return draft


def get_latest_portfolio_summary_draft(
    session,
    week_start: date,
    status: str,
) -> Optional[dict]:
    draft = (
        session.query(PortfolioSummaryDraft)
        .filter(PortfolioSummaryDraft.week_start == week_start, PortfolioSummaryDraft.status == status)
        .order_by(PortfolioSummaryDraft.id.desc())
        .first()
    )
    return serialize_portfolio_summary_draft(draft) if draft else None


def accept_portfolio_summary_draft(
    session,
    draft: PortfolioSummaryDraft,
    final_payload: Optional[dict] = None,
) -> PortfolioSummaryDraft:
    if draft.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending drafts can be accepted")
    draft.status = "accepted"
    draft.final_payload = _json_dumps(final_payload or _json_loads(draft.draft_payload))
    draft.reviewed_at = datetime.now(UTC)
    session.commit()
    session.refresh(draft)
    return draft


def dismiss_portfolio_summary_draft(session, draft: PortfolioSummaryDraft) -> PortfolioSummaryDraft:
    if draft.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending drafts can be dismissed")
    draft.status = "dismissed"
    draft.reviewed_at = datetime.now(UTC)
    session.commit()
    session.refresh(draft)
    return draft


def attention_queue(session, settings: Settings | None = None, today: Optional[date] = None) -> list[dict]:
    settings = settings or get_settings()
    today = today or date.today()
    queue = []
    current_week = current_week_start(today)

    for summary in portfolio_view(session, settings, today=today):
        leadership_surprise = summary["leadership_surprise_indicator"]
        if leadership_surprise["level"] == "high":
            queue.append(
                {
                    "project_name": summary["project_name"],
                    "category": "Leadership Surprise Risk",
                    "detail": "; ".join(leadership_surprise["drivers"][:2]),
                    "score": leadership_surprise["score"],
                }
            )

        if summary["stale_plan"]:
            queue.append(
                {
                    "project_name": summary["project_name"],
                    "category": "Stale Plan",
                    "detail": "Latest successful import is older than 7 days or missing",
                    "score": 12,
                }
            )

        if summary["missing_weekly_update"]:
            queue.append(
                {
                    "project_name": summary["project_name"],
                    "category": "Missing Weekly Update",
                    "detail": f"No weekly update captured for {current_week.isoformat()}",
                    "score": 9,
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

        if summary["overdue_dependencies_count"]:
            queue.append(
                {
                    "project_name": summary["project_name"],
                    "category": "Blocked Cross-Project Dependencies",
                    "detail": f"{summary['overdue_dependencies_count']} dependency(ies) overdue",
                    "score": summary["overdue_dependencies_count"] * 5,
                }
            )

        if summary["open_decisions_count"]:
            project = session.get(Project, summary["project_id"])
            overdue_decisions = [
                decision
                for decision in list_decisions(session, project.id, include_closed=False)
                if decision.status not in {"done", "closed"} and decision.due_date and decision.due_date < today
            ]
            if overdue_decisions:
                queue.append(
                    {
                        "project_name": project.name,
                        "category": "Overdue Decisions",
                        "detail": f"{len(overdue_decisions)} decision(s) need forcing",
                        "score": len(overdue_decisions) * 5,
                    }
                )

            worsening_risks = [
                risk for risk in list_risks(session, project.id, include_closed=False) if risk.trend == "worsening"
            ]
            if worsening_risks:
                queue.append(
                    {
                        "project_name": project.name,
                        "category": "Worsening Risks",
                        "detail": f"{len(worsening_risks)} risk(s) marked worsening",
                        "score": len(worsening_risks) * 5,
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


def leadership_surprise_indicator(project: Project, today: date, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    snapshots = sorted(
        project.snapshots,
        key=lambda item: (item.imported_at, item.id),
        reverse=True,
    )
    latest_snapshot = snapshots[0] if snapshots else None
    recent_snapshots = snapshots[:3]
    recent_material_slip_snapshots = sum(
        1 for snapshot in recent_snapshots if any(milestone.material_slip for milestone in snapshot.milestones)
    )

    drivers: list[str] = []
    score = 0

    if recent_material_slip_snapshots >= 2:
        score += 24
        drivers.append("Repeated material milestone slips across recent snapshots")
    elif recent_material_slip_snapshots == 1:
        score += 10
        drivers.append("Recent material milestone slip")

    open_risks = [risk for risk in project.risks if risk.status != "closed"]
    high_severity_or_worsening_risks = [
        risk
        for risk in open_risks
        if risk.severity in {"high", "critical"} or risk.trend == "worsening"
    ]
    if high_severity_or_worsening_risks:
        score += min(28, 10 + len(high_severity_or_worsening_risks) * 6)
        drivers.append("High-severity or worsening risks are active")

    open_decisions = [decision for decision in project.decisions if decision.status not in {"done", "closed"}]
    overdue_decisions = [decision for decision in open_decisions if decision.due_date and decision.due_date < today]

    next_milestone = None
    if latest_snapshot:
        future_milestones = sorted(
            [milestone for milestone in latest_snapshot.milestones if milestone.finish_date and milestone.finish_date >= today],
            key=lambda milestone: milestone.finish_date,
        )
        next_milestone = future_milestones[0] if future_milestones else None

    if overdue_decisions:
        if next_milestone and (next_milestone.finish_date - today).days <= settings.upcoming_milestone_days:
            score += 20
            drivers.append("Overdue decisions are unresolved near a milestone")
        else:
            score += 8
            drivers.append("Overdue decisions remain unresolved")

    latest_import_date = latest_snapshot.imported_at.date() if latest_snapshot else None
    stale_plan = is_stale(today, latest_import_date, settings.stale_plan_days)
    current_update = next((update for update in project.weekly_updates if update.week_start == current_week_start(today)), None)
    if stale_plan and not current_update:
        score += 20
        drivers.append("Plan is stale and this week is missing a status update")
    elif stale_plan or not current_update:
        score += 8
        drivers.append("Plan freshness/update cadence needs attention")

    overdue_actions = [
        action for action in project.actions if action.status != "done" and action.due_date and action.due_date < today
    ]
    overdue_critical_tasks = 0
    material_slips_latest = 0
    if latest_snapshot:
        overdue_critical_tasks = sum(
            1
            for task in latest_snapshot.tasks
            if task.critical_flag and task.finish_date and task.finish_date < today and (task.percent_complete or 0.0) < 100.0
        )
        material_slips_latest = sum(1 for milestone in latest_snapshot.milestones if milestone.material_slip)

    confidence = confidence_score(
        material_slips=material_slips_latest,
        overdue_critical_tasks=overdue_critical_tasks,
        overdue_actions=len(overdue_actions),
        stale_plan=stale_plan,
    )
    if next_milestone and (next_milestone.finish_date - today).days <= 21 and confidence <= 75:
        score += 18
        drivers.append("Near-term milestone confidence is low")

    if score >= 60:
        level = "high"
    elif score >= 30:
        level = "medium"
    else:
        level = "low"

    return {"score": score, "level": level, "drivers": drivers[:4]}


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


def get_risk_or_404(session, risk_id: int) -> RiskItem:
    risk = get_risk(session, risk_id)
    if not risk:
        raise HTTPException(status_code=404, detail="Risk not found")
    return risk


def get_decision_or_404(session, decision_id: int) -> DecisionItem:
    decision = get_decision(session, decision_id)
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    return decision


def get_suggestion_or_404(session, suggestion_id: int) -> SuggestionItem:
    suggestion = get_suggestion(session, suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return suggestion


def get_weekly_update_or_404(session, update_id: int) -> WeeklyUpdate:
    weekly_update = get_weekly_update_by_id(session, update_id)
    if not weekly_update:
        raise HTTPException(status_code=404, detail="Weekly update not found")
    return weekly_update
