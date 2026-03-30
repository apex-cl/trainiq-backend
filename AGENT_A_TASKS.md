# AGENT A — Backend: Tests reparieren + Code-Bugs fixen + Fehlende Endpoints

> **Priorität: HOCH** — Viele Tests sind aktuell BROKEN wegen falschen Assertions und Code-Bugs.
> **Arbeitsverzeichnis:** `/Users/abu/Projekt/trainiq/backend/`
> **Du implementierst alles selbst. Keine halben Sachen. Keine TODOs.**

---

## KRITISCHE BUGS ZUM FIXEN

### Bug A-FIX-1 — `user.py`: Doppelter Validator

**Datei:** `/Users/abu/Projekt/trainiq/backend/app/api/routes/user.py`

Die Klasse `GoalsRequest` hat `validate_weekly_hours` **zweimal** definiert (Zeile 38-43 und 45-50). Python überschreibt die erste Definition. Außerdem hatte die Klasse zuvor schon einen doppelten Block. Der Code muss sauber sein.

**Ersetze die gesamte GoalsRequest-Klasse** (aktuell Zeilen 14-50) mit:

```python
ALLOWED_SPORTS = {"running", "cycling", "swimming", "triathlon"}
ALLOWED_LEVELS = {"beginner", "intermediate", "advanced"}


class GoalsRequest(BaseModel):
    sport: str
    goal_description: str
    target_date: str | None = None
    weekly_hours: int | None = None
    fitness_level: str | None = None

    @field_validator("sport")
    @classmethod
    def validate_sport(cls, v: str) -> str:
        if v not in ALLOWED_SPORTS:
            raise ValueError(f"Sport muss einer von {ALLOWED_SPORTS} sein")
        return v

    @field_validator("fitness_level")
    @classmethod
    def validate_fitness_level(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_LEVELS:
            raise ValueError(f"Fitnesslevel muss einer von {ALLOWED_LEVELS} sein")
        return v

    @field_validator("weekly_hours")
    @classmethod
    def validate_weekly_hours(cls, v: int | None) -> int | None:
        if v is not None and (v < 1 or v > 30):
            raise ValueError("Wochenstunden müssen zwischen 1 und 30 liegen")
        return v
```

---

## BROKEN TESTS REPARIEREN

### Test A-TEST-1 — `test_auth.py`: Register-Assertions falsch

**Datei:** `/Users/abu/Projekt/trainiq/backend/tests/test_auth.py`

`test_register_success` assertiert `data["email"]`, `data["name"]`, `data["id"]` — aber der Register-Endpoint gibt jetzt `access_token`, `token_type`, `user` zurück. Der Test schlägt fehl weil `data["email"]` nicht existiert.

**Ersetze `test_register_success`** (Zeilen 5-19):

```python
@pytest.mark.asyncio
async def test_register_success(client):
    resp = await client.post(
        "/auth/register",
        json={
            "email": "newuser@test.com",
            "password": "secure1234",
            "name": "New User",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "newuser@test.com"
    assert data["user"]["name"] == "New User"
    assert "id" in data["user"]
```

---

### Test A-TEST-2 — `test_auth.py`: Fehlende Tests

Füge am Ende von `test_auth.py` hinzu:

```python
@pytest.mark.asyncio
async def test_register_returns_token(client):
    """Register should return a token directly — no separate login needed."""
    email = f"direct_{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/auth/register",
        json={"email": email, "password": "test1234", "name": "Direct User"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    # Token should be usable immediately
    token = data["access_token"]
    me_resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == email


@pytest.mark.asyncio
async def test_me_without_token_dev_mode_returns_demo(client):
    """In dev mode, unauthenticated requests should return demo user."""
    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "demo@trainiq.app"
```

---

### Test A-TEST-3 — `test_user.py`: Sport-Werte sind invalid

**Datei:** `/Users/abu/Projekt/trainiq/backend/tests/test_user.py`

Der Validator erlaubt nur `running/cycling/swimming/triathlon`, aber die Tests senden `"Laufen"`, `"Radfahren"`, `"Schwimmen"` (Deutsch). Das führt zu HTTP 422.

**Ersetze die gesamte Datei** mit korrekten Werten:

