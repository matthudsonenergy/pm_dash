from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(db_url: str):
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    return create_engine(db_url, connect_args=connect_args)


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)
    _reconcile_sqlite_schema(engine)


def _reconcile_sqlite_schema(engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    column_specs = {
        "projects": {
            "description": "TEXT",
        },
        "project_files": {
            "content_type": "VARCHAR(100)",
            "checksum": "VARCHAR(64)",
            "uploaded_at": "DATETIME",
            "updated_at": "DATETIME",
        },
        "tasks": {
            "resource_names": "TEXT",
            "primary_owner": "VARCHAR(150)",
            "resource_key": "VARCHAR(120)",
        },
        "schedule_snapshots": {
            "task_diff_viewed_at": "DATETIME",
        },
    }
    index_specs = {
        "project_files": {
            "ix_project_files_project_id": "CREATE INDEX ix_project_files_project_id ON project_files (project_id)",
        },
        "tasks": {
            "ix_tasks_resource_key": "CREATE INDEX ix_tasks_resource_key ON tasks (resource_key)",
        },
    }

    with engine.begin() as connection:
        for table_name, columns in column_specs.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_type in columns.items():
                if column_name in existing_columns:
                    continue
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))

        for table_name, indexes in index_specs.items():
            if table_name not in existing_tables:
                continue
            existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
            for index_name, ddl in indexes.items():
                if index_name in existing_indexes:
                    continue
                connection.execute(text(ddl))


@contextmanager
def session_scope(session_factory) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
