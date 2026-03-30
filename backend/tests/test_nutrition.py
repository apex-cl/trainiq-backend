import uuid
import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_nutrition_today_empty(client, auth_headers):
    resp = await client.get("/nutrition/today", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "logs" in data
    assert "totals" in data
    assert isinstance(data["logs"], list)
    assert data["totals"]["calories"] == 0


@pytest.mark.asyncio
async def test_nutrition_today_with_data(client, auth_headers, db):
    from app.models.nutrition import NutritionLog

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])

    log = NutritionLog(
        user_id=user_id,
        meal_type="Mittagessen",
        calories=500.0,
        protein_g=30.0,
        carbs_g=60.0,
        fat_g=15.0,
        analysis_raw={"meal_name": "Huhn mit Reis"},
    )
    db.add(log)
    await db.commit()

    resp = await client.get("/nutrition/today", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["logs"]) >= 1
    assert data["totals"]["calories"] >= 500.0


@pytest.mark.asyncio
async def test_nutrition_gaps(client, auth_headers):
    resp = await client.get("/nutrition/gaps", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_nutrition_targets(client, auth_headers):
    """Should return personalized nutrition targets."""
    resp = await client.get("/nutrition/targets", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "calories" in data
    assert "protein_g" in data
    assert data["calories"] > 0


@pytest.mark.asyncio
async def test_nutrition_history_default(client, auth_headers):
    """Should return a list (possibly empty) of daily summaries."""
    resp = await client.get("/nutrition/history", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_nutrition_history_custom_days(client, auth_headers):
    """Should accept custom days parameter."""
    resp = await client.get("/nutrition/history?days=14", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_delete_meal(client, auth_headers, db):
    """Should delete a specific meal and return 200."""
    from app.models.nutrition import NutritionLog

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])

    log = NutritionLog(
        user_id=user_id,
        meal_type="Frühstück",
        calories=300.0,
        protein_g=15.0,
        carbs_g=40.0,
        fat_g=8.0,
        analysis_raw={"meal_name": "Haferflocken"},
    )
    db.add(log)
    await db.commit()

    resp = await client.delete(f"/nutrition/meal/{log.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verify it's gone
    check = await client.get("/nutrition/today", headers=auth_headers)
    ids = [l["id"] for l in check.json()["logs"]]
    assert str(log.id) not in ids


@pytest.mark.asyncio
async def test_delete_meal_not_found(client, auth_headers):
    """Deleting nonexistent meal should return 404."""
    import uuid as uuid_module
    fake_id = str(uuid_module.uuid4())
    resp = await client.delete(f"/nutrition/meal/{fake_id}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_nutrition_targets_with_goals(client, auth_headers, db):
    """With user goals, targets should be sport-specific."""
    from app.models.training import UserGoal

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])

    goal = UserGoal(
        user_id=user_id,
        sport="running",
        goal_description="Marathon",
        weekly_hours=10,
        fitness_level="advanced",
    )
    db.add(goal)
    await db.commit()

    resp = await client.get("/nutrition/targets", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["calories"] > 2000  # Athletes need more calories
