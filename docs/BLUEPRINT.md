# TrainIQ — Agent Blueprint (Gesamtübersicht)

Dieses Dokument ist die zentrale Referenz für alle Agents die an diesem Projekt arbeiten.
Lies es vollständig bevor du irgendetwas schreibst.

---

## Was ist TrainIQ?

Eine KI-gestützte Trainings-Coach-App für Ausdauersportler (Laufen, Radfahren, Schwimmen, Triathlon).
Die App ersetzt einen teuren Personal Coach durch einen KI-Agent der:
- Automatisch Daten von der Smartwatch holt (alle 4 Stunden)
- Ernährungsfotos analysiert und Nährwerte berechnet
- Täglich den Trainingsplan für den nächsten Tag erstellt
- Als Chat-Agent alle Funktionen der App steuert
- Realistisch ist: sagt die Wahrheit basierend auf echten Körperdaten

---

## Technologie Stack (NICHT ändern)

```
Frontend:   Next.js 14 (App Router) + Tailwind CSS + shadcn/ui
Backend:    FastAPI (Python 3.12)
Datenbank:  PostgreSQL 16 (via Docker)
Cache:      Redis 7 (via Docker)
Storage:    MinIO (für Essensfotos, S3-kompatibel)
KI-Coach:   Google Gemini Flash 1.5 API
Proxy:      Nginx (Reverse Proxy)
Deploy:     Docker Compose (alles lokal hochfahren mit `docker compose up`)
```

---

## Projektstruktur (EXAKT so anlegen)

```
trainiq/
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env
├── .env.example
├── nginx/
│   └── nginx.conf
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   └── app/
│       ├── __init__.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── dependencies.py
│       │   └── routes/
│       │       ├── __init__.py
│       │       ├── auth.py
│       │       ├── coach.py
│       │       ├── training.py
│       │       ├── metrics.py
│       │       ├── nutrition.py
│       │       └── watch.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py
│       │   ├── database.py
│       │   └── security.py
│       ├── models/
│       │   ├── __init__.py
│       │   ├── user.py
│       │   ├── training.py
│       │   ├── metrics.py
│       │   ├── nutrition.py
│       │   └── conversation.py
│       ├── services/
│       │   ├── __init__.py
│       │   ├── coach_agent.py
│       │   ├── training_planner.py
│       │   ├── nutrition_analyzer.py
│       │   ├── watch_sync.py
│       │   └── recovery_scorer.py
│       └── scheduler/
│           ├── __init__.py
│           ├── runner.py
│           └── jobs.py
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── tailwind.config.ts
│   ├── next.config.ts
│   └── src/
│       ├── app/
│       │   ├── layout.tsx
│       │   ├── page.tsx               ← Landing/Redirect
│       │   ├── (auth)/
│       │   │   ├── login/page.tsx
│       │   │   └── register/page.tsx
│       │   ├── (app)/
│       │   │   ├── layout.tsx         ← App Shell mit Navigation
│       │   │   ├── dashboard/page.tsx
│       │   │   ├── chat/page.tsx
│       │   │   ├── training/
│       │   │   │   ├── page.tsx
│       │   │   │   └── [date]/page.tsx
│       │   │   ├── ernaehrung/page.tsx
│       │   │   └── metriken/page.tsx
│       │   └── onboarding/page.tsx
│       ├── components/
│       │   ├── ui/                    ← shadcn/ui Komponenten
│       │   ├── chat/
│       │   │   ├── ChatWindow.tsx
│       │   │   ├── MessageBubble.tsx
│       │   │   └── ChatInput.tsx
│       │   ├── dashboard/
│       │   │   ├── RecoveryScore.tsx
│       │   │   ├── MetricTile.tsx
│       │   │   └── TodayWorkout.tsx
│       │   ├── training/
│       │   │   ├── WeekStrip.tsx
│       │   │   └── WorkoutDetail.tsx
│       │   └── nutrition/
│       │       ├── FoodUpload.tsx
│       │       └── MacroBar.tsx
│       ├── lib/
│       │   ├── api.ts
│       │   ├── types.ts
│       │   └── utils.ts
│       └── hooks/
│           ├── useCoach.ts
│           ├── useMetrics.ts
│           └── useTraining.ts
│
└── postgres/
    └── init.sql
```

---

## Design System (EXAKT einhalten)

### Farben (tailwind.config.ts erweitern)
```typescript
colors: {
  bg:       '#F8F8F8',   // Seiten-Hintergrund
  surface:  '#F0F0F0',   // Sections
  card:     '#EBEBEB',   // Karten
  border:   '#DEDEDE',   // Alle Borders
  muted:    '#CCCCCC',   // Deaktivierte Elemente
  textMain: '#111111',   // Haupttext
  textDim:  '#888888',   // Sekundärtext / Labels
  blue:     '#2563EB',   // Akzentfarbe (Positiv, CTAs, Highlights)
  blueDim:  '#DBEAFE',   // Akzent hell (Backgrounds)
  danger:   '#991B1B',   // Fehler / Schlecht
}
```

