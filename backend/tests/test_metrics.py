import uuid
import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_post_wellbeing_success(client, auth_headers):
    resp = await client.post(
        "/metrics/wellbeing",
        json={"fatigue_score": 5, "mood_score": 7},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["fatigue_score"] == 5
    assert data["mood_score"] == 7


@pytest.mark.asyncio
async def test_post_wellbeing_with_pain_notes(client, auth_headers):
    resp = await client.post(
        "/metrics/wellbeing",
        json={
            "fatigue_score": 3,
            "mood_score": 4,
            "pain_notes": "Leichte Knieschmerzen",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pain_notes"] == "Leichte Knieschmerzen"


@pytest.mark.asyncio
async def test_post_wellbeing_update(client, auth_headers):
    await client.post(
        "/metrics/wellbeing",
        json={"fatigue_score": 5, "mood_score": 5},
        headers=auth_headers,
    )
    resp = await client.post(
        "/metrics/wellbeing",
        json={"fatigue_score": 8, "mood_score": 9},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["fatigue_score"] == 8
    assert data["mood_score"] == 9


@pytest.mark.asyncio
async def test_post_wellbeing_validation_low(client, auth_headers):
    resp = await client.post(
        "/metrics/wellbeing",
        json={"fatigue_score": 0, "mood_score": 5},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_wellbeing_validation_high(client, auth_headers):
    resp = await client.post(
        "/metrics/wellbeing",
        json={"fatigue_score": 5, "mood_score": 11},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_today_no_data(client, auth_headers):
    resp = await client.get("/metrics/today", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "no_data"


@pytest.mark.asyncio
async def test_get_today_with_data(client, auth_headers, db):
    from app.models.metrics import HealthMetric

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])

    metric = HealthMetric(
        user_id=user_id,
        recorded_at=datetime.now(timezone.utc),
        hrv=45.0,
        resting_hr=60,
        sleep_duration_min=480,
        stress_score=30.0,
        source="test",
    )
    db.add(metric)
    await db.commit()

    resp = await client.get("/metrics/today", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["hrv"] == 45.0
    assert data["source"] == "test"


@pytest.mark.asyncio
async def test_get_week(client, auth_headers):
    resp = await client.get("/metrics/week", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_recovery(client, auth_headers, db):
    from app.models.metrics import HealthMetric

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])

    metric = HealthMetric(
        user_id=user_id,
        recorded_at=datetime.now(timezone.utc),
        hrv=55.0,
        resting_hr=55,
        sleep_duration_min=480,
        stress_score=25.0,
        source="test",
    )
    db.add(metric)
    await db.commit()

    resp = await client.get("/metrics/recovery", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "score" in data
    assert "label" in data
    assert 0 <= data["score"] <= 100


@pytest.mark.asyncio
async def test_get_recovery_no_data(client, auth_headers):
    resp = await client.get("/metrics/recovery", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 0
    assert data["label"] == "KEINE DATEN"
