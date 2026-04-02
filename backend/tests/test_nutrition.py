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


# ──────────────────────────────────────────────
# NutritionAnalyzer Unit-Tests
# ──────────────────────────────────────────────

class TestDetectMimeType:
    """Tests für _detect_mime_type (MIME-Erkennung via Magic-Bytes)."""

    def test_jpeg(self):
        from app.services.nutrition_analyzer import NutritionAnalyzer
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 20
        assert NutritionAnalyzer._detect_mime_type(jpeg) == "image/jpeg"

    def test_png(self):
        from app.services.nutrition_analyzer import NutritionAnalyzer
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        assert NutritionAnalyzer._detect_mime_type(png) == "image/png"

    def test_webp(self):
        from app.services.nutrition_analyzer import NutritionAnalyzer
        webp = b"RIFF\x10\x00\x00\x00WEBP" + b"\x00" * 20
        assert NutritionAnalyzer._detect_mime_type(webp) == "image/webp"

    def test_gif_falls_back_to_jpeg(self):
        from app.services.nutrition_analyzer import NutritionAnalyzer
        gif = b"GIF89a" + b"\x00" * 20
        # GIF has no dedicated type — falls back to jpeg (acceptable)
        result = NutritionAnalyzer._detect_mime_type(gif)
        assert result in ("image/jpeg", "image/gif")

    def test_riff_non_webp_falls_back_to_jpeg(self):
        from app.services.nutrition_analyzer import NutritionAnalyzer
        # RIFF but not WEBP
        riff_other = b"RIFF\x10\x00\x00\x00AVI " + b"\x00" * 20
        assert NutritionAnalyzer._detect_mime_type(riff_other) == "image/jpeg"


@pytest.mark.asyncio
async def test_analyze_image_no_api_key(monkeypatch):
    """Ohne API-Key muss eine RuntimeError geworfen werden."""
    from app.services.nutrition_analyzer import NutritionAnalyzer
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "llm_api_key", "")
    monkeypatch.setattr(cfg_module.settings, "nvidia_api_key", "")

    analyzer = NutritionAnalyzer()
    with pytest.raises(RuntimeError, match="API-Key"):
        await analyzer.analyze_image(b"\xff\xd8\xff" + b"\x00" * 10, "dinner")


@pytest.mark.asyncio
async def test_analyze_image_no_model(monkeypatch):
    """Ohne Modell-Name muss eine RuntimeError geworfen werden."""
    from app.services.nutrition_analyzer import NutritionAnalyzer
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(cfg_module.settings, "llm_vision_model", "")
    monkeypatch.setattr(cfg_module.settings, "llm_model", "")

    analyzer = NutritionAnalyzer()
    with pytest.raises(RuntimeError, match="Modell"):
        await analyzer.analyze_image(b"\xff\xd8\xff" + b"\x00" * 10, "dinner")


@pytest.mark.asyncio
async def test_analyze_image_uses_vision_model_when_set(monkeypatch):
    """Wenn LLM_VISION_MODEL gesetzt ist, muss dieses Modell verwendet werden."""
    import httpx
    from app.services.nutrition_analyzer import NutritionAnalyzer
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(cfg_module.settings, "llm_vision_model", "vision-model-v1")
    monkeypatch.setattr(cfg_module.settings, "llm_model", "default-model")
    monkeypatch.setattr(cfg_module.settings, "llm_base_url", "https://api.example.com/v1")

    captured = {}
    _req = httpx.Request("POST", "https://api.example.com/v1/chat/completions")

    async def mock_post(self_client, url, *, headers=None, json=None, **kwargs):
        captured["model"] = json["model"]
        captured["mime"] = json["messages"][0]["content"][1]["image_url"]["url"].split(";")[0].split(":")[1]
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "content": '{"meal_name":"Pizza","calories":750.0,"protein_g":30.0,"carbs_g":90.0,"fat_g":25.0,"portion_notes":"1 Stück","confidence":"high"}'
                    }
                }]
            },
            request=_req,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    analyzer = NutritionAnalyzer()
    result = await analyzer.analyze_image(b"\xff\xd8\xff" + b"\x00" * 10, "dinner")

    assert captured["model"] == "vision-model-v1"
    assert result["meal_name"] == "Pizza"
    assert result["calories"] == 750.0
    assert result["confidence"] == "high"


