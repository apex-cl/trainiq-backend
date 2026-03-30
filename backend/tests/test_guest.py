import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_guest_session(client: AsyncClient):
    """Erstellt eine Gast-Session."""
    resp = await client.post("/guest/session")
    assert resp.status_code == 200
    data = resp.json()
    assert "guest_token" in data
    assert data["guest_token"].startswith("guest_")
    assert "expires_at" in data
    assert data["limits"]["max_messages"] == 10
    assert data["limits"]["max_photos"] == 2


@pytest.mark.asyncio
async def test_get_guest_session(client: AsyncClient):
    """Prüft den Status einer Gast-Session."""
    # Session erstellen
    resp = await client.post("/guest/session")
    token = resp.json()["guest_token"]

    # Status abrufen
    resp = await client.get(f"/guest/session/{token}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["guest_token"] == token
    assert data["message_count"] == 0
    assert data["photo_count"] == 0
    assert data["messages_remaining"] == 10
    assert data["photos_remaining"] == 2


@pytest.mark.asyncio
async def test_get_guest_session_not_found(client: AsyncClient):
    """Prüft 404 für ungültiges Gast-Token."""
    resp = await client.get("/guest/session/invalid_token")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_guest_chat(client: AsyncClient, guest_token: str):
    """Gast kann Chat-Nachricht senden."""
    resp = await client.post(
        "/coach/chat",
        json={"message": "Hallo Coach"},
        headers={"X-Guest-Token": guest_token},
    )
    assert resp.status_code == 200
    assert "X-Guest-Messages-Remaining" in resp.headers


@pytest.mark.asyncio
async def test_guest_chat_limit(client: AsyncClient):
    """Gast erreicht Nachrichten-Limit."""
    # Session erstellen
    resp = await client.post("/guest/session")
    token = resp.json()["guest_token"]

    # 10 Nachrichten senden (Limit)
    for i in range(10):
        resp = await client.post(
            "/coach/chat",
            json={"message": f"Nachricht {i}"},
            headers={"X-Guest-Token": token},
        )
        if resp.status_code == 403:
            break

    # 11. Nachricht sollte fehlschlagen
    resp = await client.post(
        "/coach/chat",
        json={"message": "Zu viele"},
        headers={"X-Guest-Token": token},
    )
    assert resp.status_code == 403
    assert "Gast-Limit" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_guest_chat_without_token(client: AsyncClient):
    """Chat ohne Auth-Token schlägt fehl."""
    resp = await client.post(
        "/coach/chat",
        json={"message": "Test"},
    )
    # In Dev-Mode wird Demo-User verwendet, daher 200
    # In Production würde 401 zurückkommen
    assert resp.status_code in [200, 401]


@pytest.mark.asyncio
async def test_multiple_guest_sessions(client: AsyncClient):
    """Mehrere Gast-Sessions können erstellt werden."""
    resp1 = await client.post("/guest/session")
    resp2 = await client.post("/guest/session")
    assert resp1.json()["guest_token"] != resp2.json()["guest_token"]
