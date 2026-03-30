# PROMPT FÜR AGENT B — Full Implementation

Kopiere alles zwischen den Strichen in einen neuen Chat.

---

Du bist ein erfahrener Senior Software Engineer. Agent A hat die komplette Projektstruktur
aufgebaut. Deine Aufgabe ist es, alle Stub-Funktionen zu implementieren und das Projekt
vollständig zum Laufen zu bringen.

## PFLICHT: Lies zuerst diese Dateien

1. `/Users/abu/Projekt/app/BLUEPRINT.md` — Gesamtspezifikation, Design System, Regeln
2. `/Users/abu/Projekt/trainiq/` — Das von Agent A aufgebaute Projekt vollständig lesen

Lies ALLE existierenden Dateien bevor du anfängst. Ändere NICHTS an der Struktur —
implementiere nur was in den Stub-Dateien fehlt.

Das Projekt liegt in: `/Users/abu/Projekt/trainiq/`

---

## Deine Aufgaben (in dieser Reihenfolge)

### PHASE 1 — Backend Auth (zuerst, alles andere braucht es)

#### app/api/routes/auth.py — Vollständig implementieren

**POST /auth/register:**
- Body: `{email: str, name: str, password: str}`
- Validierung: Email-Format, Passwort min 8 Zeichen
- Password hashen mit `security.hash_password()`
- User in DB speichern
- Zurückgeben: `{id, email, name, created_at}`
- Fehler: 409 wenn Email schon existiert

**POST /auth/login:**
- Body: `{email: str, password: str}`
- User aus DB laden, Passwort prüfen mit `security.verify_password()`
- JWT Token erstellen mit `security.create_access_token({sub: user.id})`
- Zurückgeben: `{access_token: str, token_type: "bearer", user: {id, name, email}}`
- Fehler: 401 bei falschem Passwort

**GET /auth/me:**
- Requires: Bearer Token
- Zurückgeben: aktueller User aus DB

---

### PHASE 2 — Metriken (Coach braucht diese Daten)

#### app/api/routes/metrics.py — Vollständig implementieren

**POST /metrics/wellbeing:**
- Body: `{fatigue_score: int, mood_score: int, pain_notes: str | None}`
- In `daily_wellbeing` Tabelle speichern (UPSERT für heute)

**GET /metrics/today:**
- Neueste `health_metrics` Row für heute laden
- Falls leer: Dummy-Werte mit `source: "no_data"` zurückgeben
- Zurückgeben: `{hrv, resting_hr, sleep_duration_min, sleep_quality_score, stress_score, steps, source}`

**GET /metrics/week:**
- Letzte 7 Tage `health_metrics` laden
- Gruppiert nach Datum, jeweils neuester Eintrag pro Tag
- Zurückgeben: Array von täglichen Metriken

**GET /metrics/recovery:**
- Heute's Metriken laden
- `recovery_scorer.calculate_recovery_score()` aufrufen
- Zurückgeben: `{score: int, label: str, details: {...}}`
- Label: score >= 70 → "BEREIT", 40-69 → "VORSICHT", < 40 → "RUHEN"

#### app/services/recovery_scorer.py — Vollständig implementieren

```python
class RecoveryScorer:
    def calculate_recovery_score(self, metrics: dict, user_baseline: dict) -> dict:
        """
        Gewichtete Formel (aus wissenschaftlichem Paper):
        HRV:    35% — Vergleich zu User-Baseline (7-Tage-Durchschnitt)
        Schlaf: 25% — Optimal = 480 min (8 Stunden)
        Stress: 20% — Invertiert (niedriger Stress = besser)
        HR:     20% — Vergleich zu User-Ruhepuls-Baseline

        Rückgabe:
        {
          score: 0-100,
          label: "BEREIT" | "VORSICHT" | "RUHEN",
          hrv_component: float,
          sleep_component: float,
          stress_component: float,
          hr_component: float
        }
        """
```

Wenn keine Baseline vorhanden (neuer User): Standardwerte nutzen (HRV: 40, Sleep: 420, Stress: 40, HR: 65).

