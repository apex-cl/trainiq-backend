import pytest
from datetime import date, timedelta


@pytest.mark.asyncio
async def test_streak_no_completed(client, auth_headers):
    """No completed workouts → streak is 0."""
    resp = await client.get("/training/streak", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_streak"] == 0
    assert data["longest_streak"] == 0


@pytest.mark.asyncio
async def test_streak_with_completed(client, auth_headers, db):
    """Completed workouts on consecutive days should build a streak."""
    from app.models.training import TrainingPlan
    import uuid
    from sqlalchemy import select

    me = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me.json()["id"])

    today = date.today()
    for offset in range(3):
        d = today - timedelta(days=offset)
        existing = await db.execute(
            select(TrainingPlan).where(
                TrainingPlan.user_id == user_id,
                TrainingPlan.date == d,
            )
        )
        plan = existing.scalar_one_or_none()
        if not plan:
            plan = TrainingPlan(
                user_id=user_id,
                date=d,
                sport="running",
                workout_type="easy_run",
                duration_min=30,
                status="completed",
            )
            db.add(plan)
        else:
            plan.status = "completed"
    await db.commit()

    resp = await client.get("/training/streak", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_streak"] >= 3
    assert data["longest_streak"] >= 3


@pytest.mark.asyncio
async def test_achievements_empty(client, auth_headers):
    """No training data → all achievements locked."""
    resp = await client.get("/training/achievements", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 8
    assert all(a["unlocked_at"] is None for a in data)


@pytest.mark.asyncio
async def test_achievements_first_workout(client, auth_headers, db):
    """Completing one workout should unlock first_workout achievement."""
    from app.models.training import TrainingPlan
    import uuid

    me = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me.json()["id"])

    plan = TrainingPlan(
        user_id=user_id,
        date=date.today() - timedelta(days=5),
        sport="running",
        workout_type="easy_run",
        duration_min=40,
        status="completed",
    )
    db.add(plan)
    await db.commit()

    resp = await client.get("/training/achievements", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    first_workout = next(a for a in data if a["id"] == "first_workout")
    assert first_workout["unlocked_at"] is not None


@pytest.mark.asyncio
async def test_notifications_subscribe(client, auth_headers):
    """Subscribing to push notifications should return ok."""
    resp = await client.post(
        "/notifications/subscribe",
        json={
            "endpoint": "https://fcm.googleapis.com/fcm/send/test123",
            "keys": {"p256dh": "test_p256dh", "auth": "test_auth"},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_notifications_unsubscribe(client, auth_headers):
    """Unsubscribing from push notifications should return ok."""
    resp = await client.post(
        "/notifications/unsubscribe",
        json={"endpoint": "https://fcm.googleapis.com/fcm/send/test123"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
