"""
Native Analytics Modelle — berechnet aus eigenen Uhren-Daten (Garmin, Polar, WHOOP etc.)

- ActivityDetail: Erweiterte Aktivitätsdaten (Laps, Power, Laufdynamik)
- GearItem: Schuhe und Fahrräder mit Kilometerstand (manuelle Pflege)
- FitnessSnapshot: CTL / ATL / TSB Zeitreihe
- PersonalRecord: Persönliche Bestzeiten
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Text,
    ForeignKey, Index, JSON,
)
from app.core.database import Base


class ActivityDetail(Base):
    """Erweiterte Aktivitätsdaten aus Garmin/Polar/WHOOP — Laps, Power, Laufdynamik."""
    __tablename__ = "activity_details"
    __table_args__ = (
        Index("ix_activity_details_user_date", "user_id", "activity_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String, nullable=False)          # "garmin" | "polar" | "whoop" | "manual"
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)  # Provider-eigene Activity-ID

    # Basis
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    sport_type: Mapped[str | None] = mapped_column(String, nullable=True)
    activity_date: Mapped[str | None] = mapped_column(String, nullable=True)  # "2026-04-03"
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elapsed_time_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moving_time_s: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Power (Radfahren / Laufen mit Leistungsmesser)
    average_watts: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_watts: Mapped[float | None] = mapped_column(Float, nullable=True)
    kilojoules: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Laufdynamik
    average_cadence: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_stride_length: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Herzfrequenz
    average_heartrate: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_heartrate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Gear-Referenz (z.B. Schuh-ID aus GearItem)
    gear_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gear_items.id", ondelete="SET NULL"), nullable=True
    )

    # Laps als JSON
    laps: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class GearItem(Base):
    """Schuhe und Fahrräder — manuell gepflegt, km werden aus Aktivitäten summiert."""
    __tablename__ = "gear_items"
    __table_args__ = (
        Index("ix_gear_items_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    gear_type: Mapped[str] = mapped_column(String, nullable=False)   # "shoe" | "bike"
    name: Mapped[str] = mapped_column(String, nullable=False)
    brand: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    purchase_date: Mapped[str | None] = mapped_column(String, nullable=True)  # "2025-09-01"
    initial_km: Mapped[float] = mapped_column(Float, default=0.0)            # km vor Nutzung in App
    retired: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class FitnessSnapshot(Base):
    """
    Täglicher CTL / ATL / TSB Snapshot — berechnet aus completed TrainingPlan Einträgen.
    CTL (Chronic Training Load) = Fitness
    ATL (Acute Training Load)   = Fatigue
    TSB (Training Stress Balance) = Form = CTL - ATL
    """
    __tablename__ = "fitness_snapshots"
    __table_args__ = (
        Index("ix_fitness_snapshots_user_date", "user_id", "snapshot_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    snapshot_date: Mapped[str] = mapped_column(String, nullable=False)  # "2026-04-03"
    ctl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    atl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tsb: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tss: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)   # Tages-TSS
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class PersonalRecord(Base):
    """Persönliche Bestzeiten — automatisch aus completed TrainingPlan Einträgen berechnet."""
    __tablename__ = "personal_records"
    __table_args__ = (
        Index("ix_personal_records_user_distance", "user_id", "distance_label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    distance_label: Mapped[str] = mapped_column(String, nullable=False)  # "5km", "10km" etc.
    elapsed_time_s: Mapped[int] = mapped_column(Integer, nullable=False)
    achieved_date: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="manual")           # "garmin" | "manual"
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