---

### PHASE 3 — Coach Agent (Herzstück)

#### app/services/coach_agent.py — Vollständig implementieren

```python
import google.generativeai as genai
from app.core.config import settings

genai.configure(api_key=settings.gemini_api_key)

class CoachAgent:

    SYSTEM_PROMPT = """
    Du bist TrainIQ Coach — ein professioneller Ausdauer-Trainingscoach.
    [EXAKT DEN SYSTEM PROMPT AUS BLUEPRINT.md VERWENDEN]
    """

    def __init__(self):
        self.model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=self.SYSTEM_PROMPT
        )

    async def build_context(self, user_id: str, db) -> str:
        """
        Lädt und formatiert den Kontext für den Coach:
        - Letzte 7 Tage Metriken (HRV, Schlaf, Stress)
        - Heutiger Recovery Score
        - Aktueller Wochenplan
        - Ernährung der letzten 48h (Kalorien, Protein, Carbs)
        - User-Ziele
        - Heutiges Befinden (falls eingetragen)

        Gibt formatierten String zurück der an den Prompt angehängt wird.
        """

    async def stream(self, message: str, user_id: str, db) -> AsyncGenerator[str, None]:
        """
        Streaming Response für Chat.
        1. Kontext laden via build_context()
        2. Chat-Verlauf laden (letzte 20 Nachrichten aus DB)
        3. Gemini generate_content_async() mit stream=True aufrufen
        4. Jeden Chunk als SSE Event yielden: f"data: {chunk}\n\n"
        5. User-Nachricht und Antwort in conversations Tabelle speichern
        6. Falls Antwort eine ACTION enthält: Action parsen und ausführen
        """

    def parse_action(self, response_text: str) -> dict | None:
        """
        Prüft ob Antwort eine JSON-Action enthält.
        Pattern: {...} am Ende der Antwort
        Gibt dict zurück oder None
        """

    async def execute_action(self, action: dict, user_id: str, db):
        """
        Führt Coach-Actions aus:
        - update_plan: Training in DB anpassen
        - set_rest_day: Trainingsplan auf REST setzen
        - log_goal: Neues Ziel speichern
        """
```

#### app/api/routes/coach.py — Vollständig implementieren

**POST /coach/chat:**
```python
@router.post("/chat")
async def chat(request: ChatRequest, current_user = Depends(get_current_user), db = Depends(get_db)):
    agent = CoachAgent()
    return StreamingResponse(
        agent.stream(request.message, str(current_user.id), db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
```

**GET /coach/history:**
- Letzte 50 Conversations aus DB laden
- Chronologisch sortiert
- Zurückgeben: Array von `{role, content, created_at}`

**DELETE /coach/history:**
- Alle Conversations des Users löschen

---

### PHASE 4 — Training Planner

#### app/services/training_planner.py — Vollständig implementieren

```python
class TrainingPlanner:

    async def generate_week_plan(self, user_id: str, week_start: date, db) -> list[dict]:
        """
        Generiert Trainingsplan für eine Woche via Gemini.

        Kontext der übergeben wird:
        - User-Ziele (Sport, Zieldatum, Fitnesslevel, verfügbare Stunden)
        - Letzte 2 Wochen Trainingshistorie
        - Aktuelle Fitness (Recovery Score Trend)
        - Geplante Wochenstunden

        Gemini Prompt:
        "Erstelle einen 7-Tage Trainingsplan für [USER_KONTEXT].
        Antworte NUR mit JSON Array: [{date, sport, workout_type, duration_min,
        intensity_zone, target_hr_min, target_hr_max, description, coach_reasoning}]"

        Parsed JSON und speichert in training_plans Tabelle.
        Gibt Liste der erstellten Pläne zurück.
        """

    async def adjust_for_recovery(self, plan: dict, recovery_score: int) -> dict:
        """
        Passt einen Trainingsplan basierend auf Recovery Score an:
        - Score < 40: workout_type = 'rest', duration_min = 0
        - Score 40-60: intensity_zone -1, duration_min * 0.7
        - Score >= 70: kein Änderung
        """
```

