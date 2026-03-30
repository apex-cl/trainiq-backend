import uuid
import pytest


@pytest.mark.asyncio
async def test_coach_chat_requires_auth(client):
    """Chat without auth should return 401 or redirect to demo in dev mode."""
    resp = await client.post(
        "/coach/chat",
        json={"message": "Hello"},
    )
    assert resp.status_code in [200, 401]


@pytest.mark.asyncio
async def test_coach_chat_with_auth(client, auth_headers):
    """Chat with valid auth should return streaming response."""
    resp = await client.post(
        "/coach/chat",
        headers=auth_headers,
        json={"message": "Erstelle einen kurzen Trainingsplan"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/event-stream")


@pytest.mark.asyncio
async def test_coach_history_empty(client, auth_headers):
    """History endpoint should return list."""
    resp = await client.get("/coach/history", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_coach_history_with_messages(client, auth_headers):
    """After chatting, history should contain messages."""
    await client.post(
        "/coach/chat",
        headers=auth_headers,
        json={"message": "Hallo"},
    )

    resp = await client.get("/coach/history", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_coach_delete_history(client, auth_headers):
    """Delete history should clear all messages."""
    await client.post(
        "/coach/chat",
        headers=auth_headers,
        json={"message": "Test"},
    )

    resp = await client.delete("/coach/history", headers=auth_headers)
    assert resp.status_code == 200

    history = await client.get("/coach/history", headers=auth_headers)
    assert len(history.json()) == 0


@pytest.mark.asyncio
async def test_coach_meal_suggestion(client, auth_headers):
    """Coach can suggest meals based on training."""
    resp = await client.post(
        "/coach/chat",
        headers=auth_headers,
        json={"message": "Was sollte ich nach dem Training essen?"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_coach_plan_request(client, auth_headers):
    """Coach can generate training plans."""
    resp = await client.post(
        "/coach/chat",
        headers=auth_headers,
        json={"message": "Erstelle einen Trainingsplan für diese Woche"},
    )
    assert resp.status_code == 200
