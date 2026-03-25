from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]


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
    data_dir = Path(os.getenv("PM_DASH_DATA_DIR", REPO_ROOT / "data"))
    uploads_dir = data_dir / "uploads"
    db_path = Path(os.getenv("PM_DASH_DB_PATH", data_dir / "pm_dashboard.db"))

    return Settings(
        repo_root=REPO_ROOT,
        data_dir=data_dir,
        uploads_dir=uploads_dir,
        db_url=os.getenv("PM_DASH_DB_URL", f"sqlite:///{db_path}"),
        parser_project_dir=REPO_ROOT / "tools" / "mpp-parser",
        parser_jar=REPO_ROOT / "tools" / "mpp-parser" / "target" / "mpp-parser-1.0.0.jar",
        sample_mpp=REPO_ROOT / "2026 Pyrolysis Petal - 24 Mar 2026.mpp",
    )
