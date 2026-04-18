import uuid
from datetime import date, datetime, timezone
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String,
    Integer,
    Float,
    DateTime,
    Date,
    JSON,
    Text,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from app.core.database import Base


class HealthMetric(Base):
    __tablename__ = "health_metrics"
    __table_args__ = (
        Index("ix_health_metrics_user_recorded", "user_id", "recorded_at"),
        Index("ix_health_metrics_user_source", "user_id", "source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    hrv: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_stages: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stress_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    spo2: Mapped[float | None] = mapped_column(Float, nullable=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vo2_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DailyWellbeing(Base):
    __tablename__ = "daily_wellbeing"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_daily_wellbeing_user_date"),
        Index("ix_daily_wellbeing_user_date", "user_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    fatigue_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mood_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pain_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecoveryScore(Base):
    __tablename__ = "recovery_scores"
    __table_args__ = (Index("ix_recovery_scores_user_date", "user_id", "date"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
