from __future__ import annotations

from .models import Project
from .projects import PROJECTS


def ensure_seed_projects(session) -> None:
    existing_projects = session.query(Project).order_by(Project.id).all()
    by_key = {project.key: project for project in existing_projects}

    for definition in PROJECTS:
        project = by_key.get(definition.key)
        if not project:
            for legacy_key in definition.legacy_keys:
                project = by_key.get(legacy_key)
                if project:
                    break
        if not project:
            session.add(
                Project(
                    key=definition.key,
                    name=definition.name,
                    description=definition.description,
                )
            )
            continue

        project.key = definition.key
        project.name = definition.name
        project.description = definition.description

    session.commit()
