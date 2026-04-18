"""Extended auth tests: forgot-password, reset-password, verify-email, 2FA stubs, Keycloak."""
import uuid
import pytest
from datetime import datetime, timedelta, timezone


# ─── Forgot Password ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forgot_password_existing_user(client):
    """Always returns 200 even for existing user (prevents user enumeration)."""
    email = f"forgotpw_{uuid.uuid4().hex[:8]}@test.com"
    await client.post(
        "/auth/register",
        json={"email": email, "password": "test1234", "name": "Forgot PW User"},
    )
    resp = await client.post("/auth/forgot-password", json={"email": email})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_forgot_password_nonexistent_user(client):
    """Should return 200 even for non-existing email to prevent enumeration."""
    resp = await client.post(
        "/auth/forgot-password",
        json={"email": "doesnotexist@test.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ─── Reset Password ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_password_invalid_token(client):
    """Invalid reset token should return 400."""
    resp = await client.post(
        "/auth/reset-password",
        json={"token": "totally-invalid-token", "new_password": "newpassword1"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reset_password_short_password(client):
    """New password too short should return 422."""
    resp = await client.post(
        "/auth/reset-password",
        json={"token": "sometoken", "new_password": "short"},
    )
    assert resp.status_code == 422


# ─── Verify Email ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_email_invalid_token(client):
    """Invalid verification token should return 400."""
    resp = await client.get("/auth/verify-email/invalid-token-xyz")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_send_verification_email_already_verified(client):
    """Resending verification to already-verified user should return 200 with message."""
    email = f"verified_{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post(
        "/auth/register",
        json={"email": email, "password": "test1234", "name": "Verified User"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Mark email as verified via DB
    from app.core.database import async_session as db_session
    from app.models.user import User
    from sqlalchemy import select, update

    import app.core.database as db_module
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    async with db_module.async_session() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user.email_verified = True
            await session.commit()

    resp = await client.post("/auth/verify-email/send", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_verify_email_valid_token(client):
    """Valid token should verify email and return 200."""
    import secrets
    from app.models.user import User
    from sqlalchemy import select
    import app.core.database as db_module

    email = f"toverify_{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post(
        "/auth/register",
        json={"email": email, "password": "test1234", "name": "To Verify"},
    )
    assert reg.status_code == 200

    # Get the verification token from DB
    async with db_module.async_session() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        assert user is not None
        vtoken = user.verification_token

    if not vtoken:
        pytest.skip("No verification token set (email module missing)")

    resp = await client.get(f"/auth/verify-email/{vtoken}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verify DB state updated
    async with db_module.async_session() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        assert user.email_verified is True
        assert user.verification_token is None


# ─── 2FA Stubs (deprecated, via Keycloak) ────────────────────────────────────


@pytest.mark.asyncio
async def test_2fa_setup_returns_410(client, auth_headers):
    """2FA setup endpoint is deprecated, should return 410."""
    resp = await client.post("/auth/2fa/setup", headers=auth_headers)
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_2fa_enable_returns_410(client, auth_headers):
    """2FA enable endpoint is deprecated, should return 410."""
    resp = await client.post("/auth/2fa/enable", headers=auth_headers)
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_2fa_disable_returns_410(client, auth_headers):
    """2FA disable endpoint is deprecated, should return 410."""
    resp = await client.post("/auth/2fa/disable", headers=auth_headers)
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_2fa_verify_returns_410(client, auth_headers):
    """2FA verify endpoint is deprecated, should return 410."""
    resp = await client.post("/auth/2fa/verify", headers=auth_headers)
    assert resp.status_code == 410


# ─── Keycloak Endpoints ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_keycloak_login_url_returns_data(client):
    """GET /auth/keycloak-login-url should return 200 with a url or 400 when disabled."""
    resp = await client.get("/auth/keycloak-login-url")
    # Keycloak defaults to enabled — returns auth_url. Disabled → 400.
    assert resp.status_code in [200, 400]
    if resp.status_code == 200:
        data = resp.json()
        assert "auth_url" in data or "error" in data


@pytest.mark.asyncio
async def test_keycloak_register_url_returns_data(client):
    """GET /auth/keycloak-register-url should return 200 with a url or 400 when disabled."""
    resp = await client.get("/auth/keycloak-register-url")
    assert resp.status_code in [200, 400]
    if resp.status_code == 200:
        data = resp.json()
        assert "register_url" in data or "error" in data


# ─── Me endpoint details ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_returns_subscription_tier(client, auth_headers):
    """GET /auth/me should include subscription_tier."""
    resp = await client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "subscription_tier" in data


@pytest.mark.asyncio
async def test_me_without_auth_returns_demo_in_dev_mode(client):
    """Without auth in DEV_MODE, should return demo user."""
    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "demo@trainiq.app"
