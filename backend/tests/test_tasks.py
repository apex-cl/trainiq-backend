import pytest
import httpx
from httpx import ASGITransport
from main import app


@pytest.mark.asyncio
async def test_generate_plan_enqueue(client, auth_headers):
    """Should enqueue training plan generation task."""
    resp = await client.post(
        "/tasks/generate-plan",
        json={"week_start": "2024-01-08"},
        headers=auth_headers,
    )
    assert resp.status_code in [200, 503]
    if resp.status_code == 200:
        data = resp.json()
        assert "task_id" in data
        assert "job_id" in data
        assert data["status"] == "enqueued"


@pytest.mark.asyncio
async def test_generate_plan_missing_week_start(client, auth_headers):
    """Should reject missing week_start."""
    resp = await client.post(
        "/tasks/generate-plan",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sync_strava_enqueue(client, auth_headers):
    """Should enqueue Strava sync task."""
    resp = await client.post(
        "/tasks/sync-strava",
        headers=auth_headers,
    )
    assert resp.status_code in [200, 503]
    if resp.status_code == 200:
        data = resp.json()
        assert "task_id" in data
        assert "job_id" in data
        assert data["status"] == "enqueued"


@pytest.mark.asyncio
async def test_task_status_sse_requires_auth(client, auth_headers):
    """Non-owner task_id returns 403 (access control check)."""
    # Task belongs to a different user — must be rejected
    resp = await client.get(
        "/tasks/status/plan_gen:00000000-0000-0000-0000-000000000099:2024-01-08",
        headers=auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_task_status_sse_unauthorized_task_id(client, auth_headers):
    """Non-owner task_id returns 403 regardless of whether it exists."""
    resp = await client.get(
        "/tasks/status/strava_sync:00000000-0000-0000-0000-000000000099",
        headers=auth_headers,
    )
    assert resp.status_code == 403
