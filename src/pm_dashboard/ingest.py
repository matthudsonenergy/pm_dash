from __future__ import annotations

import argparse
from pathlib import Path

from .config import get_settings
from .database import init_db, make_engine, make_session_factory
from .repository import get_project_by_key
from .seed import ensure_seed_projects
from .services import ensure_storage, import_schedule


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an MS Project file into the PM dashboard")
    parser.add_argument("--project", required=True, help="Project key, for example pyrolysis-petal-2026")
    parser.add_argument("--file", required=True, help="Path to a native .mpp file")
    args = parser.parse_args()

    settings = get_settings()
    ensure_storage(settings)
    engine = make_engine(settings.db_url)
    session_factory = make_session_factory(engine)
    init_db(engine)

    with session_factory() as session:
        ensure_seed_projects(session)
        project = get_project_by_key(session, args.project)
        if not project:
            raise SystemExit(f"Unknown project key: {args.project}")
        run = import_schedule(
            session,
            project,
            Path(args.file),
            source_filename=Path(args.file).name,
            settings=settings,
        )
        print(f"Import run {run.id} completed with status={run.status}")


if __name__ == "__main__":
    main()
