# Training Coach App — Komplette Architektur

## Übersicht

```
┌─────────────────────────────────────────────────────────────┐
│                     DOCKER COMPOSE                          │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │   frontend   │   │   backend    │   │   scheduler    │  │
│  │  Next.js     │   │   FastAPI    │   │  APScheduler   │  │
│  │  :3000       │   │  :8000       │   │  (4h Jobs)     │  │
│  └──────┬───────┘   └──────┬───────┘   └───────┬────────┘  │
│         │                  │                   │            │
│         └──────────────────▼───────────────────┘            │
│                     ┌──────────────┐                        │
│                     │    nginx     │                        │
│                     │  :80 / :443  │ ← Reverse Proxy        │
│                     └──────────────┘                        │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │  postgresql  │   │    redis     │   │    storage     │  │
│  │  :5432       │   │  :6379       │   │  (Minio :9000) │  │
│  └──────────────┘   └──────────────┘   └────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────▼──────────────────┐
              │           Externe APIs            │
              │  Garmin | Gemini | Firebase       │
              │  Apple Health | Strava | Polar    │
              └──────────────────────────────────┘
```

---

## 1. Frontend — Next.js

### Seiten / Routes

```
/                    → Landing Page
/login               → Login / Register
/dashboard           → Hauptübersicht (Metriken, heutiger Plan)
/chat                → Coach Chat (Herzstück)
/training            → Trainingsplan (Woche/Monat)
/training/[date]     → Detail eines Trainingstags
/ernaehrung          → Ernährungslog + Upload
/metriken            → HRV, Schlaf, HR Charts
/profil              → Ziele, Uhr verbinden, Einstellungen
/onboarding          → Ersteinrichtung (Ziele, Sport, Uhr)
```

### Komponenten-Struktur

```
src/
├── app/
│   ├── dashboard/
│   ├── chat/
│   ├── training/
│   ├── ernaehrung/
│   ├── metriken/
│   └── profil/
├── components/
│   ├── chat/
│   │   ├── ChatWindow.tsx
│   │   ├── MessageBubble.tsx
│   │   └── InputBar.tsx
│   ├── dashboard/
│   │   ├── MetricCard.tsx
│   │   ├── TrainingPreview.tsx
│   │   └── RecoveryScore.tsx
│   ├── training/
│   │   ├── WeekView.tsx
│   │   └── WorkoutCard.tsx
│   └── ernaehrung/
│       ├── FoodUpload.tsx
│       └── NutritionSummary.tsx
├── lib/
│   ├── api.ts           → API calls zum Backend
│   ├── supabase.ts      → Supabase Client
│   └── types.ts         → TypeScript Types
└── hooks/
    ├── useCoach.ts      → Coach Chat Hook
    ├── useMetrics.ts    → Health Metrics Hook
    └── useTraining.ts   → Training Plan Hook
```

### Tech Stack Frontend
- **Next.js 14** (App Router)
- **Tailwind CSS** (Styling)
- **shadcn/ui** (UI Komponenten — kostenlos, schön)
- **Recharts** (Grafiken für HRV, Schlaf, etc.)
- **Supabase JS Client** (Auth + Realtime)

---

## 2. Backend — FastAPI

### Ordnerstruktur

