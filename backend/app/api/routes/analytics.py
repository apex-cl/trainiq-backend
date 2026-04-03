"""
Analytics API — Native Fitness, Bestzeiten, Ausrüstung.

Alle Daten aus unserer eigenen DB (kein Strava-API-Schlüssel nötig).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models.analytics import FitnessSnapshot, GearItem, PersonalRecord
from app.models.user import User
from app.services.activity_analytics import (
    PR_DISTANCES,
    compute_personal_records_from_activity_details,
    save_fitness_snapshots,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class GearCreate(BaseModel):
    gear_type: str          # "shoes" | "bike" | "wetsuit" | other
    name: str
    brand: str | None = None
    model: str | None = None
    purchase_date: str | None = None
    initial_km: float = 0.0
    notes: str | None = None


class GearUpdate(BaseModel):
    name: str | None = None
    brand: str | None = None
    model: str | None = None
    purchase_date: str | None = None
    initial_km: float | None = None
    retired: bool | None = None
    notes: str | None = None


class PRManualUpsert(BaseModel):
    elapsed_time_s: int
    achieved_date: str | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Fitness & Freshness (CTL / ATL / TSB)
# ---------------------------------------------------------------------------
@router.get("/fitness")
async def get_fitness(
    days: int = Query(90, ge=7, le=365),
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CTL/ATL/TSB aus eigenen Trainingsdaten berechnen.

    Mit `?refresh=true` wird neu berechnet und in der DB gespeichert.
    Sonst werden gecachte Snapshots aus der DB zurückgegeben (oder frisch berechnet
    wenn noch keine vorhanden sind).
    """
    user_id = uuid.UUID(str(current_user.id))

    if refresh:
        await save_fitness_snapshots(user_id, db, days)

    result = await db.execute(
        select(FitnessSnapshot)
        .where(FitnessSnapshot.user_id == user_id)
        .order_by(FitnessSnapshot.snapshot_date.desc())
        .limit(days)
    )
    snapshots = result.scalars().all()

    if not snapshots:
        # Erste Anfrage — berechnen und speichern
        await save_fitness_snapshots(user_id, db, days)
        result = await db.execute(
            select(FitnessSnapshot)
            .where(FitnessSnapshot.user_id == user_id)
            .order_by(FitnessSnapshot.snapshot_date.asc())
            .limit(days)
        )
        snapshots = result.scalars().all()
    else:
        snapshots = sorted(snapshots, key=lambda s: s.snapshot_date)

    today_snap = snapshots[-1] if snapshots else None
    return {
        "current": {
            "ctl": today_snap.ctl if today_snap else 0,
            "atl": today_snap.atl if today_snap else 0,
            "tsb": today_snap.tsb if today_snap else 0,
        },
        "history": [
            {
                "date": s.snapshot_date,
                "ctl": s.ctl,
                "atl": s.atl,
                "tsb": s.tsb,
                "tss": s.tss,
            }
            for s in snapshots
        ],
        "calculated_at": today_snap.calculated_at.isoformat() if today_snap else None,
    }


