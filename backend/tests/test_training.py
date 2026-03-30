import uuid
import pytest
from datetime import date, timedelta


@pytest.mark.asyncio
async def test_get_week_plan(client, auth_headers):
    resp = await client.get("/training/plan", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_week_plan_with_date(client, auth_headers):
    week_start = date.today() - timedelta(days=date.today().weekday())
    resp = await client.get(
        f"/training/plan?week={week_start.isoformat()}", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_day_plan_not_found(client, auth_headers):
    resp = await client.get("/training/plan/2099-01-01", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_complete_nonexistent_plan(client, auth_headers):
    fake_id = str(uuid.uuid4())
    resp = await client.post(f"/training/complete/{fake_id}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_skip_nonexistent_plan(client, auth_headers):
    fake_id = str(uuid.uuid4())
    resp = await client.post(f"/training/skip/{fake_id}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_complete_and_skip_plan(client, auth_headers, db):
    from app.models.training import TrainingPlan

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])

    plan = TrainingPlan(
        user_id=user_id,
        date=date.today(),
        sport="Laufen",
        workout_type="easy_run",
        duration_min=45,
        intensity_zone=2,
        status="planned",
    )
    db.add(plan)
    await db.commit()
    plan_id = str(plan.id)

    resp = await client.post(f"/training/complete/{plan_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_skip_with_reason(client, auth_headers, db):
    from app.models.training import TrainingPlan

    me_resp = await client.get("/auth/me", headers=auth_headers)
    user_id = uuid.UUID(me_resp.json()["id"])

    plan = TrainingPlan(
        user_id=user_id,
        date=date.today() + timedelta(days=1),
        sport="Schwimmen",
        workout_type="swim",
        duration_min=60,
        status="planned",
    )
    db.add(plan)
    await db.commit()
    plan_id = str(plan.id)

    resp = await client.post(
        f"/training/skip/{plan_id}",
        json={"reason": "Verletzung"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"
