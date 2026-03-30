import uuid
import re
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import settings
from app.models.user import User
from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


# ─── Request Models ──────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not EMAIL_REGEX.match(v):
            raise ValueError("Ungültige E-Mail-Adresse")
        return v.lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Passwort muss mindestens 8 Zeichen lang sein")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Neues Passwort muss mindestens 8 Zeichen lang sein")
        return v


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Passwort muss mindestens 8 Zeichen lang sein")
        return v


# ─── Local Auth Endpoints ────────────────────────────────────────────────────


@router.post("/register")
@limiter.limit("5/minute")
async def register(
    request: Request, request_data: RegisterRequest, db: AsyncSession = Depends(get_db)
):
    """Register a new user with email/password. Returns JWT token."""
    existing = await db.execute(select(User).where(User.email == request_data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="E-Mail bereits registriert")

    verification_token = secrets.token_urlsafe(32)
    user = User(
        id=uuid.uuid4(),
        email=request_data.email,
        name=request_data.name,
        password_hash=hash_password(request_data.password),
        verification_token=verification_token,
        verification_expires=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(user)
    await db.flush()

    # Welcome + Verification Mail (non-blocking, darf nicht die Registrierung blockieren)
    try:
        from app.services.email_service import EmailService
        email_svc = EmailService()
        await email_svc.send_welcome(user.email, user.name)
        await email_svc.send_verification(user.email, user.name, verification_token)
    except Exception as e:
        logger.warning(f"Registration emails failed | user={user.id} | error={e}")

    token = create_access_token({"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
        },
    }


@router.post("/login")
@limiter.limit("5/minute")
async def login(
    request: Request, request_data: LoginRequest, db: AsyncSession = Depends(get_db)
):
    """Login with email/password. Returns JWT token."""
    result = await db.execute(select(User).where(User.email == request_data.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")
    if not user.password_hash:
        raise HTTPException(status_code=401, detail="Bitte melde dich über Keycloak an")
    if not verify_password(request_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")

    token = create_access_token({"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
        },
    }


@router.post("/change-password")
async def change_password(
    request_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the current user's password."""
    if not current_user.password_hash:
        raise HTTPException(
            status_code=400,
            detail="Passwort kann nur für lokale Accounts geändert werden. Nutze Keycloak.",
        )
    if not verify_password(request_data.current_password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Aktuelles Passwort ist falsch")

    current_user.password_hash = hash_password(request_data.new_password)
    await db.flush()
    return {"ok": True}


# ─── Password Reset (lokaler Auth-Flow) ─────────────────────────────────────


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    request_data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Sends a password-reset email for local-auth users."""
    result = await db.execute(
        select(User).where(User.email == request_data.email.lower())
    )
    user = result.scalar_one_or_none()

    # Immer 200 zurückgeben, um User-Enumeration zu vermeiden
    if not user or not user.password_hash:
        return {"ok": True, "message": "Falls die E-Mail existiert, wurde ein Link gesendet."}

    try:
        from app.services.email_service import EmailService
        email_svc = EmailService()
        await email_svc.send_password_reset(user.email, user.name, db)
    except Exception as e:
        logger.error(f"Password reset email failed | user={user.id} | error={e}")
        raise HTTPException(status_code=500, detail="E-Mail konnte nicht gesendet werden.")

    return {"ok": True, "message": "Falls die E-Mail existiert, wurde ein Link gesendet."}


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    request_data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Resets the password using a token from the reset email."""
    from app.services.email_service import EmailService
    email_svc = EmailService()
    new_hash = hash_password(request_data.new_password)
    success = await email_svc.use_reset_token(request_data.token, new_hash, db)
    if not success:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener Token.")
    return {"ok": True, "message": "Passwort erfolgreich zurückgesetzt."}


# ─── E-Mail-Verifizierung (lokaler Auth-Flow) ────────────────────────────────


@router.post("/verify-email/send")
@limiter.limit("3/minute")
async def send_verification_email(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resends the email verification link."""
    if current_user.email_verified:
        return {"ok": True, "message": "E-Mail ist bereits verifiziert."}

    verification_token = secrets.token_urlsafe(32)
    current_user.verification_token = verification_token
    current_user.verification_expires = datetime.now(timezone.utc) + timedelta(hours=24)
    await db.flush()

    try:
        from app.services.email_service import EmailService
        email_svc = EmailService()
        await email_svc.send_verification(current_user.email, current_user.name, verification_token)
    except Exception as e:
        logger.error(f"Verification email failed | user={current_user.id} | error={e}")
        raise HTTPException(status_code=500, detail="E-Mail konnte nicht gesendet werden.")

    return {"ok": True, "message": "Verifizierungs-E-Mail wurde gesendet."}


@router.get("/verify-email/{token}")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    """Verifies the email address via token from the verification email."""
    result = await db.execute(
        select(User).where(
            User.verification_token == token,
            User.verification_expires > datetime.now(timezone.utc),
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener Verifizierungs-Link.")

    user.email_verified = True
    user.verification_token = None
    user.verification_expires = None
    await db.flush()
    return {"ok": True, "message": "E-Mail erfolgreich verifiziert."}


# ─── Keycloak Helper Endpoints ───────────────────────────────────────────────


@router.get("/keycloak-login-url")
async def get_keycloak_login_url():
    if not settings.keycloak_enabled:
        raise HTTPException(
            status_code=400,
            detail="Keycloak is not enabled",
        )
    from app.services.keycloak_service import keycloak_service

    state = secrets.token_urlsafe(32)
    redirect_uri = f"{settings.frontend_url}/api/auth/callback"
    auth_url = keycloak_service.get_login_url(redirect_uri, state)
    return {"auth_url": auth_url, "state": state}


@router.get("/keycloak-register-url")
async def get_keycloak_register_url():
    if not settings.keycloak_enabled:
        raise HTTPException(
            status_code=400,
            detail="Keycloak is not enabled",
        )
    from app.services.keycloak_service import keycloak_service

    state = secrets.token_urlsafe(32)
    redirect_uri = f"{settings.frontend_url}/api/auth/callback"
    register_url = keycloak_service.get_register_url(redirect_uri, state)
    return {"register_url": register_url, "state": state}


# ─── 2FA (via Keycloak) ──────────────────────────────────────────────────────


@router.post("/2fa/setup")
async def setup_2fa_deprecated():
    raise HTTPException(
        status_code=410,
        detail="Two-factor authentication is handled by Keycloak. Configure 2FA in Keycloak account settings.",
    )


@router.post("/2fa/enable")
async def enable_2fa_deprecated():
    raise HTTPException(
        status_code=410,
        detail="Two-factor authentication is handled by Keycloak.",
    )


@router.post("/2fa/disable")
async def disable_2fa_deprecated():
    raise HTTPException(
        status_code=410,
        detail="Two-factor authentication is handled by Keycloak.",
    )


@router.post("/2fa/verify")
async def verify_2fa_deprecated():
    raise HTTPException(
        status_code=410,
        detail="Two-factor authentication is handled by Keycloak.",
    )


# ─── User Info ───────────────────────────────────────────────────────────────


@router.get("/me")
async def me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.training import UserGoal

    goals_result = await db.execute(
        select(UserGoal).where(UserGoal.user_id == current_user.id)
    )
    has_goals = goals_result.scalars().first() is not None
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "name": current_user.name,
        "email_verified": current_user.email_verified,
        "two_factor_enabled": current_user.two_factor_enabled,
        "subscription_tier": current_user.subscription_tier,
        "created_at": current_user.created_at.isoformat(),
        "has_goals": has_goals,
    }
