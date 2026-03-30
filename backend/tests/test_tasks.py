import pytest


@pytest.mark.asyncio
async def test_generate_plan_enqueue(client, auth_headers):
    """Should enqueue training plan generation task."""
    resp = await client.post(
        "/tasks/generate-plan",
        json={"week_start": "2024-01-08"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
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
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert "job_id" in data
    assert data["status"] == "enqueued"


@pytest.mark.asyncio
async def test_task_status_sse_requires_auth(client):
    """Should require authentication for SSE status endpoint."""
    resp = await client.get("/tasks/status/test-task-id")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_task_status_sse_unauthorized_task_id(client, auth_headers):
    """Should return stream even for non-existent task (user owns nothing)."""
    resp = await client.get(
        "/tasks/status/nonexistent-task-id",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"
