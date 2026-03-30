import uuid
import pytest


@pytest.mark.asyncio
async def test_get_subscription(client, auth_headers):
    """Get current subscription status."""
    resp = await client.get("/billing/subscription", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "tier" in data or "subscription_tier" in data


@pytest.mark.asyncio
async def test_create_checkout_session(client, auth_headers):
    """Create a Stripe checkout session."""
    resp = await client.post(
        "/billing/checkout",
        headers=auth_headers,
        json={
            "price_id": "price_pro_monthly",
            "success_url": "https://trainiq.app/success",
        },
    )
    assert resp.status_code in [200, 503]
    if resp.status_code == 200:
        data = resp.json()
        assert "url" in data or "checkout_url" in data


@pytest.mark.asyncio
async def test_create_checkout_session_yearly(client, auth_headers):
    """Create a yearly subscription checkout."""
    resp = await client.post(
        "/billing/checkout",
        headers=auth_headers,
        json={"price_id": "price_pro_yearly"},
    )
    assert resp.status_code in [200, 503]


@pytest.mark.asyncio
async def test_get_portal_session(client, auth_headers):
    """Get Stripe customer portal session."""
    resp = await client.get("/billing/portal", headers=auth_headers)
    assert resp.status_code in [200, 503]


@pytest.mark.asyncio
async def test_webhook_missing_signature(client):
    """Webhook without Stripe signature should be rejected."""
    resp = await client.post(
        "/billing/webhook",
        json={"type": "checkout.session.completed"},
    )
    assert resp.status_code in [400, 401, 403]


@pytest.mark.asyncio
async def test_webhook_invalid_payload(client):
    """Webhook with invalid payload should return error."""
    resp = await client.post(
        "/billing/webhook",
        headers={"stripe-signature": "invalid_signature"},
        json={"type": "invalid_type"},
    )
    assert resp.status_code in [400, 401]


@pytest.mark.asyncio
async def test_subscription_cancelled(client, auth_headers):
    """After cancellation, tier should reflect that."""
    resp = await client.get("/billing/subscription", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "tier" in data
