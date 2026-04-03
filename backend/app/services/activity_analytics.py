"""
Activity Analytics Service — native CTL/ATL/TSB, Bestzeiten, Ausrüstung.

Alle Daten kommen aus unserer eigenen Datenbank (TrainingPlan, HealthMetric,
ActivityDetail, GearItem, PersonalRecord) — kein externer API-Aufruf nötig.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import FitnessSnapshot, PersonalRecord, GearItem
from app.models.training import TrainingPlan


# ---------------------------------------------------------------------------
# Bekannte PR-Distanzen (Meter)
# ---------------------------------------------------------------------------
PR_DISTANCES: dict[str, float] = {
    "400m": 400,
    "1km": 1000,
    "1mi": 1609.34,
    "5km": 5000,
    "10km": 10000,
    "15km": 15000,
    "HM": 21097.5,
    "Marathon": 42195,
}


# ---------------------------------------------------------------------------
# CTL / ATL / TSB helper
# ---------------------------------------------------------------------------
def _estimate_tss(duration_min: float, intensity_zone: int) -> float:
    """Einfacher TSS-Schätzer ohne Powermeter.

    Formel: (Dauer_h * IF^2) * 100
    Intensity Factor (IF) wird aus der Trainingszone geschätzt:
      Zone 1 → IF ~0.60, Zone 2 → 0.68, Zone 3 → 0.78, Zone 4 → 0.88, Zone 5 → 0.98
    """
    zone_if = {1: 0.60, 2: 0.68, 3: 0.78, 4: 0.88, 5: 0.98}
    if_val = zone_if.get(max(1, min(5, intensity_zone)), 0.70)
    duration_h = duration_min / 60.0
    return round(duration_h * if_val ** 2 * 100, 2)


async def calculate_fitness_freshness(
    user_id: uuid.UUID,
    db: AsyncSession,
    days: int = 90,
) -> list[dict[str, Any]]:
    """Berechnet CTL/ATL/TSB für die letzten `days` Tage aus abgeschlossenen Trainings.

    CTL (Chronic Training Load) ~ 42-Tage exponentieller Durchschnitt des TSS
    ATL (Acute Training Load) ~ 7-Tage exponentieller Durchschnitt des TSS
    TSB (Form) = CTL - ATL
    """
    today = date.today()
    start = today - timedelta(days=days + 42)  # extra 42 Tage für CTL-Anlauf

    # Abgeschlossene Trainingseinheiten laden
    result = await db.execute(
        select(
            TrainingPlan.date,
            TrainingPlan.duration_min,
            TrainingPlan.intensity_zone,
        ).where(
            TrainingPlan.user_id == user_id,
            TrainingPlan.status == "completed",
            TrainingPlan.date >= start,
        )
    )
    rows = result.all()

    # TSS pro Tag aggregieren
    tss_by_day: dict[str, float] = {}
    for row in rows:
        day_str = str(row.date)[:10]
        duration = float(row.duration_min or 0)
        zone = int(row.intensity_zone or 2)
        tss_by_day[day_str] = tss_by_day.get(day_str, 0) + _estimate_tss(duration, zone)

    # CTL/ATL über Datumsreihe iterieren
    ctl = 0.0
    atl = 0.0
    ctl_k = 2 / (42 + 1)
    atl_k = 2 / (7 + 1)

    snapshots: list[dict[str, Any]] = []
    current = start
    while current <= today:
        day_str = current.isoformat()
        tss = tss_by_day.get(day_str, 0.0)
        ctl = tss * ctl_k + ctl * (1 - ctl_k)
        atl = tss * atl_k + atl * (1 - atl_k)
        tsb = ctl - atl
        if current >= (today - timedelta(days=days)):
            snapshots.append({
                "date": day_str,
                "ctl": round(ctl, 1),
                "atl": round(atl, 1),
                "tsb": round(tsb, 1),
                "tss": round(tss, 1),
            })
        current += timedelta(days=1)

    return snapshots


async def save_fitness_snapshots(
    user_id: uuid.UUID,
    db: AsyncSession,
    days: int = 90,
) -> list[FitnessSnapshot]:
    """Speichert berechnete CTL/ATL/TSB-Snapshots in der DB (upsert nach Datum)."""
    snapshots_data = await calculate_fitness_freshness(user_id, db, days)

    # Bestehende Snapshots für den Zeitraum laden
    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    existing_result = await db.execute(
        select(FitnessSnapshot).where(
            FitnessSnapshot.user_id == user_id,
            FitnessSnapshot.snapshot_date >= start,
        )
    )
    existing: dict[str, FitnessSnapshot] = {
        s.snapshot_date: s for s in existing_result.scalars().all()
    }

    saved: list[FitnessSnapshot] = []
    now = datetime.now(timezone.utc)
    for snap in snapshots_data:
        if snap["date"] in existing:
            obj = existing[snap["date"]]
            obj.ctl = snap["ctl"]
            obj.atl = snap["atl"]
            obj.tsb = snap["tsb"]
            obj.tss = snap["tss"]
            obj.calculated_at = now
        else:
            obj = FitnessSnapshot(
                user_id=user_id,
                snapshot_date=snap["date"],
                ctl=snap["ctl"],
                atl=snap["atl"],
                tsb=snap["tsb"],
                tss=snap["tss"],
                calculated_at=now,
            )
            db.add(obj)
        saved.append(obj)

    await db.commit()
    return saved


async def compute_personal_records_from_activity_details(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Leitet Bestzeiten aus ActivityDetail-Einträgen ab (Garmin/Polar/Whoop-Sync)."""
    from app.models.analytics import ActivityDetail

    result = await db.execute(
        select(
            ActivityDetail.activity_date,
            ActivityDetail.elapsed_time_s,
            ActivityDetail.distance_m,
        ).where(
            ActivityDetail.user_id == user_id,
            ActivityDetail.distance_m.isnot(None),
            ActivityDetail.elapsed_time_s.isnot(None),
        )
    )
    rows = result.all()

    best: dict[str, tuple[int, str]] = {}  # label -> (elapsed_s, date)
    for row in rows:
        dist_m = float(row.distance_m or 0)
        dur_s = int(row.elapsed_time_s or 0)
        if dist_m <= 0 or dur_s <= 0:
            continue
        pace = dur_s / dist_m  # s/m
        for label, pr_dist in PR_DISTANCES.items():
            if dist_m >= pr_dist * 0.95:  # mind. 95 % der Distanz absolviert
                est_s = int(pace * pr_dist)
                if label not in best or est_s < best[label][0]:
                    best[label] = (est_s, str(row.activity_date)[:10])

    return [
        {
            "distance_label": label,
            "elapsed_time_s": elapsed_s,
            "achieved_date": achieved_date,
            "source": "watch_sync",
        }
        for label, (elapsed_s, achieved_date) in best.items()
    ]