```
backend/
├── main.py                  → FastAPI App Entry Point
├── requirements.txt
├── .env
├── app/
│   ├── api/
│   │   ├── routes/
│   │   │   ├── auth.py          → Login, Register, Token
│   │   │   ├── coach.py         → Chat mit KI-Coach
│   │   │   ├── training.py      → Trainingsplan CRUD
│   │   │   ├── metrics.py       → Health Daten abrufen
│   │   │   ├── nutrition.py     → Foto Upload + Analyse
│   │   │   ├── watch.py         → Watch verbinden/sync
│   │   │   └── notifications.py → Push Einstellungen
│   │   └── dependencies.py      → Auth Middleware, DB Session
│   ├── services/
│   │   ├── coach_agent.py       → LLM Agent Logik
│   │   ├── training_planner.py  → Trainingsplan Generator
│   │   ├── nutrition_analyzer.py→ Foto → Nährwerte (Gemini Vision)
│   │   ├── watch_sync.py        → Garmin/Strava Daten holen
│   │   ├── recovery_scorer.py   → Erholungs-Score berechnen
│   │   └── notification_sender.py → Firebase Push
│   ├── models/
│   │   ├── user.py
│   │   ├── training.py
│   │   ├── metrics.py
│   │   ├── nutrition.py
│   │   └── conversation.py
│   ├── scheduler/
│   │   ├── jobs.py              → APScheduler Jobs
│   │   ├── watch_puller.py      → Alle 4h Uhr-Daten holen
│   │   └── plan_generator.py   → Jeden Abend Plan erstellen
│   └── core/
│       ├── config.py            → Einstellungen (.env)
│       ├── database.py          → Supabase/PostgreSQL Connection
│       └── security.py          → JWT, Passwort-Hashing
```

### API Endpoints

```
AUTH
POST   /auth/register
POST   /auth/login
POST   /auth/refresh

COACH
POST   /coach/chat              → Nachricht senden, Antwort streamen
GET    /coach/history           → Chat-Verlauf
DELETE /coach/history           → Chat zurücksetzen

TRAINING
GET    /training/plan           → Aktueller Wochenplan
GET    /training/plan/{date}    → Plan für bestimmten Tag
POST   /training/complete       → Training als erledigt markieren
POST   /training/skip           → Training überspringen + Grund
GET    /training/history        → Vergangene Trainings

METRIKEN
GET    /metrics/today           → Heutige Werte (HRV, Schlaf, HR)
GET    /metrics/week            → Wochenverlauf
GET    /metrics/recovery        → Aktueller Recovery Score
POST   /metrics/subjective      → Morgendliches Befinden eintragen

ERNÄHRUNG
POST   /nutrition/upload        → Foto hochladen → analysieren
GET    /nutrition/today         → Heutige Nährwerte
GET    /nutrition/gaps          → Fehlende Nährstoffe
GET    /nutrition/history       → Verlauf

UHR
POST   /watch/connect           → Uhr verbinden (OAuth)
POST   /watch/sync              → Manuell Daten holen
GET    /watch/status            → Verbindungsstatus

NUTZER
GET    /user/profile
PUT    /user/goals              → Ziele setzen/ändern
PUT    /user/sports             → Sportarten wählen
```

---

## 3. Datenbank — Supabase (PostgreSQL)

### Tabellen

