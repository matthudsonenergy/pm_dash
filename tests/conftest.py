from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from pm_dashboard.config import Settings
from pm_dashboard.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        repo_root=Path("/home/matthew_hudson/pm_dash"),
        data_dir=data_dir,
        uploads_dir=data_dir / "uploads",
        db_url=f"sqlite:///{data_dir / 'test.db'}",
        parser_project_dir=Path("/home/matthew_hudson/pm_dash/tools/mpp-parser"),
        parser_jar=Path("/home/matthew_hudson/pm_dash/tools/mpp-parser/target/mpp-parser-1.0.0.jar"),
        sample_mpp=Path("/home/matthew_hudson/pm_dash/2026 Pyrolysis Petal - 24 Mar 2026.mpp"),
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def auth_settings(settings: Settings) -> Settings:
    return replace(settings, auth_username="pm", auth_password="secret")
