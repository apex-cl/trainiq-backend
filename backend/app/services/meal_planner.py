"""Wöchentlicher Speiseplan mit Rezepten via LLM."""

import json
import httpx
from loguru import logger
from app.core.config import settings


class MealPlanner:
    """Erstellt vollständige Wochenspeisepläne mit Rezepten."""

    async def generate_weekly_plan(
        self,
        user_id: str,
        kalorien_ziel: int,
        protein_ziel_g: int,
        training_context: str = "",
    ) -> str:
        """Generiert einen 7-Tage Speiseplan mit Frühstück, Mittagessen, Abendessen und Snacks inkl. Rezepten."""

        training_section = (
            f"\nTrainingsbelastung dieser Woche:\n{training_context}"
            if training_context
            else ""
        )

        prompt = f"""Erstelle einen vollständigen 7-Tage-Speiseplan für einen Ausdauersportler.

Tagesziel: {kalorien_ziel} kcal, {protein_ziel_g}g Protein{training_section}

Anforderungen:
- Für jeden Tag: Frühstück, Mittagessen, Abendessen, 1-2 Snacks
- Für jede Hauptmahlzeit: vollständiges Rezept (Zutaten + Zubereitung in 3-5 Schritten)
- Nahrwerte pro Mahlzeit (kcal, Protein, Kohlenhydrate, Fett)
- Sportlerfreundlich: viel Protein, komplexe Kohlenhydrate, gesunde Fette
- Abwechslungsreich, alltagstauglich, keine exotischen Zutaten
- Auf Deutsch

Format (Markdown):
## Montag (ca. {kalorien_ziel} kcal)

### Frühstück — Overnight Oats mit Beeren (420 kcal | 28g P | 55g KH | 12g F)
**Zutaten (1 Portion):** 80g Haferflocken, 200ml Milch, ...
**Zubereitung:**
1. ...
2. ...

### Mittagessen — ...
...

### Abendessen — ...
...

### Snack — ...

---
## Dienstag
...

Erstelle alle 7 Tage vollständig."""

        try:
            if not settings.active_llm_api_key:
                raise RuntimeError("LLM nicht konfiguriert")

            headers = {
                "Authorization": f"Bearer {settings.active_llm_api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 4096,
                "temperature": 0.7,
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{settings.llm_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                msg = data["choices"][0]["message"]
                return (msg.get("content") or msg.get("reasoning") or "").strip()

        except Exception as e:
            logger.error(f"Meal plan generation failed | user={user_id} | error={e}")
            return f"Fehler beim Erstellen des Speiseplans: {e}"

    async def analyze_nutrient_gaps(
        self,
        avg_calories: float,
        avg_protein_g: float,
        avg_carbs_g: float,
        avg_fat_g: float,
        target_calories: int = 2200,
        target_protein_g: int = 150,
    ) -> str:
        """Analysiert Nährstofflücken und gibt konkrete Empfehlungen."""

        prompt = f"""Analysiere die Ernährung eines Ausdauersportlers und identifiziere Mängel.

Ist-Werte (täglicher Durchschnitt):
- Kalorien: {round(avg_calories)} kcal (Ziel: {target_calories} kcal)
- Protein: {round(avg_protein_g)}g (Ziel: {target_protein_g}g)
- Kohlenhydrate: {round(avg_carbs_g)}g
- Fett: {round(avg_fat_g)}g

Erstelle eine strukturierte Analyse auf Deutsch:
1. **Kritische Mängel** (rot): Was fehlt dringend und warum ist es für Sportler wichtig
2. **Optimierungsbedarf** (gelb): Was könnte besser sein
3. **Stärken** (grün): Was gut läuft
4. **Konkrete Lebensmittel-Empfehlungen**: Welche 5-7 Lebensmittel sollte der Nutzer täglich ergänzen
5. **Schnelle Fixes**: 3 einfache Mahlzeiten die sofort helfen

Antworte konkret mit echten Zahlen und Lebensmitteln."""

        try:
            if not settings.active_llm_api_key:
                return "Analyse nicht verfügbar"

            headers = {
                "Authorization": f"Bearer {settings.active_llm_api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1024,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{settings.llm_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                msg = data["choices"][0]["message"]
                return (msg.get("content") or msg.get("reasoning") or "").strip()

        except Exception as e:
            logger.error(f"Nutrient gap analysis failed | error={e}")
            return f"Analyse fehlgeschlagen: {e}"
