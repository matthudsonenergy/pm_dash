from __future__ import annotations

from .models import Project


DEFAULT_PROJECTS = [
    {"key": "pyrolysis-petal-2026", "name": "Pyrolysis Petal 2026"},
    {"key": "project-2", "name": "Project 2"},
    {"key": "project-3", "name": "Project 3"},
    {"key": "project-4", "name": "Project 4"},
    {"key": "project-5", "name": "Project 5"},
    {"key": "project-6", "name": "Project 6"},
    {"key": "project-7", "name": "Project 7"},
]


def ensure_seed_projects(session) -> None:
    existing = {project.key for project in session.query(Project).all()}
    for seed in DEFAULT_PROJECTS:
        if seed["key"] in existing:
            continue
        session.add(Project(key=seed["key"], name=seed["name"]))
    session.commit()
