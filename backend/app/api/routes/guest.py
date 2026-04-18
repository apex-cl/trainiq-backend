from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.database import get_db
from app.core.config import settings
from app.models.guest import GuestSession

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/session")
@limiter.limit("5/minute")
async def create_guest_session(request: Request, db: AsyncSession = Depends(get_db)):
    """Erstellt eine neue Gast-Session. Gibt Session-Token zurück."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=settings.guest_session_hours)

    guest = GuestSession(expires_at=expires)
    db.add(guest)
    await db.commit()
    await db.refresh(guest)

    return {
        "guest_token": guest.id,
        "expires_at": guest.expires_at.isoformat(),
        "limits": {
            "max_messages": settings.guest_max_messages,
            "max_photos": settings.guest_max_photos,
        },
    }


@router.get("/session/{guest_token}")
async def get_guest_session(guest_token: str, db: AsyncSession = Depends(get_db)):
    """Gibt den Status einer Gast-Session zurück."""
    result = await db.execute(
        select(GuestSession).where(
            GuestSession.id == guest_token,
            GuestSession.expires_at > datetime.now(timezone.utc),
        )
    )
    guest = result.scalar_one_or_none()

    if not guest:
        raise HTTPException(
            status_code=404, detail="Gast-Session nicht gefunden oder abgelaufen"
        )

    return {
        "guest_token": guest.id,
        "message_count": guest.message_count,
        "photo_count": guest.photo_count,
        "messages_remaining": max(0, settings.guest_max_messages - guest.message_count),
        "photos_remaining": max(0, settings.guest_max_photos - guest.photo_count),
        "expires_at": guest.expires_at.isoformat(),
    }
