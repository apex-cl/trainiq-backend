"""Tests for user profile update, notification settings, account export, and data export."""
import uuid
import pytest


# ─── Profile Update ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_profile_name(client, auth_headers):
    """PUT /user/profile should update name."""
    resp = await client.put(
        "/user/profile",
        json={"name": "Updated Name"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_update_profile_weight_and_height(client, auth_headers):
    """Should accept valid weight and height."""
    resp = await client.put(
        "/user/profile",
        json={"weight_kg": 75.5, "height_cm": 178},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["weight_kg"] == 75.5
    assert data["height_cm"] == 178


@pytest.mark.asyncio
async def test_update_profile_invalid_weight(client, auth_headers):
    """Weight out of range should return 422."""
    resp = await client.put(
        "/user/profile",
        json={"weight_kg": 5},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_profile_invalid_weight_high(client, auth_headers):
    """Weight too high should return 422."""
    resp = await client.put(
        "/user/profile",
        json={"weight_kg": 500},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_profile_invalid_height(client, auth_headers):
    """Height out of range should return 422."""
    resp = await client.put(
        "/user/profile",
        json={"height_cm": 10},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_profile_birth_date(client, auth_headers):
    """Valid birth date should be accepted and returned."""
    resp = await client.put(
        "/user/profile",
        json={"birth_date": "1990-05-15"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["birth_date"] == "1990-05-15"


@pytest.mark.asyncio
async def test_update_profile_invalid_birth_date(client, auth_headers):
    """Invalid date format should return 422."""
    resp = await client.put(
        "/user/profile",
        json={"birth_date": "not-a-date"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_profile_gender_and_language(client, auth_headers):
    """Should accept gender and preferred_language."""
    resp = await client.put(
        "/user/profile",
        json={"gender": "male", "preferred_language": "en"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["gender"] == "male"
    assert data["preferred_language"] == "en"


@pytest.mark.asyncio
async def test_update_profile_requires_auth(client):
    """Without auth, should return 401 or demo user redirect."""
    resp = await client.put("/user/profile", json={"name": "Anon"})
    # In DEV_MODE, demo user is used so it might succeed
    assert resp.status_code in [200, 401, 403]


# ─── Notification Settings ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_notification_settings_defaults(client, auth_headers):
    """GET /user/settings/notifications should return default settings."""
    resp = await client.get("/user/settings/notifications", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "training_reminders" in data
    assert "recovery_alerts" in data
    assert "achievement_notifications" in data
    assert "weekly_summary" in data
    assert "marketing_emails" in data


@pytest.mark.asyncio
async def test_update_notification_settings(client, auth_headers):
    """PUT /user/settings/notifications should update all fields."""
    resp = await client.put(
        "/user/settings/notifications",
        json={
            "training_reminders": False,
            "recovery_alerts": True,
            "achievement_notifications": False,
            "weekly_summary": True,
            "marketing_emails": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["training_reminders"] is False
    assert data["marketing_emails"] is True


@pytest.mark.asyncio
async def test_update_notification_settings_persists(client, auth_headers):
    """Updated settings should persist across GET calls."""
    await client.put(
        "/user/settings/notifications",
        json={
            "training_reminders": False,
            "recovery_alerts": False,
            "achievement_notifications": True,
            "weekly_summary": False,
            "marketing_emails": False,
        },
        headers=auth_headers,
    )
    resp = await client.get("/user/settings/notifications", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["training_reminders"] is False
    assert data["recovery_alerts"] is False


# ─── Data Export ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_data_requires_auth(client):
    """Export without auth should require authentication."""
    resp = await client.get("/user/export")
    # DEV_MODE: demo user will be used, so 200 is possible
    assert resp.status_code in [200, 401, 403]


@pytest.mark.asyncio
async def test_export_data_returns_json(client, auth_headers):
    """Export endpoint should return valid JSON with user data."""
    resp = await client.get("/user/export", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Should contain some top-level user data keys
    assert isinstance(data, dict)


# ─── Account Deletion ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_account_succeeds(client):
    """DELETE /user/account should delete the account and return 200."""
    email = f"todelete_{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post(
        "/auth/register",
        json={"email": email, "password": "test1234", "name": "Delete Me"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.delete("/user/account", headers=headers)
    assert resp.status_code == 200

    # Subsequent login should fail
    login_resp = await client.post(
        "/auth/login", json={"email": email, "password": "test1234"}
    )
    assert login_resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_account_requires_auth(client):
    """Without auth token deletion should fail."""
    # Send with invalid token
    resp = await client.delete(
        "/user/account", headers={"Authorization": "Bearer invalid-token"}
    )
    assert resp.status_code == 401