@pytest.mark.asyncio
async def test_analyze_image_fallback_to_llm_model(monkeypatch):
    """Ohne LLM_VISION_MODEL soll LLM_MODEL als Fallback benutzt werden."""
    import httpx
    from app.services.nutrition_analyzer import NutritionAnalyzer
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(cfg_module.settings, "llm_vision_model", "")
    monkeypatch.setattr(cfg_module.settings, "llm_model", "gpt-4o-mini")
    monkeypatch.setattr(cfg_module.settings, "llm_base_url", "https://api.example.com/v1")

    captured = {}
    _req = httpx.Request("POST", "https://api.example.com/v1/chat/completions")

    async def mock_post(self_client, url, *, headers=None, json=None, **kwargs):
        captured["model"] = json["model"]
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "content": '{"meal_name":"Salat","calories":200.0,"protein_g":8.0,"carbs_g":15.0,"fat_g":10.0,"portion_notes":"Große Schüssel","confidence":"medium"}'
                    }
                }]
            },
            request=_req,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    analyzer = NutritionAnalyzer()
    result = await analyzer.analyze_image(b"\xff\xd8\xff" + b"\x00" * 10, "lunch")

    assert captured["model"] == "gpt-4o-mini"
    assert result["meal_name"] == "Salat"
    assert result["calories"] == 200.0


@pytest.mark.asyncio
async def test_analyze_image_strips_markdown_codeblock(monkeypatch):
    """LLM-Antworten mit ```json ... ``` müssen korrekt geparst werden."""
    import httpx
    from app.services.nutrition_analyzer import NutritionAnalyzer
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(cfg_module.settings, "llm_vision_model", "test-model")
    monkeypatch.setattr(cfg_module.settings, "llm_base_url", "https://api.example.com/v1")

    wrapped = '```json\n{"meal_name":"Burger","calories":900.0,"protein_g":45.0,"carbs_g":80.0,"fat_g":40.0,"portion_notes":"mittel","confidence":"high"}\n```'
    _req = httpx.Request("POST", "https://api.example.com/v1/chat/completions")

    async def mock_post(self_client, url, *, headers=None, json=None, **kwargs):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": wrapped}}]},
            request=_req,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    analyzer = NutritionAnalyzer()
    result = await analyzer.analyze_image(b"\xff\xd8\xff" + b"\x00" * 10, "dinner")
    assert result["meal_name"] == "Burger"
    assert result["calories"] == 900.0


@pytest.mark.asyncio
async def test_analyze_image_png_sets_correct_mime(monkeypatch):
    """PNG-Bilder müssen image/png als MIME-Typ an die API senden."""
    import httpx
    from app.services.nutrition_analyzer import NutritionAnalyzer
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(cfg_module.settings, "llm_vision_model", "test-model")
    monkeypatch.setattr(cfg_module.settings, "llm_base_url", "https://api.example.com/v1")

    captured_mime = {}
    _req = httpx.Request("POST", "https://api.example.com/v1/chat/completions")

    async def mock_post(self_client, url, *, headers=None, json=None, **kwargs):
        url_field = json["messages"][0]["content"][1]["image_url"]["url"]
        captured_mime["mime"] = url_field.split(";base64,")[0].replace("data:", "")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"meal_name":"Müsli","calories":350.0,"protein_g":12.0,"carbs_g":60.0,"fat_g":8.0,"portion_notes":"Schüssel","confidence":"medium"}'}}]},
            request=_req,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    analyzer = NutritionAnalyzer()
    await analyzer.analyze_image(png_bytes, "breakfast")
    assert captured_mime["mime"] == "image/png"


# ──────────────────────────────────────────────
# Upload-Endpoint Integration-Tests
# ──────────────────────────────────────────────

# Minimales gültiges 1x1 JPEG (80 Bytes)
_MINIMAL_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9\x3d="
    b"\x82\x83\x84\x85\xff\xd9"
)


