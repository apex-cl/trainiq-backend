import uuid
from datetime import date, datetime, timezone
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String,
    Integer,
    Date,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from app.core.database import Base


class UserGoal(Base):
    __tablename__ = "user_goals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    sport: Mapped[str] = mapped_column(String, nullable=False)
    goal_description: Mapped[str] = mapped_column(Text, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    weekly_hours: Mapped[int] = mapped_column(Integer, default=5)
    fitness_level: Mapped[str] = mapped_column(String, default="intermediate")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class TrainingPlan(Base):
    __tablename__ = "training_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_training_plans_user_date"),
        Index("ix_training_plans_user_date", "user_id", "date"),
        Index("ix_training_plans_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    sport: Mapped[str] = mapped_column(String, nullable=False)
    workout_type: Mapped[str] = mapped_column(String, nullable=False)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    intensity_zone: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_hr_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_hr_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    coach_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="planned")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
