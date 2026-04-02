"""Tests for metrics week endpoint and additional health metric scenarios."""
import uuid
import pytest
from datetime import datetime, timedelta, timezone


# ─── Metrics Week ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_week_empty(client, auth_headers):
    """GET /metrics/week with no data returns empty list."""
    resp = await client.get("/metrics/week", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_week_with_single_day(client, auth_headers, db):
    """GET /metrics/week returns one entry per day."""
    from app.models.metrics import HealthMetric

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])

    # Add 2 entries for the same day (only newest should appear)
    now = datetime.now(timezone.utc)
    for offset_minutes in [0, 60]:
        db.add(
            HealthMetric(
                user_id=user_id,
                recorded_at=now - timedelta(minutes=offset_minutes),
                hrv=42.0 + offset_minutes,
                resting_hr=60,
                source="test",
            )
        )
    await db.commit()

    resp = await client.get("/metrics/week", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # Entries are deduplicated by day
    dates = [entry["date"] for entry in data]
    assert len(dates) == len(set(dates))


@pytest.mark.asyncio
async def test_get_week_multiple_days(client, auth_headers, db):
    """GET /metrics/week returns entries for different days."""
    from app.models.metrics import HealthMetric

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])

    now = datetime.now(timezone.utc)
    for days_ago in [1, 2, 3]:
        db.add(
            HealthMetric(
                user_id=user_id,
                recorded_at=now - timedelta(days=days_ago),
                hrv=40.0,
                resting_hr=62,
                sleep_duration_min=420,
                source="garmin",
            )
        )
    await db.commit()

    resp = await client.get("/metrics/week", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 3
    for entry in data:
        assert "date" in entry
        assert "hrv" in entry
        assert "source" in entry


@pytest.mark.asyncio
async def test_get_week_respects_7_day_window(client, auth_headers, db):
    """GET /metrics/week should not include entries older than 7 days."""
    from app.models.metrics import HealthMetric

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])

    now = datetime.now(timezone.utc)
    # Add entry 10 days ago (outside window)
    db.add(
        HealthMetric(
            user_id=user_id,
            recorded_at=now - timedelta(days=10),
            hrv=55.0,
            resting_hr=58,
            source="old_entry",
        )
    )
    await db.commit()

    resp = await client.get("/metrics/week", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    sources = [entry.get("source") for entry in data]
    assert "old_entry" not in sources


@pytest.mark.asyncio
async def test_get_week_newest_entry_per_day(client, auth_headers, db):
    """Only the newest entry per day should appear, newest first."""
    from app.models.metrics import HealthMetric

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])

    now = datetime.now(timezone.utc)
    two_days_ago = now.replace(hour=6, minute=0) - timedelta(days=2)

    # Two entries on the same day: morning and evening
    db.add(
        HealthMetric(
            user_id=user_id,
            recorded_at=two_days_ago,
            hrv=30.0,
            source="morning",
        )
    )
    db.add(
        HealthMetric(
            user_id=user_id,
            recorded_at=two_days_ago + timedelta(hours=12),
            hrv=50.0,
            source="evening",
        )
    )
    await db.commit()

    resp = await client.get("/metrics/week", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    target_date = two_days_ago.date().isoformat()
    day_entries = [e for e in data if e["date"] == target_date]
    assert len(day_entries) == 1
    assert day_entries[0]["source"] == "evening"
    assert day_entries[0]["hrv"] == 50.0


# ─── Wellbeing edge cases ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wellbeing_requires_auth(client):
    """POST /metrics/wellbeing without auth should use demo user (DEV_MODE)."""
    resp = await client.post(
        "/metrics/wellbeing",
        json={"fatigue_score": 5, "mood_score": 5},
    )
    assert resp.status_code in [200, 401, 403]


@pytest.mark.asyncio
async def test_wellbeing_boundary_values(client, auth_headers):
    """Score values at boundary (1 and 10) should be accepted."""
    for low, high in [(1, 10), (10, 1)]:
        resp = await client.post(
            "/metrics/wellbeing",
            json={"fatigue_score": low, "mood_score": high},
            headers=auth_headers,
        )
        assert resp.status_code == 200


# ─── Recovery endpoint ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recovery_requires_auth(client):
    """GET /metrics/recovery uses demo user in DEV_MODE."""
    resp = await client.get("/metrics/recovery")
    assert resp.status_code in [200, 401, 403]


@pytest.mark.asyncio
async def test_recovery_response_fields(client, auth_headers):
    """Recovery response should contain score and component fields."""
    resp = await client.get("/metrics/recovery", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "score" in data
    assert "label" in data
