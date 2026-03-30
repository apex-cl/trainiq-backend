import random
import uuid as uuid_module
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.metrics import HealthMetric


class WatchSync:
    """Synchronizes health and fitness data from smartwatches."""

    @staticmethod
    def _uid(user_id: str):
        return uuid_module.UUID(user_id) if isinstance(user_id, str) else user_id

    async def sync_manual_entry(self, user_id: str, data: dict, db: AsyncSession):
        """Speichert manuell eingegebene Gesundheitsdaten in health_metrics."""
        uid = self._uid(user_id)
        metric = HealthMetric(
            user_id=uid,
            recorded_at=datetime.now(timezone.utc),
            hrv=data.get("hrv"),
            resting_hr=data.get("resting_hr"),
            sleep_duration_min=data.get("sleep_duration_min"),
            sleep_quality_score=data.get("sleep_quality_score"),
            stress_score=data.get("stress_score"),
            spo2=data.get("spo2"),
            steps=data.get("steps"),
            source="manual",
        )
        db.add(metric)
        await db.flush()
        return metric

    async def get_demo_data(self, user_id: str, db: AsyncSession):
        """Generiert realistische Demo-Metriken wenn keine Uhr verbunden."""
        uid = self._uid(user_id)
        today = datetime.now(timezone.utc).date()
        result = await db.execute(
            select(HealthMetric).where(
                HealthMetric.user_id == uid,
                HealthMetric.source == "demo",
                HealthMetric.recorded_at
                >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc),
            )
        )
        existing = result.scalars().first()
        if existing:
            return existing

        metric = HealthMetric(
            user_id=uid,
            recorded_at=datetime.now(timezone.utc),
            hrv=round(random.uniform(35.0, 50.0), 1),
            resting_hr=random.randint(55, 70),
            sleep_duration_min=random.randint(360, 510),
            sleep_quality_score=round(random.uniform(60.0, 95.0), 1),
            stress_score=round(random.uniform(25.0, 55.0), 1),
            spo2=round(random.uniform(95.0, 99.0), 1),
            steps=random.randint(5000, 15000),
            source="demo",
        )
        db.add(metric)
        await db.flush()
        return metric

    async def get_watch_status(self, user_id: str, db: AsyncSession) -> dict:
        """Gibt den Verbindungsstatus der Uhr zurück."""
        from app.models.watch import WatchConnection

        uid = self._uid(user_id)

        result = await db.execute(
            select(WatchConnection).where(
                WatchConnection.user_id == uid,
                WatchConnection.is_active == True,
            )
        )
        connection = result.scalars().first()
        if not connection:
            return {"connected": False, "provider": None, "last_synced_at": None}
        return {
            "connected": True,
            "provider": connection.provider,
            "last_synced_at": connection.last_synced_at.isoformat()
            if connection.last_synced_at
            else None,
        }
