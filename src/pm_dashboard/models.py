from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
    weekly_updates: Mapped[list["WeeklyUpdate"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    risks: Mapped[list["RiskItem"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    decisions: Mapped[list["DecisionItem"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    suggestions: Mapped[list["SuggestionItem"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    upstream_dependencies: Mapped[list["ProjectDependency"]] = relationship(
        back_populates="upstream_project",
        cascade="all, delete-orphan",
        foreign_keys="ProjectDependency.upstream_project_id",
    )
    downstream_dependencies: Mapped[list["ProjectDependency"]] = relationship(
        back_populates="downstream_project",
        cascade="all, delete-orphan",
        foreign_keys="ProjectDependency.downstream_project_id",
    )


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
    task_diff_viewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)

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
    resource_names: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    primary_owner: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    resource_key: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)

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


class WeeklyUpdate(Base):
    __tablename__ = "weekly_updates"
    __table_args__ = (UniqueConstraint("project_id", "week_start", name="uq_weekly_updates_project_week"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    week_start: Mapped[date] = mapped_column(Date(), index=True)
    status_summary: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    blockers: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    approvals_needed: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    follow_ups: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    confidence_note: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    meeting_notes: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    status_notes: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    needs_escalation: Mapped[bool] = mapped_column(Boolean(), default=False)
    leadership_watch: Mapped[bool] = mapped_column(Boolean(), default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, onupdate=utcnow)

    project: Mapped["Project"] = relationship(back_populates="weekly_updates")
    suggestions: Mapped[list["SuggestionItem"]] = relationship(
        back_populates="weekly_update", cascade="all, delete-orphan"
    )
    risks: Mapped[list["RiskItem"]] = relationship(back_populates="weekly_update")
    decisions: Mapped[list["DecisionItem"]] = relationship(back_populates="weekly_update")


class RiskItem(Base):
    __tablename__ = "risk_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    weekly_update_id: Mapped[Optional[int]] = mapped_column(ForeignKey("weekly_updates.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    category: Mapped[str] = mapped_column(String(60), default="risk")
    severity: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    owner: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    mitigation: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    trend: Mapped[str] = mapped_column(String(40), default="steady", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, onupdate=utcnow)

    project: Mapped["Project"] = relationship(back_populates="risks")
    weekly_update: Mapped[Optional["WeeklyUpdate"]] = relationship(back_populates="risks")


class DecisionItem(Base):
    __tablename__ = "decision_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    weekly_update_id: Mapped[Optional[int]] = mapped_column(ForeignKey("weekly_updates.id"), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(String(300))
    context: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    owner: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    impact: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, onupdate=utcnow)

    project: Mapped["Project"] = relationship(back_populates="decisions")
    weekly_update: Mapped[Optional["WeeklyUpdate"]] = relationship(back_populates="decisions")


class SuggestionItem(Base):
    __tablename__ = "suggestion_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    weekly_update_id: Mapped[Optional[int]] = mapped_column(ForeignKey("weekly_updates.id"), nullable=True, index=True)
    suggestion_type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300))
    proposed_payload: Mapped[str] = mapped_column(Text())
    rationale: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="suggestions")
    weekly_update: Mapped[Optional["WeeklyUpdate"]] = relationship(back_populates="suggestions")

class ProjectDependency(Base):
    __tablename__ = "project_dependencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    upstream_project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    downstream_project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    upstream_task_ref: Mapped[str] = mapped_column(String(200), index=True)
    downstream_task_ref: Mapped[str] = mapped_column(String(200), index=True)
    needed_by_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    owner: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="import", index=True)

    upstream_project: Mapped["Project"] = relationship(
        back_populates="upstream_dependencies", foreign_keys=[upstream_project_id]
    )
    downstream_project: Mapped["Project"] = relationship(
        back_populates="downstream_dependencies", foreign_keys=[downstream_project_id]
    )


class PortfolioSummaryDraft(Base):
    __tablename__ = "portfolio_summary_drafts"
    __table_args__ = (UniqueConstraint("week_start", "status", name="uq_portfolio_summary_drafts_week_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(Date(), index=True)
    draft_payload: Mapped[str] = mapped_column(Text())
    final_payload: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
