import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.database import get_db
from app.core.config import settings
from app.api.dependencies import get_current_user
from app.models.user import User
from app.services.keycloak_service import keycloak_service
from app.services.jwt_service import jwt_service

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class TokenExchangeRequest(BaseModel):
    code: str
    redirect_uri: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


@router.get("/login")
async def login():
    if not settings.keycloak_enabled:
        raise HTTPException(
            status_code=400, detail="Keycloak is not enabled. Use local authentication."
        )
    state = secrets.token_urlsafe(32)
    redirect_uri = f"{settings.frontend_url}/api/auth/callback"
    auth_url = keycloak_service.get_login_url(redirect_uri, state)
    return {"auth_url": auth_url, "state": state}


@router.get("/register")
async def register():
    if not settings.keycloak_enabled:
        raise HTTPException(
            status_code=400, detail="Keycloak is not enabled. Use local authentication."
        )
    state = secrets.token_urlsafe(32)
    redirect_uri = f"{settings.frontend_url}/api/auth/callback"
    register_url = keycloak_service.get_register_url(redirect_uri, state)
    return {"register_url": register_url, "state": state}


@router.post("/callback")
@limiter.limit("10/minute")
async def callback(request: Request, body: TokenExchangeRequest, db: AsyncSession = Depends(get_db)):
    if not settings.keycloak_enabled:
        raise HTTPException(status_code=400, detail="Keycloak is not enabled.")

    # Validate redirect_uri comes from our own frontend (prevents open redirect / token theft)
    allowed_prefixes = (
        settings.frontend_url,
        "http://localhost",
        "http://localhost:3000",
    )
    if not any(body.redirect_uri.startswith(p) for p in allowed_prefixes):
        raise HTTPException(status_code=400, detail="Ungültige redirect_uri")

    token_data = await keycloak_service.exchange_code(
        body.code, body.redirect_uri
    )
    if not token_data:
        raise HTTPException(
            status_code=400, detail="Failed to exchange code for tokens"
        )

    userinfo = await keycloak_service.get_userinfo(token_data["access_token"])
    if not userinfo:
        raise HTTPException(status_code=400, detail="Failed to get user info")

    email = userinfo.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="No email in Keycloak userinfo")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            email=email,
            name=userinfo.get("name") or userinfo.get("preferred_username") or "User",
            keycloak_id=userinfo.get("sub"),
            email_verified=userinfo.get("email_verified", False),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        user.keycloak_id = userinfo.get("sub")
        user.email_verified = userinfo.get("email_verified", user.email_verified)
        await db.commit()

    app_token = jwt_service.create_access_token({"sub": str(user.id)})

    return {
        "access_token": app_token,
        "refresh_token": token_data.get("refresh_token"),
        "id_token": token_data.get("id_token"),
        "token_type": "bearer",
        "expires_in": token_data.get("expires_in", 300),
        "user": {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "email_verified": user.email_verified,
            "subscription_tier": user.subscription_tier,
        },
    }


@router.post("/refresh")
@limiter.limit("10/minute")
async def refresh(request: Request, body: RefreshTokenRequest):
    if not settings.keycloak_enabled:
        raise HTTPException(status_code=400, detail="Keycloak is not enabled.")

    token_data = await keycloak_service.refresh_token(body.refresh_token)
    if not token_data:
        raise HTTPException(status_code=400, detail="Failed to refresh token")

    return {
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_type": "bearer",
        "expires_in": token_data.get("expires_in", 300),
    }


@router.post("/logout")
async def logout(
    body: LogoutRequest,
    current_user: User = Depends(get_current_user),
):
    if settings.keycloak_enabled:
        await keycloak_service.logout(body.refresh_token)

    return {"ok": True, "message": "Erfolgreich abgemeldet."}


@router.get("/userinfo")
async def userinfo(current_user: User = Depends(get_current_user)):
    if not settings.keycloak_enabled:
        raise HTTPException(status_code=400, detail="Keycloak is not enabled.")

    return {
        "sub": current_user.keycloak_id or str(current_user.id),
        "email": current_user.email,
        "name": current_user.name,
        "email_verified": current_user.email_verified,
        "preferred_username": current_user.email.split("@")[0],
    }


@router.get("/keys")
async def jwks():
    if not settings.keycloak_enabled:
        raise HTTPException(status_code=400, detail="Keycloak is not enabled.")

    jwks = await keycloak_service.get_jwks()
    if not jwks:
        raise HTTPException(status_code=400, detail="Failed to get JWKS")

    return jwks
