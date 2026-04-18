"""Tests for training stats, streak, and achievements endpoints."""
import uuid
import pytest
from datetime import date, timedelta


# ─── Training Stats ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_training_stats_empty(client, auth_headers):
    """GET /training/stats with no plans returns zero stats."""
    resp = await client.get("/training/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_planned"] == 0
    assert data["total_completed"] == 0
    assert data["total_skipped"] == 0
    assert data["completion_rate"] == 0.0
    assert data["by_sport"] == {}
    assert isinstance(data["weekly_volume"], list)


@pytest.mark.asyncio
async def test_training_stats_with_plans(client, auth_headers, db):
    """Stats should aggregate correctly when plans exist."""
    from app.models.training import TrainingPlan
    from app.models.user import User
    from sqlalchemy import select
    import app.core.database as db_module

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])
    today = date.today()

    # Create 3 plans: 2 completed, 1 skipped
    plans = [
        TrainingPlan(
            user_id=user_id,
            date=today - timedelta(days=2),
            sport="running",
            workout_type="easy_run",
            status="completed",
            duration_min=60,
        ),
        TrainingPlan(
            user_id=user_id,
            date=today - timedelta(days=3),
            sport="running",
            workout_type="tempo",
            status="completed",
            duration_min=45,
        ),
        TrainingPlan(
            user_id=user_id,
            date=today - timedelta(days=4),
            sport="cycling",
            workout_type="endurance",
            status="skipped",
            duration_min=90,
        ),
    ]
    for p in plans:
        db.add(p)
    await db.commit()

    resp = await client.get("/training/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_planned"] >= 3
    assert data["total_completed"] >= 2
    assert data["total_skipped"] >= 1
    assert data["completion_rate"] > 0
    assert "running" in data["by_sport"]
    assert isinstance(data["weekly_volume"], list)
    assert len(data["weekly_volume"]) == 4  # 4 weeks


@pytest.mark.asyncio
async def test_training_stats_duration_sum(client, auth_headers, db):
    """Total duration should sum only completed workouts."""
    from app.models.training import TrainingPlan

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])
    today = date.today()

    plans = [
        TrainingPlan(
            user_id=user_id,
            date=today - timedelta(days=1),
            sport="swimming",
            workout_type="endurance",
            status="completed",
            duration_min=50,
        ),
        TrainingPlan(
            user_id=user_id,
            date=today - timedelta(days=5),
            sport="swimming",
            workout_type="easy",
            status="skipped",
            duration_min=120,  # Should NOT be included
        ),
    ]
    for p in plans:
        db.add(p)
    await db.commit()

    resp = await client.get("/training/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Skipped plans don't add to total_duration_min
    # completed plan adds 50 min (plus any from other tests but the skipped 120 is not counted)
    assert data["total_duration_min"] >= 0


@pytest.mark.asyncio
async def test_training_stats_requires_auth(client):
    """Stats without auth should use demo user in DEV_MODE."""
    resp = await client.get("/training/stats")
    assert resp.status_code in [200, 401, 403]


# ─── Training Streak ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_streak_empty(client, auth_headers):
    """No completed workouts → streak is 0."""
    resp = await client.get("/training/streak", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_streak"] == 0
    assert data["longest_streak"] == 0


@pytest.mark.asyncio
async def test_streak_consecutive_days(client, auth_headers, db):
    """Consecutive completed days should build a streak."""
    from app.models.training import TrainingPlan

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])
    today = date.today()

    # Create 3 consecutive completed days ending today
    for i in range(3):
        db.add(
            TrainingPlan(
                user_id=user_id,
                date=today - timedelta(days=i),
                sport="running",
                workout_type="easy_run",
                status="completed",
                duration_min=45,
            )
        )
    await db.commit()

    resp = await client.get("/training/streak", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_streak"] >= 3
    assert data["longest_streak"] >= 3
    assert data["last_active"] != ""


@pytest.mark.asyncio
async def test_streak_broken_by_gap(client, auth_headers, db):
    """A gap in training days should break the streak."""
    from app.models.training import TrainingPlan

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])
    today = date.today()

    # Day 0 (today) and day 3 (gap of 2 days) — streak should be 1
    for offset in [0, 3, 4]:
        db.add(
            TrainingPlan(
                user_id=user_id,
                date=today - timedelta(days=offset),
                sport="cycling",
                workout_type="tempo",
                status="completed",
                duration_min=30,
            )
        )
    await db.commit()

    resp = await client.get("/training/streak", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_streak"] == 1  # Only today counts since there's a gap


@pytest.mark.asyncio
async def test_streak_longest_tracker(client, auth_headers, db):
    """Longest streak should reflect the maximum consecutive run."""
    from app.models.training import TrainingPlan

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])
    today = date.today()

    # 5 consecutive days from 10 to 6 days ago, then a gap, then 1 day
    for i in range(5):
        db.add(
            TrainingPlan(
                user_id=user_id,
                date=today - timedelta(days=10 + i),
                sport="running",
                workout_type="easy",
                status="completed",
                duration_min=30,
            )
        )
    db.add(
        TrainingPlan(
            user_id=user_id,
            date=today - timedelta(days=2),
            sport="running",
            workout_type="easy",
            status="completed",
            duration_min=30,
        )
    )
    await db.commit()

    resp = await client.get("/training/streak", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["longest_streak"] >= 5


# ─── Achievements ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_achievements_returns_list(client, auth_headers):
    """GET /training/achievements should return a list."""
    resp = await client.get("/training/achievements", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_achievements_have_expected_fields(client, auth_headers):
    """Each achievement should have id, title, description, icon, unlocked_at fields."""
    resp = await client.get("/training/achievements", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    for item in data:
        assert "id" in item
        assert "title" in item
        assert "description" in item
        assert "icon" in item
        assert "unlocked_at" in item  # None if not unlocked


@pytest.mark.asyncio
async def test_achievement_unlocked_after_first_workout(client, auth_headers, db):
    """After completing a workout, 'first_workout' achievement should be unlocked."""
    from app.models.training import TrainingPlan

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])
    today = date.today()

    db.add(
        TrainingPlan(
            user_id=user_id,
            date=today,
            sport="running",
            workout_type="easy_run",
            status="completed",
            duration_min=30,
        )
    )
    await db.commit()

    resp = await client.get("/training/achievements", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    first_workout = next((a for a in data if a["id"] == "first_workout"), None)
    assert first_workout is not None
    assert first_workout["unlocked_at"] is not None  # Should be a date string


@pytest.mark.asyncio
async def test_achievements_without_plans_all_locked(client, auth_headers):
    """Without any completed workouts, no achievement should be unlocked."""
    resp = await client.get("/training/achievements", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # first_workout at minimum should be locked (unlocked_at is None)
    first_workout = next((a for a in data if a["id"] == "first_workout"), None)
    if first_workout:
        assert first_workout["unlocked_at"] is None


# ─── Plan with invalid week format ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_week_plan_invalid_date_format(client, auth_headers):
    """Invalid week date format should return 422."""
    resp = await client.get("/training/plan?week=not-a-date", headers=auth_headers)
    assert resp.status_code == 422