```sql
-- Nutzer
users (
  id UUID PRIMARY KEY,
  email TEXT,
  name TEXT,
  created_at TIMESTAMP
)

-- Ziele
user_goals (
  id UUID,
  user_id UUID → users,
  sport TEXT,              -- 'running', 'cycling', 'triathlon'
  goal_description TEXT,   -- "Halbmarathon unter 2h"
  target_date DATE,
  current_fitness_level TEXT,
  weekly_hours_available INT,
  created_at TIMESTAMP
)

-- Gesundheitsmetriken (von der Uhr)
health_metrics (
  id UUID,
  user_id UUID → users,
  recorded_at TIMESTAMP,
  hrv FLOAT,
  resting_hr INT,
  sleep_duration_min INT,
  sleep_quality_score FLOAT,
  sleep_stages JSONB,      -- {deep, light, rem, awake}
  stress_score FLOAT,
  spo2 FLOAT,
  steps INT,
  source TEXT              -- 'garmin', 'apple_health', 'manual'
)

-- Subjektives Befinden (täglich)
daily_wellbeing (
  id UUID,
  user_id UUID → users,
  date DATE,
  fatigue_score INT,       -- 1-10
  mood_score INT,          -- 1-10
  pain_areas TEXT[],       -- ['knee', 'lower_back']
  notes TEXT
)

-- Trainingsplan
training_plans (
  id UUID,
  user_id UUID → users,
  date DATE,
  sport TEXT,
  workout_type TEXT,       -- 'easy_run', 'intervals', 'rest', 'strength'
  duration_min INT,
  intensity_zone INT,      -- 1-5
  description TEXT,
  coach_reasoning TEXT,    -- Warum hat Coach das empfohlen?
  status TEXT,             -- 'planned', 'completed', 'skipped', 'modified'
  completed_at TIMESTAMP,
  actual_duration_min INT
)

-- Ernährungslogs
nutrition_logs (
  id UUID,
  user_id UUID → users,
  logged_at TIMESTAMP,
  meal_type TEXT,          -- 'breakfast', 'lunch', 'dinner', 'snack'
  image_url TEXT,
  raw_analysis JSONB,      -- Gemini Vision Output
  calories FLOAT,
  protein_g FLOAT,
  carbs_g FLOAT,
  fat_g FLOAT,
  micronutrients JSONB
)

-- Coach Gespräche
conversations (
  id UUID,
  user_id UUID → users,
  role TEXT,               -- 'user' oder 'assistant'
  content TEXT,
  created_at TIMESTAMP,
  metadata JSONB           -- z.B. welche Daten der Coach genutzt hat
)

-- Uhr-Verbindungen
watch_connections (
  id UUID,
  user_id UUID → users,
  provider TEXT,           -- 'garmin', 'apple', 'polar', 'strava'
  access_token TEXT,
  refresh_token TEXT,
  last_synced_at TIMESTAMP,
  is_active BOOLEAN
)
```

---

## 4. KI-Coach — Agent Architektur

### Wie der Agent denkt

```
User schickt Nachricht
        ↓
Agent sammelt Kontext:
  - Letzte 7 Tage Metriken (HRV, Schlaf, HR)
  - Aktueller Trainingsplan
  - Heutiges Befinden
  - Ernährung letzte 48h
  - User-Ziele
  - Chat-Verlauf (letzte 20 Nachrichten)
        ↓
Agent entscheidet:
  - Nur antworten?
  - Trainingsplan ändern?
  - Ernährungstipp geben?
  - Alarm schlagen? (Übertraining, Verletzungsrisiko)
        ↓
Agent antwortet (gestreamt)
        ↓
Wenn Aktion nötig → Agent ruft interne Tools auf:
  - update_training_plan()
  - set_rest_day()
  - send_notification()
  - log_user_goal()
```

### Agent System Prompt (Kern)

```
Du bist ein professioneller Ausdauer-Coach. Du hast Zugriff auf:
- Die Echtzeit-Gesundheitsdaten des Athleten
- Den aktuellen Trainingsplan
- Die Ernährungsprotokolle
- Die Trainingshistorie

Deine Prinzipien:
1. REALISMUS: Sage immer die Wahrheit. Schmeichle nicht.
2. DATENBASIERT: Triff Entscheidungen nur auf Basis echter Werte.
3. GANZHEITLICH: Berücksichtige Körper, Ernährung, Schlaf und Psyche.
4. PROAKTIV: Erkenne Probleme bevor sie auftreten.

Wenn ein Ziel unrealistisch ist, sage es klar und biete einen
realistischen Alternativplan an.
```

### LLM Wahl
- **Primär:** Google Gemini Flash (kostenlos, schnell, Vision-fähig)
- **Fallback:** Groq + Llama 3 (kostenlos, sehr schnell)
- **Später:** Fine-tuned Modell auf Sportwissenschaft

---

## 5. Hintergrund-Jobs (Scheduler)

