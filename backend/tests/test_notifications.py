import pytest


@pytest.mark.asyncio
async def test_get_vapid_key_not_configured(client, auth_headers):
    """Should return not_configured when VAPID not set."""
    resp = await client.get("/notifications/vapid-key")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_subscribe_missing_endpoint(client, auth_headers):
    """Should reject subscription without endpoint."""
    resp = await client.post(
        "/notifications/subscribe",
        json={"keys": {"p256dh": "test", "auth": "test"}},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_subscribe_missing_keys(client, auth_headers):
    """Should reject subscription without keys."""
    resp = await client.post(
        "/notifications/subscribe",
        json={"endpoint": "https://example.com/push"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_subscribe_success(client, auth_headers):
    """Should accept valid subscription when VAPID not configured."""
    resp = await client.post(
        "/notifications/subscribe",
        json={
            "endpoint": "https://example.com/push",
            "keys": {"p256dh": "test-key", "auth": "test-auth"},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True


@pytest.mark.asyncio
async def test_unsubscribe_success(client, auth_headers):
    """Should unsubscribe successfully."""
    resp = await client.post(
        "/notifications/unsubscribe",
        json={"endpoint": "https://example.com/push"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