### Fonts
```typescript
fontFamily: {
  pixel: ['"VT323"', 'monospace'],        // Alle Zahlen / Datenwerte
  mono:  ['"Share Tech Mono"', 'monospace'], // Terminal-Elemente
  sans:  ['Inter', 'sans-serif'],          // Labels, Fließtext
}
// Google Fonts in layout.tsx einbinden:
// VT323, Share Tech Mono, Inter (300, 400, 500, 600)
```

### Typografie Regeln
- **Pixel-Font (VT323)**: Alle numerischen Werte (HRV, HR, Kalorien, Score, Zeiten, Distanzen)
- **All-Caps + tracking-widest + text-xs**: Alle Labels und Beschriftungen (font-sans)
- **font-sans normal**: Fließtext, Nachrichten, Beschreibungen
- Nie: rounded-xl, shadows (box-shadow), Gradienten

### Komponenten Regeln
- `border-radius`: max `rounded` (4px) — kein `rounded-xl` oder `rounded-full`
- `border`: immer `border border-border` — kein `shadow`
- Buttons: `border border-border` Ghost-Style oder `border border-blue text-blue`
- Aktive Elemente: `border-blue text-blue` — kein filled Background außer bei CTAs
- Progress Bars: `h-[3px]` ohne border-radius

---

## Datenbank Schema (postgres/init.sql)

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE user_goals (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  sport TEXT NOT NULL,
  goal_description TEXT NOT NULL,
  target_date DATE,
  weekly_hours INT DEFAULT 5,
  fitness_level TEXT DEFAULT 'intermediate',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE health_metrics (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  recorded_at TIMESTAMPTZ NOT NULL,
  hrv FLOAT,
  resting_hr INT,
  sleep_duration_min INT,
  sleep_quality_score FLOAT,
  sleep_stages JSONB,
  stress_score FLOAT,
  spo2 FLOAT,
  steps INT,
  source TEXT DEFAULT 'manual',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE daily_wellbeing (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  fatigue_score INT CHECK (fatigue_score BETWEEN 1 AND 10),
  mood_score INT CHECK (mood_score BETWEEN 1 AND 10),
  pain_notes TEXT,
  UNIQUE(user_id, date)
);

CREATE TABLE training_plans (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  sport TEXT NOT NULL,
  workout_type TEXT NOT NULL,
  duration_min INT,
  intensity_zone INT CHECK (intensity_zone BETWEEN 1 AND 5),
  target_hr_min INT,
  target_hr_max INT,
  description TEXT,
  coach_reasoning TEXT,
  status TEXT DEFAULT 'planned',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, date)
);

CREATE TABLE nutrition_logs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  logged_at TIMESTAMPTZ DEFAULT NOW(),
  meal_type TEXT,
  image_url TEXT,
  calories FLOAT,
  protein_g FLOAT,
  carbs_g FLOAT,
  fat_g FLOAT,
  analysis_raw JSONB
);

CREATE TABLE conversations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE watch_connections (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  access_token TEXT,
  refresh_token TEXT,
  last_synced_at TIMESTAMPTZ,
  is_active BOOLEAN DEFAULT TRUE,
  UNIQUE(user_id, provider)
);

-- Index für Performance
CREATE INDEX idx_health_metrics_user_date ON health_metrics(user_id, recorded_at DESC);
CREATE INDEX idx_training_plans_user_date ON training_plans(user_id, date);
CREATE INDEX idx_conversations_user ON conversations(user_id, created_at DESC);
CREATE INDEX idx_nutrition_user_date ON nutrition_logs(user_id, logged_at DESC);
```

---

## API Endpoints Übersicht

```
POST /auth/register          Body: {email, name, password}
POST /auth/login             Body: {email, password} → {access_token}
GET  /auth/me                Header: Bearer token → user info

POST /coach/chat             Body: {message} → SSE Stream
GET  /coach/history          → letzte 50 Nachrichten
DELETE /coach/history        → Chat löschen

GET  /training/plan          Query: ?week=2024-03-17 → Wochenplan
GET  /training/plan/{date}   → Tagesplan
POST /training/complete/{id} → als erledigt markieren
POST /training/skip/{id}     Body: {reason}

GET  /metrics/today          → heutige Werte
GET  /metrics/week           → 7 Tage
GET  /metrics/recovery       → Recovery Score (0-100)
POST /metrics/wellbeing      Body: {fatigue, mood, pain_notes}

POST /nutrition/upload       Form: file (image) → analysiert + gespeichert
GET  /nutrition/today        → heutige Nährwerte + Mahlzeiten
GET  /nutrition/gaps         → fehlende Nährstoffe

