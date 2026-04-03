import uuid
import pytest


@pytest.mark.asyncio
async def test_watch_status_no_connection(client, auth_headers):
    resp = await client.get("/watch/status", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "connected" in data
    assert isinstance(data["connected"], list)


@pytest.mark.asyncio
async def test_watch_sync(client, auth_headers):
    resp = await client.post("/watch/sync", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "synced" in data
    assert "provider" in data


@pytest.mark.asyncio
async def test_watch_manual_input(client, auth_headers):
    resp = await client.post(
        "/watch/manual",
        json={
            "hrv": 42.5,
            "resting_hr": 58,
            "sleep_duration_min": 450,
            "stress_score": 35.0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["source"] == "manual"


@pytest.mark.asyncio
async def test_watch_manual_invalid_hrv(client, auth_headers):
    """Should reject invalid HRV values."""
    resp = await client.post(
        "/watch/manual",
        json={"hrv": 500, "resting_hr": 60},
        headers=auth_headers,
    )
    assert resp.status_code == 422