```python
import pytest


@pytest.mark.asyncio
async def test_create_goal(client, auth_headers):
    resp = await client.post(
        "/user/goals",
        json={
            "sport": "running",
            "goal_description": "Marathon unter 4 Stunden",
            "target_date": "2025-12-31",
            "weekly_hours": 6,
            "fitness_level": "advanced",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sport"] == "running"
    assert data["goal_description"] == "Marathon unter 4 Stunden"
    assert data["weekly_hours"] == 6


@pytest.mark.asyncio
async def test_upsert_goal(client, auth_headers):
    payload1 = {
        "sport": "cycling",
        "goal_description": "100km Tour",
        "weekly_hours": 4,
    }
    await client.post("/user/goals", json=payload1, headers=auth_headers)

    payload2 = {
        "sport": "cycling",
        "goal_description": "200km Tour",
        "weekly_hours": 8,
    }
    resp = await client.post("/user/goals", json=payload2, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["goal_description"] == "200km Tour"
    assert data["weekly_hours"] == 8


@pytest.mark.asyncio
async def test_get_goals_empty(client, auth_headers):
    resp = await client.get("/user/goals", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_goals_with_data(client, auth_headers):
    await client.post(
        "/user/goals",
        json={"sport": "swimming", "goal_description": "2km Kraul am Stück"},
        headers=auth_headers,
    )
    resp = await client.get("/user/goals", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(g["sport"] == "swimming" for g in data)


@pytest.mark.asyncio
async def test_get_profile(client, auth_headers):
    resp = await client.get("/user/profile", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "email" in data
    assert "name" in data
    assert "goals" in data
    assert isinstance(data["goals"], list)


@pytest.mark.asyncio
async def test_goal_invalid_sport(client, auth_headers):
    """Should reject unknown/German sport names."""
    resp = await client.post(
        "/user/goals",
        json={"sport": "Laufen", "goal_description": "Test"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_goal_invalid_weekly_hours(client, auth_headers):
    """Should reject out-of-range weekly hours."""
    resp = await client.post(
        "/user/goals",
        json={"sport": "running", "goal_description": "Test", "weekly_hours": 50},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_account(client):
    """Delete account should remove user and return 200."""
    import uuid
    email = f"del_{uuid.uuid4().hex[:8]}@test.com"
    reg_resp = await client.post(
        "/auth/register",
        json={"email": email, "password": "test1234", "name": "To Delete"},
    )
    token = reg_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.delete("/user/account", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    # After deletion, token should not work
    me_resp = await client.get("/auth/me", headers=headers)
    assert me_resp.status_code in [401, 404]
```

---

### Test A-TEST-4 — `test_nutrition.py`: Fehlende Tests

**Datei:** `/Users/abu/Projekt/trainiq/backend/tests/test_nutrition.py`

Füge am Ende hinzu:

```python
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
async def test_nutrition_targets_with_goals(client, auth_headers, db):
    """With user goals, targets should be sport-specific."""
    from app.models.training import UserGoal
    import uuid

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
```

---

### Test A-TEST-5 — `conftest.py`: auth_headers Fixture reparieren

**Datei:** `/Users/abu/Projekt/trainiq/backend/tests/conftest.py`

Die `auth_headers` Fixture macht aktuell Register + dann separately Login. Seit Register jetzt direkt ein Token zurückgibt, kann der Login-Schritt entfallen. Aber das aktuelle Pattern funktioniert noch (Login gibt auch Token zurück), also KEINE Änderung nötig — ABER: stelle sicher dass die Fixture den Token aus Login nimmt (nicht Register), damit Tests die "Register gibt Token zurück" testen können isoliert bleiben.

**Prüfe** Zeile 120-124 — wenn es schon so ist, keine Änderung. Wenn `resp.json()["access_token"]` fehlschlägt, ist Login kaputt. Schreibe einen Smoke-Test:

Füge in `conftest.py` nach den Importen einen Kommentar hinzu:
```python
# NOTE: conftest always uses /auth/login for auth_headers fixture
# Register tests should create separate users and use the returned token directly
```

---

### Test A-TEST-6 — `test_watch.py`: Fehlende Tests + Verbesserungen

**Datei:** `/Users/abu/Projekt/trainiq/backend/tests/test_watch.py`

Füge am Ende hinzu:

```python
@pytest.mark.asyncio
async def test_watch_manual_invalid_hrv(client, auth_headers):
    """Should reject invalid HRV values."""
    resp = await client.post(
        "/watch/manual",
        json={"hrv": 500, "resting_hr": 60},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_strava_connect_requires_config(client, auth_headers):
    """Strava connect returns 503 when no client ID configured."""
    resp = await client.get("/watch/strava/connect", headers=auth_headers)
    # Either redirects (302) or returns unavailable (503) — both valid
    assert resp.status_code in [200, 302, 503]
```

---

## PYTEST KONFIGURATION EINRICHTEN

### A-PYTEST-1 — `pytest.ini` erstellen

**Neue Datei:** `/Users/abu/Projekt/trainiq/backend/pytest.ini`

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

### A-PYTEST-2 — Test Run Script erstellen

**Neue Datei:** `/Users/abu/Projekt/trainiq/backend/run_tests.sh`

```bash
#!/bin/bash
set -e

echo "=== TrainIQ Backend Tests ==="
echo ""

# Install test dependencies if needed
pip install pytest pytest-asyncio httpx aiosqlite --quiet

# Run tests
python -m pytest tests/ -v --tb=short 2>&1

echo ""
echo "=== Tests abgeschlossen ==="
```

Mach die Datei ausführbar (mental — der Agent schreibt den Inhalt, chmod muss manuell):

### A-PYTEST-3 — `pyproject.toml` erstellen (Alternative zu pytest.ini)

**Neue Datei:** `/Users/abu/Projekt/trainiq/backend/pyproject.toml`

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

## ABSCHLUSSKONTROLLE FÜR AGENT A

Nach allen Änderungen müssen diese Tests **grün** sein:
- `test_register_success` — prüft `access_token` + `user.email`
- `test_create_goal` — sendet `"running"` (nicht `"Laufen"`)
- `test_goal_invalid_sport` — 422 für `"Laufen"`
- `test_delete_account` — 200 + token danach ungültig
- `test_nutrition_targets` — Endpoint existiert und gibt Daten zurück
- `test_nutrition_history_default` — Endpoint existiert und gibt Liste zurück
- `user.py` hat KEINEN doppelten Validator mehr

**Führe zum Schluss aus:**
```bash
cd /Users/abu/Projekt/trainiq/backend
python -m pytest tests/ -v --tb=short
```

Und zeige das Ergebnis im Terminal. Repariere alle fehlschlagenden Tests.