@pytest.mark.asyncio
async def test_upload_invalid_content_type(client, auth_headers):
    """Nicht-Bild Content-Type muss 400 zurückgeben."""
    resp = await client.post(
        "/nutrition/upload",
        headers=auth_headers,
        files={"file": ("test.txt", b"hello", "text/plain")},
        data={"meal_type": "dinner"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_too_large(client, auth_headers):
    """Dateien > 10 MB müssen 413 zurückgeben."""
    big = b"\xff\xd8\xff" + b"\x00" * (10 * 1024 * 1024 + 1)
    resp = await client.post(
        "/nutrition/upload",
        headers=auth_headers,
        files={"file": ("big.jpg", big, "image/jpeg")},
        data={"meal_type": "dinner"},
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_upload_invalid_magic_bytes(client, auth_headers):
    """Bild-Content-Type aber falsche Magic-Bytes müssen 400 zurückgeben."""
    resp = await client.post(
        "/nutrition/upload",
        headers=auth_headers,
        files={"file": ("fake.jpg", b"NOTANIMAGE", "image/jpeg")},
        data={"meal_type": "dinner"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_no_llm_key_returns_502(client, auth_headers, monkeypatch):
    """Wenn kein LLM-Key gesetzt ist, muss der Endpoint 502 zurückgeben."""
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "llm_api_key", "")
    monkeypatch.setattr(cfg_module.settings, "nvidia_api_key", "")

    resp = await client.post(
        "/nutrition/upload",
        headers=auth_headers,
        files={"file": ("meal.jpg", _MINIMAL_JPEG, "image/jpeg")},
        data={"meal_type": "lunch"},
    )
    assert resp.status_code == 502
    assert "fehlgeschlagen" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_success_with_mocked_llm(client, auth_headers, monkeypatch):
    """Erfolgreiches Upload mit gemockter LLM-Antwort."""
    from app.services import nutrition_analyzer as na_module
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "cloudinary_api_key", "")

    async def mock_analyze(self, image_bytes, meal_type):
        return {
            "meal_name": "Spaghetti Bolognese",
            "calories": 680.0,
            "protein_g": 35.0,
            "carbs_g": 85.0,
            "fat_g": 18.0,
            "portion_notes": "Große Portion",
            "confidence": "high",
        }

    monkeypatch.setattr(na_module.NutritionAnalyzer, "analyze_image", mock_analyze)

    resp = await client.post(
        "/nutrition/upload",
        headers=auth_headers,
        files={"file": ("pasta.jpg", _MINIMAL_JPEG, "image/jpeg")},
        data={"meal_type": "dinner"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["meal_name"] == "Spaghetti Bolognese"
    assert data["calories"] == 680.0
    assert data["protein_g"] == 35.0
    assert data["confidence"] == "high"
    assert "id" in data


@pytest.mark.asyncio
async def test_upload_different_images_give_different_results(client, auth_headers, monkeypatch):
    """Zwei verschiedene Bilder müssen unterschiedliche Ergebnisse liefern."""
    from app.services import nutrition_analyzer as na_module
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "cloudinary_api_key", "")

    results = [
        {"meal_name": "Apfel", "calories": 80.0, "protein_g": 0.4, "carbs_g": 21.0, "fat_g": 0.2, "portion_notes": "1 mittelgroß", "confidence": "high"},
        {"meal_name": "Schnitzel mit Pommes", "calories": 950.0, "protein_g": 55.0, "carbs_g": 70.0, "fat_g": 45.0, "portion_notes": "Restaurantportion", "confidence": "high"},
    ]
    call_count = [0]

    async def mock_analyze(self, image_bytes, meal_type):
        idx = call_count[0] % len(results)
        call_count[0] += 1
        return results[idx]

    monkeypatch.setattr(na_module.NutritionAnalyzer, "analyze_image", mock_analyze)

    resp1 = await client.post(
        "/nutrition/upload",
        headers=auth_headers,
        files={"file": ("apple.jpg", _MINIMAL_JPEG, "image/jpeg")},
        data={"meal_type": "snack"},
    )
    resp2 = await client.post(
        "/nutrition/upload",
        headers=auth_headers,
        files={"file": ("schnitzel.jpg", _MINIMAL_JPEG, "image/jpeg")},
        data={"meal_type": "dinner"},
    )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    d1, d2 = resp1.json(), resp2.json()

    assert d1["meal_name"] != d2["meal_name"]
    assert d1["calories"] != d2["calories"]
    assert d1["calories"] == 80.0
    assert d2["calories"] == 950.0


@pytest.mark.asyncio
async def test_guest_upload_success(client, guest_token, monkeypatch):
    """Gast kann Foto hochladen wenn Limit nicht erreicht."""
    from app.services import nutrition_analyzer as na_module
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "cloudinary_api_key", "")

    async def mock_analyze(self, image_bytes, meal_type):
        return {
            "meal_name": "Joghurt",
            "calories": 120.0,
            "protein_g": 8.0,
            "carbs_g": 14.0,
            "fat_g": 3.0,
            "portion_notes": "kleiner Becher",
            "confidence": "medium",
        }

    monkeypatch.setattr(na_module.NutritionAnalyzer, "analyze_image", mock_analyze)

    resp = await client.post(
        "/nutrition/upload",
        headers={"X-Guest-Token": guest_token},
        files={"file": ("yogurt.jpg", _MINIMAL_JPEG, "image/jpeg")},
        data={"meal_type": "breakfast"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["meal_name"] == "Joghurt"
    assert "photos_remaining" in data

