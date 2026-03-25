from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, onupdate=utcnow)

    snapshots: Mapped[list["ScheduleSnapshot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    actions: Mapped[list["ActionItem"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    import_runs: Mapped[list["ImportRun"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ScheduleSnapshot(Base):
    __tablename__ = "schedule_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, index=True)
    source_filename: Mapped[str] = mapped_column(String(255))
    source_path: Mapped[str] = mapped_column(String(500))
    source_checksum: Mapped[str] = mapped_column(String(64))
    current_finish_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    baseline_finish_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    task_count: Mapped[int] = mapped_column(Integer(), default=0)
    milestone_count: Mapped[int] = mapped_column(Integer(), default=0)
    critical_task_count: Mapped[int] = mapped_column(Integer(), default=0)

    project: Mapped["Project"] = relationship(back_populates="snapshots")
    tasks: Mapped[list["Task"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")
    milestones: Mapped[list["Milestone"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")
    import_runs: Mapped[list["ImportRun"]] = relationship(back_populates="snapshot")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("schedule_snapshots.id"), index=True)
    task_unique_id: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True, index=True)
    outline_level: Mapped[int] = mapped_column(Integer(), default=1)
    outline_path: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    start_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    finish_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    baseline_start_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    baseline_finish_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    percent_complete: Mapped[float] = mapped_column(Float(), default=0.0)
    critical_flag: Mapped[bool] = mapped_column(Boolean(), default=False)
    milestone_flag: Mapped[bool] = mapped_column(Boolean(), default=False)
    predecessor_refs: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)

    snapshot: Mapped["ScheduleSnapshot"] = relationship(back_populates="tasks")


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("schedule_snapshots.id"), index=True)
    source_task_unique_id: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    finish_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    baseline_start_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    baseline_finish_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    percent_complete: Mapped[float] = mapped_column(Float(), default=0.0)
    critical_flag: Mapped[bool] = mapped_column(Boolean(), default=False)
    predecessor_refs: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    variance_from_previous_days: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    variance_from_baseline_days: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    material_slip: Mapped[bool] = mapped_column(Boolean(), default=False)

    snapshot: Mapped["ScheduleSnapshot"] = relationship(back_populates="milestones")


class ActionItem(Base):
    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    owner: Mapped[str] = mapped_column(String(150))
    due_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="actions")


class ImportRun(Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    snapshot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("schedule_snapshots.id"), nullable=True, index=True)
    source_filename: Mapped[str] = mapped_column(String(255))
    source_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(40), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="import_runs")
    snapshot: Mapped[Optional["ScheduleSnapshot"]] = relationship(back_populates="import_runs")
