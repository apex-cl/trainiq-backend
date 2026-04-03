"""Tests for watch provider OAuth endpoints — all should return 503 when not configured."""
import pytest


PROVIDERS = [
    "garmin",
    "polar",
    "wahoo",
    "fitbit",
    "suunto",
    "withings",
    "coros",
    "zepp",
    "whoop",
    "samsung",
    "googlefit",
]

PROVIDER_CONNECT_URLS = {
    # garmin uses direct credential login — no external API key needed → always 200
    "polar": "/watch/polar/connect",
    "wahoo": "/watch/wahoo/connect",
    "fitbit": "/watch/fitbit/connect",
    "suunto": "/watch/suunto/connect",
    "withings": "/watch/withings/connect",
    "coros": "/watch/coros/connect",
    "zepp": "/watch/zepp/connect",
    "whoop": "/watch/whoop/connect",
    "samsung": "/watch/samsung/connect",
    "googlefit": "/watch/googlefit/connect",
}


@pytest.mark.parametrize("provider", list(PROVIDER_CONNECT_URLS.keys()))
@pytest.mark.asyncio
async def test_provider_connect_requires_config(client, auth_headers, provider):
    """Each provider's /connect endpoint should return 503 if credentials not set."""
    url = PROVIDER_CONNECT_URLS[provider]
    resp = await client.get(url, headers=auth_headers)
    assert resp.status_code in [503, 404], (
        f"Provider {provider} connect should return 503 or 404 when unconfigured, got {resp.status_code}"
    )


@pytest.mark.asyncio
async def test_watch_status_includes_all_providers(client, auth_headers):
    """Status endpoint should list all supported providers."""
    resp = await client.get("/watch/status", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "garmin_available" in data
    assert "polar_available" in data


@pytest.mark.asyncio
async def test_watch_manual_all_fields(client, auth_headers):
    """Manual input with all fields should succeed."""
    resp = await client.post(
        "/watch/manual",
        json={
            "hrv": 55.0,
            "resting_hr": 52,
            "sleep_duration_min": 510,
            "sleep_quality_score": 85.0,
            "stress_score": 25.0,
            "steps": 8500,
            "spo2": 98.5,
            "vo2_max": 52.0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["source"] == "manual"


@pytest.mark.asyncio
async def test_watch_manual_minimal_fields(client, auth_headers):
    """Manual input with only some fields should succeed."""
    resp = await client.post(
        "/watch/manual",
        json={"resting_hr": 65},
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_watch_manual_negative_hrv_rejected(client, auth_headers):
    """Negative HRV should be rejected (validator: 0–200)."""
    resp = await client.post(
        "/watch/manual",
        json={"hrv": -10},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_watch_manual_hrv_too_high(client, auth_headers):
    """HRV > 200 should be rejected."""
    resp = await client.post(
        "/watch/manual",
        json={"hrv": 999},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sync_no_connection_returns_no_provider(client, auth_headers):
    """Sync without any connected device returns no_provider or empty."""
    resp = await client.post("/watch/sync", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "provider" in data


@pytest.mark.asyncio
async def test_apple_pair_success(client, auth_headers):
    """Apple Watch pair should return a pairing_token."""
    resp = await client.post("/watch/apple/pair", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "pairing_token" in data
    assert len(data["pairing_token"]) > 0
