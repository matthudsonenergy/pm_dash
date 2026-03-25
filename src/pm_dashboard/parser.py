from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from .config import Settings, get_settings


class ParserError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedTask:
    unique_id: Optional[int]
    outline_level: int
    outline_path: Optional[str]
    name: str
    start_date: Optional[date]
    finish_date: Optional[date]
    baseline_start_date: Optional[date]
    baseline_finish_date: Optional[date]
    percent_complete: float
    critical_flag: bool
    milestone_flag: bool
    predecessor_refs: Optional[str]
    notes: Optional[str]


@dataclass(frozen=True)
class ParsedProject:
    title: str
    current_finish_date: Optional[date]
    baseline_finish_date: Optional[date]
    tasks: list[ParsedTask]


def _parse_date(raw: Optional[str]) -> Optional[date]:
    return date.fromisoformat(raw) if raw else None


def _coerce_milestone_flag(item: dict, start_date: Optional[date], finish_date: Optional[date]) -> bool:
    if item.get("milestone_flag") is not None:
        return bool(item.get("milestone_flag"))
    return bool(start_date and finish_date and start_date == finish_date)


def _coerce_task(item: dict) -> ParsedTask:
    start_date = _parse_date(item.get("start_date"))
    finish_date = _parse_date(item.get("finish_date"))

    return ParsedTask(
        unique_id=item.get("unique_id"),
        outline_level=item.get("outline_level") or 1,
        outline_path=item.get("outline_path"),
        name=item["name"],
        start_date=start_date,
        finish_date=finish_date,
        baseline_start_date=_parse_date(item.get("baseline_start_date")),
        baseline_finish_date=_parse_date(item.get("baseline_finish_date")),
        percent_complete=float(item.get("percent_complete") or 0.0),
        critical_flag=bool(item.get("critical_flag")),
        milestone_flag=_coerce_milestone_flag(item, start_date=start_date, finish_date=finish_date),
        predecessor_refs=item.get("predecessor_refs"),
        notes=item.get("notes"),
    )


def parse_mpp_file(file_path: Path, settings: Settings | None = None) -> ParsedProject:
    settings = settings or get_settings()
    if not settings.parser_jar.exists():
        raise ParserError(
            f"Parser jar not found at {settings.parser_jar}. Build it with: "
            f"cd {settings.parser_project_dir} && mvn -q package"
        )

    command = ["java", "-jar", str(settings.parser_jar), str(file_path)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "Unknown parser failure"
        raise ParserError(message)

    stdout = result.stdout.strip()
    json_payload = stdout
    if stdout and not stdout.lstrip().startswith("{"):
        candidates = [line for line in stdout.splitlines() if line.lstrip().startswith("{")]
        if candidates:
            json_payload = candidates[-1]

    try:
        payload = json.loads(json_payload)
    except json.JSONDecodeError as exc:
        raise ParserError(f"Parser returned invalid JSON: {exc}") from exc

    return ParsedProject(
        title=payload.get("title") or file_path.stem,
        current_finish_date=_parse_date(payload.get("current_finish_date")),
        baseline_finish_date=_parse_date(payload.get("baseline_finish_date")),
        tasks=[_coerce_task(item) for item in payload.get("tasks", []) if item.get("name")],
    )
