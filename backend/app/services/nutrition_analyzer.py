import base64
import json
import httpx
from loguru import logger
from app.core.config import settings


class NutritionAnalyzer:
    """Analyzes food photos and calculates nutritional values via LLM."""

    ANALYSIS_PROMPT = """Analysiere dieses Essensfoto. Schätze die Nährwerte so genau wie möglich.
Antworte NUR mit einem JSON-Objekt, ohne Markdown, ohne Code-Blöcke:
{
  "meal_name": "Beschreibung des Gerichts",
  "calories": 450.0,
  "protein_g": 25.0,
  "carbs_g": 55.0,
  "fat_g": 12.0,
  "portion_notes": "Geschätzte Portionsgröße",
  "confidence": "high"
}

confidence Werte: "high", "medium", "low"
Verwende Dezimalpunkte, keine Kommas."""

    DEFAULT_TARGETS = {
        "calories": 2000.0,
        "protein_g": 150.0,
        "carbs_g": 200.0,
        "fat_g": 65.0,
    }

    @staticmethod
    def _detect_mime_type(image_bytes: bytes) -> str:
        """Erkennt MIME-Typ aus Magic-Bytes."""
        if image_bytes[:4] == b"\x89PNG":
            return "image/png"
        if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        # JPEG und GIF fallback
        return "image/jpeg"

    async def analyze_image(self, image_bytes: bytes, meal_type: str) -> dict:
        """Sendet Bild an Vision-LLM und analysiert Nährwerte."""
        if not settings.active_llm_api_key:
            raise RuntimeError("Kein LLM API-Key konfiguriert (LLM_API_KEY)")

        # Vision-Modell: explizit konfiguriert oder Fallback auf Standard-Modell
        vision_model = settings.llm_vision_model or settings.llm_model
        if not vision_model:
            raise RuntimeError("Kein LLM-Modell konfiguriert (LLM_MODEL)")

        logger.info(f"Analyzing nutrition image | meal_type={meal_type} | model={vision_model}")

        mime_type = self._detect_mime_type(image_bytes)
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        headers = {
            "Authorization": f"Bearer {settings.active_llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.ANALYSIS_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_b64}"
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 512,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.llm_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()

        # JSON aus Response parsen
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(text)
        return {
            "meal_name": data.get("meal_name", "Unbekanntes Gericht"),
            "calories": float(data.get("calories", 0)),
            "protein_g": float(data.get("protein_g", 0)),
            "carbs_g": float(data.get("carbs_g", 0)),
            "fat_g": float(data.get("fat_g", 0)),
            "portion_notes": data.get("portion_notes", ""),
            "confidence": data.get("confidence", "medium"),
        }

    async def get_daily_gaps(
        self,
        totals: dict,
        target_calories: int | None = None,
    ) -> list[dict]:
        """Berechnet fehlende Nährstoffe für heute."""
        targets = dict(self.DEFAULT_TARGETS)
        if target_calories:
            targets["calories"] = float(target_calories)

        current = {
            "calories": totals.get("calories", 0.0),
            "protein_g": totals.get("protein_g", 0.0),
            "carbs_g": totals.get("carbs_g", 0.0),
            "fat_g": totals.get("fat_g", 0.0),
        }

        recommendations = {
            "calories": "Kalorienreiche Snacks wie Nüsse, Avocado oder Vollkornbrot",
            "protein_g": "Proteinquellen: Hähnchen, Fisch, Eier, Quark oder Proteinshakes",
            "carbs_g": "Kohlenhydrate: Reis, Kartoffeln, Haferflocken oder Bananen",
            "fat_g": "Gesunde Fette: Olivenöl, Nüsse, Lachs oder Avocado",
        }

        nutrient_labels = {
            "calories": "Kalorien",
            "protein_g": "Protein",
            "carbs_g": "Kohlenhydrate",
            "fat_g": "Fett",
        }

        gaps = []
        for key, target in targets.items():
            curr = current[key]
            missing = max(0, target - curr)
            if missing > 0:
                gaps.append(
                    {
                        "nutrient": nutrient_labels[key],
                        "current": round(curr, 1),
                        "target": round(target, 1),
                        "missing": round(missing, 1),
                        "recommendation": recommendations[key],
                    }
                )
        return gaps
