from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent


def _discover_repo_root() -> Path:
    env_root = os.getenv("PM_DASH_REPO_ROOT")
    if env_root:
        return Path(env_root).resolve()

    search_roots = [Path.cwd().resolve(), PACKAGE_ROOT.resolve()]
    markers = ("pyproject.toml", ".git", "README.md")

    for start in search_roots:
        for candidate in [start, *start.parents]:
            if any((candidate / marker).exists() for marker in markers):
                if (candidate / "src" / "pm_dashboard").exists() or (candidate / "tools" / "mpp-parser").exists():
                    return candidate

    return Path.cwd().resolve()


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    data_dir: Path
    uploads_dir: Path
    db_url: str
    parser_project_dir: Path
    parser_jar: Path
    sample_mpp: Path
    stale_plan_days: int = 7
    upcoming_milestone_days: int = 30
    slip_from_previous_days: int = 3
    slip_from_baseline_days: int = 5


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    repo_root = _discover_repo_root()
    data_dir = Path(os.getenv("PM_DASH_DATA_DIR", repo_root / "data"))
    uploads_dir = data_dir / "uploads"
    db_path = Path(os.getenv("PM_DASH_DB_PATH", data_dir / "pm_dashboard.db"))

    return Settings(
        repo_root=repo_root,
        data_dir=data_dir,
        uploads_dir=uploads_dir,
        db_url=os.getenv("PM_DASH_DB_URL", f"sqlite:///{db_path}"),
        parser_project_dir=repo_root / "tools" / "mpp-parser",
        parser_jar=repo_root / "tools" / "mpp-parser" / "target" / "mpp-parser-1.0.0.jar",
        sample_mpp=repo_root / "2026 Pyrolysis Petal - 24 Mar 2026.mpp",
    )