#### app/api/routes/training.py — Vollständig implementieren

**GET /training/plan:**
- Query param: `?week=2024-03-17` (optional, default: aktuelle Woche)
- Trainingsplan aus DB laden
- Falls kein Plan existiert: automatisch via `TrainingPlanner.generate_week_plan()` erstellen
- Jeden Plan mit aktuellem Recovery Score abgleichen via `adjust_for_recovery()`
- Zurückgeben: Array von 7 Trainingstagen

**GET /training/plan/{date}:**
- Einzelnen Tag laden
- Falls nicht vorhanden: 404
- Gibt vollständigen Plan mit `coach_reasoning` zurück

**POST /training/complete/{id}:**
- Status auf 'completed' setzen, `completed_at` = jetzt

**POST /training/skip/{id}:**
- Body: `{reason: str}`
- Status auf 'skipped' setzen

---

### PHASE 5 — Ernährungs-Analyse

#### app/services/nutrition_analyzer.py — Vollständig implementieren

```python
class NutritionAnalyzer:

    async def analyze_image(self, image_bytes: bytes, meal_type: str) -> dict:
        """
        Sendet Bild an Gemini Vision.

        Prompt:
        "Analysiere dieses Essensfoto. Schätze die Nährwerte so genau wie möglich.
        Antworte NUR mit JSON:
        {
          'meal_name': str,
          'calories': float,
          'protein_g': float,
          'carbs_g': float,
          'fat_g': float,
          'portion_notes': str,
          'confidence': 'high' | 'medium' | 'low'
        }"

        Bei Fehler oder nicht-erkennbarem Bild: sinnvolle Defaults zurückgeben.
        """

    async def get_daily_gaps(self, user_id: str, target_calories: int, db) -> list[dict]:
        """
        Berechnet fehlende Nährstoffe für heute.
        Vergleicht: Ist-Werte (aus nutrition_logs) vs. Soll-Werte (aus user_goals / Defaults)
        Defaults: 2000kcal, 150g Protein, 200g Carbs, 65g Fett
        Gibt Liste zurück: [{nutrient, current, target, missing, recommendation}]
        """
```

#### app/services/watch_sync.py — Vollständig implementieren

```python
class WatchSync:

    async def sync_manual_entry(self, user_id: str, data: dict, db):
        """
        Speichert manuell eingegebene Gesundheitsdaten in health_metrics.
        Source: 'manual'
        """

    async def get_demo_data(self, user_id: str, db):
        """
        Generiert realistische Demo-Metriken wenn keine Uhr verbunden.
        Wird verwendet damit App ohne echte Uhr funktioniert.
        HRV: 35-50ms (zufällig mit Trend), Schlaf: 6-8h, Stress: 25-55
        Speichert in health_metrics mit source: 'demo'
        """
```

#### app/api/routes/nutrition.py — Vollständig implementieren

**POST /nutrition/upload:**
- Bild empfangen (multipart/form-data)
- Bild in MinIO speichern (Bucket: nutrition-photos, Key: {user_id}/{timestamp}.jpg)
- `NutritionAnalyzer.analyze_image()` aufrufen
- Ergebnis + Bild-URL in nutrition_logs speichern
- Zurückgeben: `{id, meal_name, calories, protein_g, carbs_g, fat_g, image_url, confidence}`

**GET /nutrition/today:**
- Alle Nutrition Logs von heute laden
- Summen berechnen (total calories, protein, carbs, fat)
- Zurückgeben: `{logs: [...], totals: {calories, protein_g, carbs_g, fat_g}}`

**GET /nutrition/gaps:**
- `NutritionAnalyzer.get_daily_gaps()` aufrufen
- Zurückgeben: Array von fehlenden Nährstoffen

---

### PHASE 6 — Scheduler Jobs

#### app/scheduler/jobs.py — Vollständig implementieren

