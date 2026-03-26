from __future__ import annotations

import argparse
from pathlib import Path

from .config import get_settings
from .database import init_db, make_engine, make_session_factory
from .repository import get_project_by_key
from .projects import discover_repo_mpp_files
from .seed import ensure_seed_projects
from .services import ensure_storage, import_schedule, infer_project_from_inputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an MS Project file into the PM dashboard")
    parser.add_argument("--project", help="Project key, for example p2c")
    parser.add_argument("--file", help="Path to a native .mpp file")
    parser.add_argument(
        "--all-repo-mpp",
        action="store_true",
        help="Import all .mpp files found in the repository root using filename-based project matching",
    )
    args = parser.parse_args()

    settings = get_settings()
    ensure_storage(settings)
    engine = make_engine(settings.db_url)
    session_factory = make_session_factory(engine)
    init_db(engine)

    with session_factory() as session:
        ensure_seed_projects(session)

        if args.all_repo_mpp:
            imported = 0
            for file_path in discover_repo_mpp_files(settings.repo_root):
                inferred_key = infer_project_from_inputs(file_path.name, file_path.stem)
                if not inferred_key:
                    print(f"Skipping {file_path.name}: no project match")
                    continue
                project = get_project_by_key(session, inferred_key)
                if not project:
                    print(f"Skipping {file_path.name}: unknown project key {inferred_key}")
                    continue
                run = import_schedule(
                    session,
                    project,
                    file_path,
                    source_filename=file_path.name,
                    settings=settings,
                )
                imported += 1
                print(f"Imported {file_path.name} into {project.key} with status={run.status}")
            if imported == 0:
                raise SystemExit("No repository .mpp files matched a configured project")
            return

        if not args.file:
            raise SystemExit("--file is required unless --all-repo-mpp is used")

        project_key = args.project or infer_project_from_inputs(Path(args.file).name, Path(args.file).stem)
        if not project_key:
            raise SystemExit("Could not infer project key from file name. Pass --project explicitly.")

        project = get_project_by_key(session, project_key)
        if not project:
            raise SystemExit(f"Unknown project key: {project_key}")
        run = import_schedule(session, project, Path(args.file), source_filename=Path(args.file).name, settings=settings)
        print(f"Import run {run.id} completed with status={run.status} for project={project.key}")


if __name__ == "__main__":
    main()