POST /watch/sync             → manueller Sync
GET  /watch/status           → Verbindungsstatus
```

---

## Umgebungsvariablen (.env)

```env
# Datenbank
POSTGRES_USER=trainiq
POSTGRES_PASSWORD=trainiq_dev_password
POSTGRES_DB=trainiq
DATABASE_URL=postgresql://trainiq:trainiq_dev_password@postgres:5432/trainiq

# Redis
REDIS_URL=redis://redis:6379

# MinIO Storage
MINIO_ENDPOINT=minio:9000
MINIO_USER=trainiq
MINIO_PASSWORD=trainiq_minio_password
MINIO_BUCKET=nutrition-photos

# KI
GEMINI_API_KEY=HIER_ECHTEN_KEY_EINTRAGEN

# Security
JWT_SECRET=ein_sehr_langer_zufaelliger_string_mindestens_32_zeichen
JWT_EXPIRE_MINUTES=10080

# App
BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_API_URL=http://localhost/api
```

---

## Coach Agent — Verhalten & Regeln

Der Coach ist ein Gemini-Flash Agent mit diesen festen Regeln:

```
SYSTEM PROMPT:
Du bist TrainIQ Coach — ein professioneller Ausdauer-Trainingscoach.

DEINE DATEN (werden automatisch als Kontext übergeben):
- Letzte 7 Tage Gesundheitsmetriken (HRV, Schlaf, Stresslevel)
- Aktueller Trainingsplan der Woche
- Ernährungsdaten der letzten 48 Stunden
- Morgendliches Befinden (falls eingetragen)
- User-Ziele und Fitnesslevel

DEINE REGELN:
1. Antworte IMMER auf Basis der echten Datenwerte — erfinde nichts
2. Wenn HRV niedrig (< 20% unter Durchschnitt): empfehle Ruhe oder leichtes Training
3. Wenn Schlaf < 6h: warne vor Übertraining, passe Intensität an
4. Unrealistische Ziele klar benennen und Alternativen vorschlagen
5. Kurze, direkte Antworten — max 3-4 Sätze außer bei Planung
6. Zahlen immer konkret nennen (nicht "deine HRV ist gut" sondern "deine HRV ist 42ms")
7. Antworte auf Deutsch

AKTIONEN die du ausführen kannst (als JSON am Ende der Antwort):
{"action": "update_plan", "date": "2024-03-17", "changes": {...}}
{"action": "set_rest_day", "date": "2024-03-17"}
{"action": "log_goal", "goal": "..."}
```

---

## Recovery Score Algorithmus

```python
def calculate_recovery_score(metrics: dict) -> int:
    """
    Gewichtete Formel basierend auf Paper-Erkenntnissen:
    HRV:    35% Gewichtung (stärkster Prädiktor)
    Schlaf: 25% Gewichtung
    Stress: 20% Gewichtung
    HR:     20% Gewichtung

    Rückgabe: 0-100 Score
    """
    hrv_score    = normalize(metrics['hrv'],    baseline_hrv,    weight=0.35)
    sleep_score  = normalize(metrics['sleep'],  target=480,      weight=0.25)
    stress_score = normalize(100 - metrics['stress'], 70,        weight=0.20)
    hr_score     = normalize(60 - metrics['resting_hr'], 0,      weight=0.20)

    return int(min(100, max(0, (hrv_score + sleep_score + stress_score + hr_score) * 100)))
```

---

## Wichtige Implementierungshinweise

### FastAPI Pattern (IMMER so verwenden)
```python
# Dependency Injection für Auth
async def get_current_user(token: str = Depends(oauth2_scheme), db = Depends(get_db)):
    ...

# Route Pattern
@router.get("/metrics/today")
async def get_today_metrics(current_user = Depends(get_current_user), db = Depends(get_db)):
    ...

# Streaming für Coach Chat (SSE)
@router.post("/coach/chat")
async def chat(request: ChatRequest, current_user = Depends(get_current_user)):
    return StreamingResponse(coach_agent.stream(request.message, current_user), media_type="text/event-stream")
```

### Next.js Pattern (IMMER so verwenden)
```typescript
// API calls über /lib/api.ts zentralisieren
// Kein direktes fetch() in Komponenten
// Alle Seiten unter (app)/ brauchen Auth-Check in layout.tsx
// Pixel-Font nur für Zahlen: <span className="font-pixel text-blue">42</span>
// Labels immer: <span className="text-xs tracking-widest uppercase text-textDim font-sans">
```

### Fehler die VERMIEDEN werden müssen
- KEIN `rounded-xl` oder `rounded-full` — max `rounded`
- KEIN `shadow-*` — immer `border border-border`
- KEIN reines `#000000` oder `#FFFFFF`
- KEIN direktes fetch() in React Komponenten — immer über api.ts
- KEINE synchronen Datenbankoperationen in FastAPI — immer async
- KEIN Hardcoding von Ports oder URLs — immer aus .env
- KEIN requirements.txt ohne Pin der Versionen
