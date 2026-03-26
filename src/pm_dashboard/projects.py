from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ProjectDefinition:
    key: str
    name: str
    description: str
    aliases: tuple[str, ...] = ()
    repo_files: tuple[str, ...] = ()
    legacy_keys: tuple[str, ...] = ()


PROJECTS: tuple[ProjectDefinition, ...] = (
    ProjectDefinition(
        key="p2c",
        name="P2C",
        description="2026 Pyrolysis Petal",
        aliases=("2026 pyrolysis petal", "pyrolysis petal 2026", "pyrolysis-petal-2026", "p2c"),
        repo_files=("2026 Pyrolysis Petal - 24 Mar 2026.mpp",),
        legacy_keys=("pyrolysis-petal-2026",),
    ),
    ProjectDefinition(
        key="atlas",
        name="Atlas",
        description="Atlas_phase1",
        aliases=("atlas_phase1", "atlas phase1", "atlas phase 1", "atlas"),
        repo_files=("Atlas_phase1_100h_13Mar-MH.mpp",),
        legacy_keys=("project-2",),
    ),
    ProjectDefinition(
        key="mpm",
        name="MPM",
        description="MPMProject324",
        aliases=("mpmproject324", "mpm project 324", "mpm"),
        repo_files=("MPMProject324.mpp",),
        legacy_keys=("project-3",),
    ),
    ProjectDefinition(
        key="iprd",
        name="IPRD",
        description="IPRD",
        aliases=("iprd",),
        legacy_keys=("project-4",),
    ),
    ProjectDefinition(
        key="propane-pyrolysis",
        name="Propane Pyrolysis",
        description="Propane Pyrolysis",
        aliases=("propane pyrolysis", "propanepyrolysis"),
        legacy_keys=("project-5",),
    ),
    ProjectDefinition(
        key="x3",
        name="X3",
        description="X3",
        aliases=("x3",),
        legacy_keys=("project-6",),
    ),
    ProjectDefinition(
        key="venture-funding",
        name="Venture Funding",
        description="Venture Funding",
        aliases=("venture funding", "venturefunding"),
        legacy_keys=("project-7",),
    ),
)


def normalize_project_token(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def project_definition_by_key(key: str) -> Optional[ProjectDefinition]:
    for definition in PROJECTS:
        if definition.key == key:
            return definition
    return None


def project_aliases(definition: ProjectDefinition) -> set[str]:
    aliases = {
        normalize_project_token(definition.key),
        normalize_project_token(definition.name),
        normalize_project_token(definition.description),
    }
    aliases.update(normalize_project_token(alias) for alias in definition.aliases)
    aliases.update(normalize_project_token(alias) for alias in definition.legacy_keys)
    aliases.update(normalize_project_token(Path(filename).stem) for filename in definition.repo_files)
    return {alias for alias in aliases if alias}


def infer_project_definition(*values: Optional[str]) -> Optional[ProjectDefinition]:
    normalized_values = [normalize_project_token(value) for value in values if value and normalize_project_token(value)]
    if not normalized_values:
        return None

    for candidate in normalized_values:
        for definition in PROJECTS:
            aliases = project_aliases(definition)
            if candidate in aliases:
                return definition

    for candidate in normalized_values:
        for definition in PROJECTS:
            aliases = project_aliases(definition)
            if any(alias and alias in candidate for alias in aliases):
                return definition

    return None


def discover_repo_mpp_files(repo_root: Path) -> list[Path]:
    return sorted(repo_root.glob("*.mpp"))


def repo_file_project_rows(repo_root: Path) -> list[dict]:
    rows: list[dict] = []
    for file_path in discover_repo_mpp_files(repo_root):
        definition = infer_project_definition(file_path.name, file_path.stem)
        rows.append(
            {
                "path": file_path,
                "filename": file_path.name,
                "project_key": definition.key if definition else None,
                "project_name": definition.name if definition else None,
            }
        )
    return rows
