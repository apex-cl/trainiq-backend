import uuid
import pytest


@pytest.mark.asyncio
async def test_register_success(client):
    resp = await client.post(
        "/auth/register",
        json={
            "email": "newuser@test.com",
            "password": "secure1234",
            "name": "New User",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "newuser@test.com"
    assert data["user"]["name"] == "New User"
    assert "id" in data["user"]


@pytest.mark.asyncio
async def test_register_returns_usable_token(client):
    """Token from register should immediately authenticate."""
    email = f"direct_{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/auth/register",
        json={"email": email, "password": "test1234", "name": "Direct User"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    me_resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == email


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    payload = {
        "email": f"dup_{uuid.uuid4().hex[:8]}@test.com",
        "password": "pass1234",
        "name": "Dup",
    }
    await client.post("/auth/register", json=payload)
    resp = await client.post("/auth/register", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_invalid_email(client):
    resp = await client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "pass1234", "name": "Bad"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_short_password(client):
    resp = await client.post(
        "/auth/register",
        json={"email": "short@test.com", "password": "123", "name": "Short"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client):
    email = f"login_{uuid.uuid4().hex[:8]}@test.com"
    await client.post(
        "/auth/register",
        json={"email": email, "password": "test1234", "name": "Login User"},
    )
    resp = await client.post(
        "/auth/login",
        json={"email": email, "password": "test1234"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == email


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    email = f"wrongpw_{uuid.uuid4().hex[:8]}@test.com"
    await client.post(
        "/auth/register",
        json={"email": email, "password": "correct1234", "name": "Wrong PW"},
    )
    resp = await client.post(
        "/auth/login",
        json={"email": email, "password": "wrongpassword"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client):
    resp = await client.post(
        "/auth/login",
        json={"email": "nonexistent@test.com", "password": "whatever1234"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_with_token(client, auth_headers):
    resp = await client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "email" in data
    assert "name" in data
    assert "id" in data


@pytest.mark.asyncio
async def test_me_without_token_dev_mode(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "demo@trainiq.app"


@pytest.mark.asyncio
async def test_change_password_success(client):
    """Changing password with correct current password should succeed."""
    email = f"changepw_{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post(
        "/auth/register",
        json={"email": email, "password": "oldpassword1", "name": "PW User"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/auth/change-password",
        json={"current_password": "oldpassword1", "new_password": "newpassword2"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_change_password_wrong_current(client):
    """Should reject change if current password is wrong."""
    email = f"badpw_{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post(
        "/auth/register",
        json={"email": email, "password": "correctpassword1", "name": "Bad PW"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/auth/change-password",
        json={"current_password": "wrongpassword", "new_password": "newpassword2"},
        headers=headers,
    )
    assert resp.status_code == 401