```python
async def sync_watch_data_for_all_users():
    """
    Läuft alle 4 Stunden.
    Für alle User ohne verbundene Uhr: demo Daten generieren via WatchSync.get_demo_data()
    Für User mit verbundener Uhr: API aufrufen (Garmin nicht implementiert, nur Demo)
    """

async def generate_tomorrow_plans():
    """
    Läuft täglich um 21:00.
    Für alle User: TrainingPlanner.generate_week_plan() wenn kein Plan für morgen existiert.
    """
```

#### app/scheduler/runner.py — Vollständig implementieren

```python
scheduler.add_job(sync_watch_data_for_all_users, 'interval', hours=4, id='watch_sync')
scheduler.add_job(generate_tomorrow_plans, 'cron', hour=21, minute=0, id='plan_gen')
```

---

### PHASE 7 — Frontend Implementierung

#### src/components/dashboard/RecoveryScore.tsx

Großes Recovery Score Widget:
- Score (0-100) in `font-pixel text-blue` bei ≥70, normal bei 40-69, `text-danger` bei <40
- Font size: 88px (`text-[88px]`)
- Label darunter: "BEREIT" / "VORSICHT" / "RUHEN" in tracking-widest uppercase text-xs
- Dünner Fortschrittsbalken (h-[3px]) in entsprechender Farbe
- Beschreibungstext in text-textDim text-xs

#### src/components/dashboard/MetricTile.tsx

Reusable Tile für HRV/Schlaf/Stress:
```tsx
interface MetricTileProps {
  label: string
  value: string | number
  unit: string
  trend: 'up' | 'down' | 'neutral'
  trendPercent?: number
}
```
- Label: text-xs tracking-widest uppercase text-textDim
- Value: font-pixel text-textMain (font-size 32px)
- Trend ▲ in text-blue, ▼ in text-danger

#### src/app/(app)/dashboard/page.tsx — Vollständig implementieren

```tsx
// Daten laden:
const { data: recovery } = useQuery({ queryKey: ['recovery'], queryFn: () => api.get('/metrics/recovery') })
const { data: metrics } = useQuery({ queryKey: ['metrics-today'], queryFn: () => api.get('/metrics/today') })
const { data: training } = useQuery({ queryKey: ['training-today'], queryFn: () => api.get('/training/plan/' + today) })
const { data: nutrition } = useQuery({ queryKey: ['nutrition-today'], queryFn: () => api.get('/nutrition/today') })
```

Layout EXAKT wie im Design Test (design-test.html):
- Recovery Score Hero oben
- Metriken Row (3 Tiles)
- Heutiger Trainingsplan (Karte)
- Ernährungs-Schnellansicht (Balken)
- Coach CTA Button

#### src/app/(app)/chat/page.tsx — Vollständig implementieren

```tsx
// Streaming Chat implementieren:
const sendMessage = async (message: string) => {
  const response = await fetch('/api/coach/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ message })
  })
  const reader = response.body.getReader()
  // Chunks lesen und an Messages State anhängen
  // Während Streaming: Loading Indicator
}
```

Design: EXAKT wie design-test.html Chat-Seite:
- Coach-Nachrichten links mit [C] Avatar
- User-Nachrichten rechts
- Quick-Reply Buttons: "Warum?", "Plan ändern", "Ruhetag", "Wochenziel"
- Terminal-Input mit `›` Prefix und blinkender `_` Cursor
- Foto-Upload Icon (Kamera) für Ernährungs-Upload

#### src/app/(app)/training/page.tsx — Vollständig implementieren

- 7-Tage Strip horizontal (scrollbar)
- Tap auf Tag → Training Detail laden
- Design EXAKT wie design-test.html Training-Seite

#### src/app/(app)/ernaehrung/page.tsx — Vollständig implementieren

- Foto Upload mit Drag & Drop oder Click
- `POST /nutrition/upload` aufrufen
- Loading State während Analyse (Text: "ANALYSIERE...")
- Makro-Balken (h-[3px])
- Mahlzeiten-Liste
- Coach Tipp Box
- Design EXAKT wie design-test.html Ernährungs-Seite

