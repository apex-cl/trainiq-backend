import uuid
import pytest


@pytest.mark.asyncio
async def test_create_goal(client, auth_headers):
    resp = await client.post(
        "/user/goals",
        json={
            "sport": "running",
            "goal_description": "Marathon unter 4 Stunden",
            "target_date": "2025-12-31",
            "weekly_hours": 6,
            "fitness_level": "advanced",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sport"] == "running"
    assert data["goal_description"] == "Marathon unter 4 Stunden"
    assert data["weekly_hours"] == 6


@pytest.mark.asyncio
async def test_upsert_goal(client, auth_headers):
    payload1 = {
        "sport": "cycling",
        "goal_description": "100km Tour",
        "weekly_hours": 4,
    }
    await client.post("/user/goals", json=payload1, headers=auth_headers)

    payload2 = {
        "sport": "cycling",
        "goal_description": "200km Tour",
        "weekly_hours": 8,
    }
    resp = await client.post("/user/goals", json=payload2, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["goal_description"] == "200km Tour"
    assert data["weekly_hours"] == 8


@pytest.mark.asyncio
async def test_get_goals_empty(client, auth_headers):
    resp = await client.get("/user/goals", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_goals_with_data(client, auth_headers):
    await client.post(
        "/user/goals",
        json={"sport": "swimming", "goal_description": "2km Kraul am Stück"},
        headers=auth_headers,
    )
    resp = await client.get("/user/goals", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(g["sport"] == "swimming" for g in data)


@pytest.mark.asyncio
async def test_get_profile(client, auth_headers):
    resp = await client.get("/user/profile", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "email" in data
    assert "name" in data
    assert "goals" in data
    assert isinstance(data["goals"], list)


@pytest.mark.asyncio
async def test_goal_invalid_sport(client, auth_headers):
    """Should reject German sport names or unknown values."""
    for bad_sport in ["Laufen", "Radfahren", "Schwimmen", "unknown", ""]:
        resp = await client.post(
            "/user/goals",
            json={"sport": bad_sport, "goal_description": "Test"},
            headers=auth_headers,
        )
        assert resp.status_code == 422, f"Expected 422 for sport='{bad_sport}'"


@pytest.mark.asyncio
async def test_goal_invalid_weekly_hours(client, auth_headers):
    """Should reject out-of-range weekly hours."""
    resp = await client.post(
        "/user/goals",
        json={"sport": "running", "goal_description": "Test", "weekly_hours": 50},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_goal_invalid_fitness_level(client, auth_headers):
    """Should reject invalid fitness level strings."""
    resp = await client.post(
        "/user/goals",
        json={
            "sport": "running",
            "goal_description": "Test",
            "fitness_level": "Superman",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_account(client):
    """Delete account should remove user and return 200."""
    email = f"del_{uuid.uuid4().hex[:8]}@test.com"
    reg_resp = await client.post(
        "/auth/register",
        json={"email": email, "password": "test1234", "name": "To Delete"},
    )
    assert reg_resp.status_code == 200
    token = reg_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.delete("/user/account", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
