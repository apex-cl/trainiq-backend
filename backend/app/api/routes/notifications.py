"""
Push Notification Routes

Speichert Web-Push-Subscriptions und ermöglicht das Versenden von Push-Benachrichtigungen.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.api.dependencies import get_current_user
from app.models.user import User
from app.core.config import settings
from app.core.database import get_db
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class PushSubscriptionRequest(BaseModel):
    endpoint: str
    keys: dict  # p256dh, auth


class PushUnsubscribeRequest(BaseModel):
    endpoint: str


@router.get("/vapid-key")
async def get_vapid_public_key():
    """Gibt den VAPID Public Key für die Push-Registrierung zurück."""
    if not settings.vapid_public_key:
        return {"status": "not_configured"}
    return {"public_key": settings.vapid_public_key}


@router.post("/subscribe")
async def subscribe_push(
    body: PushSubscriptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Speichert eine Web-Push-Subscription für den User."""
    if not settings.vapid_private_key:
        return {"ok": True, "status": "vapid_not_configured"}

    if not body.endpoint or not body.keys:
        raise HTTPException(status_code=400, detail="Missing endpoint or keys")

    try:
        from app.services.push_notification import PushNotificationService

        service = PushNotificationService()
        await service.subscribe(
            user_id=str(current_user.id),
            endpoint=body.endpoint,
            p256dh=body.keys.get("p256dh", ""),
            auth=body.keys.get("auth", ""),
            db=db,
        )
        await db.commit()
        logger.info(f"Push subscription saved | user={current_user.id}")
    except Exception as e:
        logger.warning(
            f"Push subscription save failed | user={current_user.id} | error={e}"
        )
        if db:
            await db.rollback()
        return {"ok": False, "error": str(e)}, 500

    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe_push(
    body: PushUnsubscribeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Löscht eine Web-Push-Subscription für den User."""
    try:
        from app.services.push_notification import PushNotificationService

        service = PushNotificationService()
        await service.unsubscribe(body.endpoint, db)
        await db.commit()
        logger.info(f"Push subscription removed | user={current_user.id}")
    except Exception as e:
        logger.warning(f"Push unsubscribe failed | user={current_user.id} | error={e}")
        await db.rollback()

    return {"ok": True}