#### src/app/(app)/metriken/page.tsx — Vollständig implementieren

- HRV Trend Chart (Recharts LineChart, angepasst auf Design System)
- Schlaf Phasen Chart (Recharts BarChart, gestapelt)
- Resting HR Grid
- Alle Charts: kein Grid, dünne Achsen, Pixel-Font für Werte
- Design EXAKT wie design-test.html Metriken-Seite

#### src/app/(auth)/login/page.tsx + register/page.tsx

Login:
- Email + Password Input
- POST /auth/login → Token in localStorage speichern
- Redirect zu /dashboard

Register:
- Name + Email + Password Input
- POST /auth/register → automatisch einloggen
- Redirect zu /onboarding

#### src/app/onboarding/page.tsx

3-Schritt Onboarding:
- Schritt 1: Sport wählen (Tiles: Laufen, Radfahren, Schwimmen, Triathlon — Mehrfachauswahl)
- Schritt 2: Ziel eingeben (Freitext + Datum) + POST /auth/me mit Zieldaten
- Schritt 3: "Ohne Uhr starten" Button → POST /watch/sync (Demo-Daten)
- Danach: Redirect zu /dashboard

---

### PHASE 8 — MinIO Setup

In `main.py` beim Start: MinIO Bucket automatisch erstellen falls nicht vorhanden:

```python
@app.on_event("startup")
async def startup():
    from minio import Minio
    from app.core.config import settings
    client = Minio(settings.minio_endpoint, settings.minio_user, settings.minio_password, secure=False)
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
```

---

## Design Regeln (JEDE Zeile Frontend Code beachten)

Aus BLUEPRINT.md Design System:
- `font-pixel` NUR für Zahlen/Werte
- Labels: `text-xs tracking-widest uppercase text-textDim font-sans`
- Borders: `border border-border` — KEIN shadow
- Max border-radius: `rounded` (4px)
- Akzentfarbe Blau: `text-blue` / `border-blue`
- Progress Bars: `h-[3px]` kein radius
- Buttons: Ghost Style `border border-border hover:border-blue hover:text-blue transition-colors`
- Hintergrund: `bg-bg` (#F8F8F8) — KEIN reines Weiß

---

## Abschluss-Checkliste

Nach deiner Arbeit muss folgendes funktionieren:

```bash
cd /Users/abu/Projekt/trainiq
docker compose up --build
```

**Auth:**
- [ ] `POST /api/auth/register` → erstellt User, gibt Token zurück
- [ ] `POST /api/auth/login` → gibt Token zurück
- [ ] Ohne Token → 401 auf geschützte Endpoints

**Metriken:**
- [ ] `GET /api/metrics/today` → gibt Metriken zurück (Demo-Daten wenn keine Uhr)
- [ ] `GET /api/metrics/recovery` → gibt Score 0-100 zurück

**Coach:**
- [ ] `POST /api/coach/chat` → Gemini antwortet als Stream
- [ ] Coach-Antworten enthalten echte Datenwerte des Users

**Training:**
- [ ] `GET /api/training/plan` → gibt 7-Tage Plan zurück
- [ ] Plan wird automatisch erstellt wenn nicht vorhanden

**Ernährung:**
- [ ] `POST /api/nutrition/upload` → analysiert Bild, gibt Nährwerte zurück

**Frontend:**
- [ ] Login/Register funktioniert
- [ ] Dashboard zeigt echte Daten vom Backend
- [ ] Chat sendet Nachrichten und empfängt Streaming-Antworten
- [ ] Wochenplan wird angezeigt
- [ ] Ernährungs-Upload funktioniert
- [ ] Design stimmt mit design-test.html überein

## Was du NICHT tust

- KEINE Änderungen an docker-compose.yml oder Dockerfile
- KEINE Änderungen an der Projektstruktur
- KEINE echte Garmin/Apple Watch API Integration (Demo-Daten sind ausreichend)
- KEINE Tests schreiben
- NICHT vom Design System in BLUEPRINT.md abweichen