```python
# Alle 4 Stunden — Uhr-Daten holen
@scheduler.scheduled_job('interval', hours=4)
async def sync_watch_data():
    # Für alle aktiven User mit verbundener Uhr
    # Garmin/Strava/Apple API aufrufen
    # Neue Daten in health_metrics speichern
    # Recovery Score neu berechnen

# Jeden Abend 21:00 — Trainingsplan für morgen
@scheduler.scheduled_job('cron', hour=21)
async def generate_tomorrow_plan():
    # Für alle User
    # Aktuelle Werte analysieren
    # Coach-Agent: "Was soll User morgen tun?"
    # Plan in training_plans speichern

# Jeden Morgen 07:00 — Push Notification
@scheduler.scheduled_job('cron', hour=7)
async def send_morning_brief():
    # Heutigen Plan holen
    # Personalisierte Nachricht generieren
    # Via Firebase senden

# Jeden Morgen 07:30 — Befinden abfragen
@scheduler.scheduled_job('cron', hour=7, minute=30)
async def send_wellbeing_check():
    # Push: "Wie fühlst du dich heute?"
    # User antwortet im Chat
```

---

## 6. Watch Integration — Garmin als Beispiel

```
User klickt "Garmin verbinden"
        ↓
OAuth2 Flow → Garmin Login
        ↓
Access Token gespeichert in watch_connections
        ↓
Scheduler holt alle 4h:
  - /wellness-service/wellness/dailyHeartRate
  - /wellness-service/wellness/dailySleep
  - /hrv-service/hrv/dailyHrvSummary
  - /activity-service/activityList
        ↓
Daten in health_metrics gespeichert
        ↓
Recovery Score neu berechnet
        ↓
Coach hat frische Daten für nächste Frage
```

---

## 7. Docker Compose Setup

### Projektstruktur

```
trainiq/
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env
├── .env.example
├── nginx/
│   └── nginx.conf
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── ...
├── frontend/
│   ├── Dockerfile
│   └── ...
└── postgres/
    └── init.sql         ← Tabellen beim ersten Start anlegen
```

### docker-compose.yml (Entwicklung)

```yaml
version: "3.9"

services:

  # ─── Datenbank ───────────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    container_name: trainiq_db
    restart: unless-stopped
    environment:
      POSTGRES_DB: trainiq
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./postgres/init.sql:/docker-entrypoint-initdb.d/init.sql
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d trainiq"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ─── Redis (Cache + Job Queue) ───────────────────────────
  redis:
    image: redis:7-alpine
    container_name: trainiq_redis
    restart: unless-stopped
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ─── File Storage (Essensfotos) ──────────────────────────
  minio:
    image: minio/minio:latest
    container_name: trainiq_storage
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_PASSWORD}
    volumes:
      - minio_data:/data
    ports:
      - "9000:9000"   # API
      - "9001:9001"   # Web Console
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 10s
      retries: 3

  # ─── Backend ─────────────────────────────────────────────
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: trainiq_backend
    restart: unless-stopped
    env_file: .env
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/trainiq
      REDIS_URL: redis://redis:6379
      MINIO_ENDPOINT: minio:9000
    volumes:
      - ./backend:/app       # Hot-reload in Entwicklung
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload

  # ─── Scheduler (separater Container) ────────────────────
  scheduler:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: trainiq_scheduler
    restart: unless-stopped
    env_file: .env
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/trainiq
      REDIS_URL: redis://redis:6379
    volumes:
      - ./backend:/app
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: python -m app.scheduler.runner   # Nur den Scheduler starten

  # ─── Frontend ────────────────────────────────────────────
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: trainiq_frontend
    restart: unless-stopped
    environment:
      NEXT_PUBLIC_API_URL: http://localhost/api
    volumes:
      - ./frontend:/app       # Hot-reload
      - /app/node_modules     # node_modules nicht überschreiben
    ports:
      - "3000:3000"
    depends_on:
      - backend
    command: npm run dev

  # ─── Nginx (Reverse Proxy) ───────────────────────────────
  nginx:
    image: nginx:alpine
    container_name: trainiq_nginx
    restart: unless-stopped
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    ports:
      - "80:80"
    depends_on:
      - backend
      - frontend

volumes:
  postgres_data:
  redis_data:
  minio_data:
```

### nginx/nginx.conf