# ---------------------------------------------------------------------------
# Personal Records (Bestzeiten)
# ---------------------------------------------------------------------------
@router.get("/personal-records")
async def get_personal_records(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Alle gespeicherten Bestzeiten des Users."""
    user_id = uuid.UUID(str(current_user.id))
    result = await db.execute(
        select(PersonalRecord)
        .where(PersonalRecord.user_id == user_id)
        .order_by(PersonalRecord.distance_label)
    )
    prs = result.scalars().all()
    return [
        {
            "id": str(pr.id),
            "distance_label": pr.distance_label,
            "elapsed_time_s": pr.elapsed_time_s,
            "achieved_date": pr.achieved_date,
            "source": pr.source,
            "notes": pr.notes,
        }
        for pr in prs
    ]


@router.post("/personal-records/sync-from-watches")
async def sync_prs_from_watches(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """PRs aus synchronisierten Watch-Aktivitäten ableiten und speichern."""
    user_id = uuid.UUID(str(current_user.id))
    derived = await compute_personal_records_from_activity_details(user_id, db)

    # Bestehende PRs laden
    result = await db.execute(
        select(PersonalRecord).where(PersonalRecord.user_id == user_id)
    )
    existing: dict[str, PersonalRecord] = {
        pr.distance_label: pr for pr in result.scalars().all()
    }

    updated = 0
    now = datetime.now(timezone.utc)
    for item in derived:
        label = item["distance_label"]
        existing_pr = existing.get(label)
        # Nur eintragen wenn besser als vorheriger Eintrag (oder noch kein Eintrag)
        if existing_pr is None or item["elapsed_time_s"] < existing_pr.elapsed_time_s:
            if existing_pr:
                existing_pr.elapsed_time_s = item["elapsed_time_s"]
                existing_pr.achieved_date = item["achieved_date"]
                existing_pr.source = item["source"]
                existing_pr.updated_at = now
            else:
                pr_obj = PersonalRecord(
                    user_id=user_id,
                    distance_label=label,
                    elapsed_time_s=item["elapsed_time_s"],
                    achieved_date=item["achieved_date"],
                    source=item["source"],
                    updated_at=now,
                )
                db.add(pr_obj)
            updated += 1

    await db.commit()
    return {"updated": updated, "total_derived": len(derived)}


@router.put("/personal-records/{distance_label}")
async def upsert_personal_record(
    distance_label: str,
    body: PRManualUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Setzt oder aktualisiert eine Bestzeit manuell."""
    if distance_label not in PR_DISTANCES:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekannte Distanz. Gültig: {', '.join(PR_DISTANCES)}",
        )
    user_id = uuid.UUID(str(current_user.id))
    result = await db.execute(
        select(PersonalRecord).where(
            PersonalRecord.user_id == user_id,
            PersonalRecord.distance_label == distance_label,
        )
    )
    pr = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if pr:
        pr.elapsed_time_s = body.elapsed_time_s
        pr.achieved_date = body.achieved_date
        pr.source = "manual"
        pr.notes = body.notes
        pr.updated_at = now
    else:
        pr = PersonalRecord(
            user_id=user_id,
            distance_label=distance_label,
            elapsed_time_s=body.elapsed_time_s,
            achieved_date=body.achieved_date,
            source="manual",
            notes=body.notes,
            updated_at=now,
        )
        db.add(pr)
    await db.commit()
    return {
        "id": str(pr.id),
        "distance_label": pr.distance_label,
        "elapsed_time_s": pr.elapsed_time_s,
        "achieved_date": pr.achieved_date,
        "source": pr.source,
    }


@router.delete("/personal-records/{distance_label}", status_code=204, response_model=None)
async def delete_personal_record(
    distance_label: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    user_id = uuid.UUID(str(current_user.id))
    result = await db.execute(
        select(PersonalRecord).where(
            PersonalRecord.user_id == user_id,
            PersonalRecord.distance_label == distance_label,
        )
    )
    pr = result.scalar_one_or_none()
    if pr:
        await db.delete(pr)
        await db.commit()


# ---------------------------------------------------------------------------
# Gear (Ausrüstung)
# ---------------------------------------------------------------------------
@router.get("/gear")
async def get_gear(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    user_id = uuid.UUID(str(current_user.id))
    result = await db.execute(
        select(GearItem)
        .where(GearItem.user_id == user_id)
        .order_by(GearItem.created_at.desc())
    )
    items = result.scalars().all()
    return [
        {
            "id": str(g.id),
            "gear_type": g.gear_type,
            "name": g.name,
            "brand": g.brand,
            "model": g.model,
            "purchase_date": g.purchase_date,
            "initial_km": g.initial_km,
            "retired": g.retired,
            "notes": g.notes,
            "created_at": g.created_at.isoformat(),
        }
        for g in items
    ]


@router.post("/gear", status_code=201)
async def create_gear(
    body: GearCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = uuid.UUID(str(current_user.id))
    gear = GearItem(
        user_id=user_id,
        gear_type=body.gear_type,
        name=body.name,
        brand=body.brand,
        model=body.model,
        purchase_date=body.purchase_date,
        initial_km=body.initial_km,
        notes=body.notes,
    )
    db.add(gear)
    await db.commit()
    await db.refresh(gear)
    return {"id": str(gear.id), "name": gear.name, "gear_type": gear.gear_type}


@router.patch("/gear/{gear_id}")
async def update_gear(
    gear_id: str,
    body: GearUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = uuid.UUID(str(current_user.id))
    result = await db.execute(
        select(GearItem).where(
            GearItem.id == uuid.UUID(gear_id),
            GearItem.user_id == user_id,
        )
    )
    gear = result.scalar_one_or_none()
    if not gear:
        raise HTTPException(status_code=404, detail="Ausrüstung nicht gefunden")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(gear, field, value)
    await db.commit()
    return {"id": str(gear.id), "name": gear.name, "retired": gear.retired}


@router.delete("/gear/{gear_id}", status_code=204, response_model=None)
async def delete_gear(
    gear_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    user_id = uuid.UUID(str(current_user.id))
    result = await db.execute(
        select(GearItem).where(
            GearItem.id == uuid.UUID(gear_id),
            GearItem.user_id == user_id,
        )
    )
    gear = result.scalar_one_or_none()
    if gear:
        await db.delete(gear)
        await db.commit()
