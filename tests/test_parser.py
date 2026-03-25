from __future__ import annotations

from datetime import date

from pm_dashboard.parser import _coerce_task


def test_coerce_task_uses_duration_heuristic_for_missing_milestone_flag():
    task = _coerce_task(
        {
            "name": "Single day event",
            "start_date": "2026-03-24",
            "finish_date": "2026-03-24",
            "milestone_flag": None,
        }
    )

    assert task.start_date == date(2026, 3, 24)
    assert task.finish_date == date(2026, 3, 24)
    assert task.milestone_flag is True


def test_coerce_task_honors_explicit_milestone_flag_false():
    task = _coerce_task(
        {
            "name": "Regular task",
            "start_date": "2026-03-24",
            "finish_date": "2026-03-24",
            "milestone_flag": False,
        }
    )

    assert task.milestone_flag is False
