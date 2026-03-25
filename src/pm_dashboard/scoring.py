from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


def clamp(value: int, lower: int = 0, upper: int = 100) -> int:
    return max(lower, min(upper, value))


def working_days_between(start: Optional[date], end: Optional[date]) -> Optional[int]:
    if not start or not end:
        return None
    if end <= start:
        return 0

    current = start
    days = 0
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days += 1
    return days


def is_stale(reference_date: date, latest_imported_at: Optional[date], threshold_days: int) -> bool:
    if latest_imported_at is None:
        return True
    return (reference_date - latest_imported_at).days > threshold_days


def confidence_score(
    *,
    material_slips: int,
    overdue_critical_tasks: int,
    overdue_actions: int,
    stale_plan: bool,
) -> int:
    score = 100
    score -= material_slips * 15
    score -= overdue_critical_tasks * 10
    score -= overdue_actions * 8
    if stale_plan:
        score -= 20
    return clamp(score)


def rag_from_confidence(score: int) -> str:
    if score <= 50:
        return "Red"
    if score <= 75:
        return "Yellow"
    return "Green"


def attention_score(
    *,
    material_slips: int,
    overdue_critical_tasks: int,
    overdue_actions: int,
    stale_plan: bool,
    upcoming_milestones: int,
) -> int:
    return (
        material_slips * 10
        + overdue_critical_tasks * 6
        + overdue_actions * 4
        + upcoming_milestones * 2
        + (12 if stale_plan else 0)
    )
