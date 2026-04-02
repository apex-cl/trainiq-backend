"""
Push Notification Service - Web Push Notifications via VAPID
Docs: https://developer.mozilla.org/en-US/docs/Web/API/Push_API
"""

import json
import httpx
from datetime import datetime, timezone
from typing import Optional
from loguru import logger
from sqlalchemy import Column, Integer, String, DateTime, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import async_session, Base
from app.models.user import User


class PushSubscriptionModel(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    endpoint = Column(String, nullable=False, unique=True)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class PushNotificationService:
    """Sendet Web Push Notifications an User."""

    def __init__(self):
        self.vapid_public_key = settings.vapid_public_key
        self.vapid_private_key = settings.vapid_private_key

    async def subscribe(
        self, user_id: str, endpoint: str, p256dh: str, auth: str, db: AsyncSession
    ) -> PushSubscriptionModel:
        """Speichert ein neues Push-Abo."""
        existing = await db.execute(
            select(PushSubscriptionModel).where(
                PushSubscriptionModel.endpoint == endpoint
            )
        )
        if existing.scalars().first():
            raise ValueError("Endpoint bereits registriert")

        sub = PushSubscriptionModel(
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
        )
        db.add(sub)
        await db.flush()
        return sub

    async def unsubscribe(self, endpoint: str, user_id: str, db: AsyncSession) -> bool:
        """Löscht ein Push-Abo — nur wenn es dem anfragenden User gehört."""
        result = await db.execute(
            select(PushSubscriptionModel).where(
                PushSubscriptionModel.endpoint == endpoint,
                PushSubscriptionModel.user_id == user_id,
            )
        )
        sub = result.scalar_one_or_none()
        if sub:
            await db.delete(sub)
            await db.flush()
            return True
        return False

    async def send_notification(
        self,
        user_id: str,
        title: str,
        body: str,
        icon: str = "/icon.png",
        badge: str = "/badge.png",
        tag: str = "",
        data: Optional[dict] = None,
    ) -> int:
        """Sendet eine Push-Notification an einen User. Returns Anzahl gesendeter Nachrichten."""
        if not self.vapid_private_key:
            logger.warning("Push notifications disabled - no VAPID keys configured")
            return 0

        async with async_session() as db:
            result = await db.execute(
                select(PushSubscriptionModel).where(
                    PushSubscriptionModel.user_id == user_id
                )
            )
            subscriptions = result.scalars().all()

            if not subscriptions:
                return 0

            sent = 0
            for sub in subscriptions:
                try:
                    await self._send_vapid_push(
                        endpoint=sub.endpoint,
                        p256dh=sub.p256dh,
                        auth=sub.auth,
                        title=title,
                        body=body,
                        icon=icon,
                        badge=badge,
                        tag=tag,
                        data=data,
                    )
                    sent += 1
                except Exception as e:
                    logger.warning(
                        f"Push notification failed | endpoint={sub.endpoint[:50]}... | error={e}"
                    )
                    continue

            return sent

    async def _send_vapid_push(
        self,
        endpoint: str,
        p256dh: str,
        auth: str,
        title: str,
        body: str,
        icon: str,
        badge: str,
        tag: str,
        data: Optional[dict],
    ):
        """Sendet eine einzelne VAPID Push-Notification."""
        from webpush import send_notification
        from webpush import (
            encode_bytes,
        )

        vapid_claim = {
            "sub": settings.from_email,
            "aud": endpoint.split("/")[2],
        }

        notification = {
            "title": title,
            "body": body,
            "icon": icon,
            "badge": badge,
            "tag": tag,
            "data": data,
            "vapid": vapid_claim,
            "vapid_private_key": self.vapid_private_key,
        }

        await send_notification(
            endpoint,
            json.dumps(notification),
            vapid_private_key=self.vapid_private_key,
            vapid_claims=vapid_claim,
        )


async def notify_training_reminder(user_id: str, workout_name: str, time_until: str):
    """Sendet eine Training-Erinnerung."""
    service = PushNotificationService()
    return await service.send_notification(
        user_id=user_id,
        title="🏃 Training Zeit!",
        body=f"{workout_name} startet in {time_until}",
        icon="/icons/run.png",
        tag="training_reminder",
        data={"type": "training_reminder", "workout": workout_name},
    )


async def notify_recovery_alert(user_id: str, score: int, message: str):
    """Sendet eine Recovery-Warnung."""
    service = PushNotificationService()
    emoji = "🟢" if score >= 70 else ("🟡" if score >= 40 else "🔴")
    return await service.send_notification(
        user_id=user_id,
        title=f"{emoji} Recovery: {score}%",
        body=message,
        icon="/icons/heart.png",
        tag="recovery_alert",
        data={"type": "recovery_alert", "score": score},
    )


async def notify_achievement_unlocked(
    user_id: str, achievement_name: str, description: str
):
    """Sendet eine Achievement-Benachrichtigung."""
    service = PushNotificationService()
    return await service.send_notification(
        user_id=user_id,
        title="🎉 Achievement unlocked!",
        body=f"{achievement_name}: {description}",
        icon="/icons/trophy.png",
        tag="achievement",
        data={"type": "achievement", "name": achievement_name},
    )