```nginx
events { worker_connections 1024; }

http {
  upstream backend  { server backend:8000; }
  upstream frontend { server frontend:3000; }

  server {
    listen 80;

    # API Requests → FastAPI
    location /api/ {
      proxy_pass http://backend/;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
    }

    # WebSocket für Chat Streaming
    location /api/coach/chat {
      proxy_pass http://backend/coach/chat;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
    }

    # Alles andere → Next.js
    location / {
      proxy_pass http://frontend;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
    }
  }
}
```

### backend/Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Dependencies zuerst (besseres Caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
```

### frontend/Dockerfile

```dockerfile
FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 3000
```

### .env (Vorlage)

```env
# Datenbank
POSTGRES_USER=trainiq
POSTGRES_PASSWORD=sicherespasswort123

# Storage
MINIO_USER=trainiq
MINIO_PASSWORD=sicherespasswort123

# KI
GEMINI_API_KEY=dein_gemini_key

# Externe APIs
GARMIN_CLIENT_ID=
GARMIN_CLIENT_SECRET=
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
FIREBASE_PROJECT_ID=

# Sicherheit
JWT_SECRET=sehr_langer_zufaelliger_string
```

### Befehle

```bash
# Alles starten (erste Mal)
docker compose up --build

# Starten (danach)
docker compose up

# Im Hintergrund
docker compose up -d

# Logs anschauen
docker compose logs -f backend
docker compose logs -f scheduler

# Stoppen
docker compose down

# Alles löschen inkl. Daten (Vorsicht!)
docker compose down -v

# Einzelnen Service neustarten
docker compose restart backend
```

### Produktion (docker-compose.prod.yml)

```yaml
# Überschreibt nur was sich in Produktion unterscheidet
version: "3.9"

services:
  backend:
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
    volumes: []    # Kein Volume-Mount in Produktion

  frontend:
    command: npm run build && npm start
    volumes: []

  nginx:
    volumes:
      - ./nginx/nginx.prod.conf:/etc/nginx/nginx.conf:ro
      - ./certbot/conf:/etc/letsencrypt    # HTTPS
```

```bash
# Produktion starten
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## 8. Entwicklungsreihenfolge (Phase A → D)

### Phase A — Coach Chat MVP (Woche 1-3)
- [ ] FastAPI Setup + Supabase Connection
- [ ] User Auth (Register/Login)
- [ ] Coach Chat Endpoint (Gemini Flash)
- [ ] Manuelle Dateneingabe (Ziele, Befinden)
- [ ] Next.js Frontend mit Chat-Interface
- [ ] Deploy auf Render + Vercel

### Phase B — Watch Integration (Woche 4-6)
- [ ] Garmin OAuth2 Flow
- [ ] Watch Data Endpoints
- [ ] 4h Scheduler einrichten
- [ ] Recovery Score Algorithmus
- [ ] Coach nutzt echte Werte
- [ ] Dashboard mit Metriken

### Phase C — Ernährung (Woche 7-9)
- [ ] Foto-Upload zu Supabase Storage
- [ ] Gemini Vision Analyse
- [ ] Nährwert-Tracking
- [ ] Coach gibt Ernährungstipps
- [ ] Weitere Wearables (Apple, Strava)

### Phase D — Personalisierung (Woche 10+)
- [ ] Trainingsplan-Generator
- [ ] Individuelle Kalibrierung (8-12 Wochen Daten)
- [ ] Push Notifications (Firebase)
- [ ] Wöchentliche Reviews
- [ ] Multi-Sport (Triathlon) Support

---

## Java → FastAPI Vergleich (für dich)

```
Java Spring Boot          FastAPI Python
─────────────────         ──────────────
@RestController     →     @app.get("/route")
@Service            →     services/myservice.py
@Repository         →     Supabase Client
@Entity             →     Pydantic BaseModel
@Autowired          →     Depends() (Dependency Injection)
ResponseEntity      →     JSONResponse
application.yml     →     .env + config.py
Maven/Gradle        →     pip + requirements.txt
```

FastAPI fühlt sich sehr ähnlich an — nur weniger Boilerplate!
