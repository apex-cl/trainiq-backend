import uuid
from datetime import datetime, timezone
from typing import Union
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_token
from app.models.user import User
from app.models.guest import GuestSession
from sqlalchemy import select

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/keycloak/login", auto_error=False)


async def _get_user_by_keycloak_id(keycloak_id: str, db: AsyncSession) -> User | None:
    result = await db.execute(select(User).where(User.keycloak_id == keycloak_id))
    return result.scalar_one_or_none()


async def _get_user_by_id(user_id: str, db: AsyncSession) -> User | None:
    try:
        user_uuid = uuid.UUID(user_id)
    except (ValueError, AttributeError):
        return None
    result = await db.execute(select(User).where(User.id == user_uuid))
    return result.scalar_one_or_none()


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if settings.dev_mode and not token:
        result = await db.execute(
            select(User).where(User.id == uuid.UUID(settings.demo_user_id))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Demo user not initialized. Restart backend.",
            )
        return user

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if settings.keycloak_enabled:
        try:
            from app.services.keycloak_jwt_service import keycloak_jwt_service

            payload = await keycloak_jwt_service.verify_keycloak_token(token)
            keycloak_id = payload.get("sub")
            if keycloak_id:
                user = await _get_user_by_keycloak_id(keycloak_id, db)
                if user:
                    return user
                email = payload.get("email")
                if email:
                    result = await db.execute(select(User).where(User.email == email))
                    user = result.scalar_one_or_none()
                    if user:
                        user.keycloak_id = keycloak_id
                        await db.commit()
                        return user
        except HTTPException:
            pass

    payload = verify_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )

    user = await _get_user_by_id(user_id, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return user


async def get_current_user_or_guest(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Union[User, GuestSession]:
    if token:
        return await get_current_user(token=token, db=db)

    guest_token = request.headers.get("X-Guest-Token")
    if guest_token:
        result = await db.execute(
            select(GuestSession).where(
                GuestSession.id == guest_token,
                GuestSession.expires_at > datetime.now(timezone.utc),
            )
        )
        guest = result.scalar_one_or_none()
        if guest:
            return guest

    if settings.dev_mode:
        result = await db.execute(
            select(User).where(User.id == uuid.UUID(settings.demo_user_id))
        )
        user = result.scalar_one_or_none()
        if user:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required (JWT or X-Guest-Token)",
    )
