# AGENT C — Infrastruktur, Security-Hardening, Docker & CI

> **Arbeitsverzeichnis:** `/Users/abu/Projekt/trainiq/`
> **Lies die bestehenden Dateien vollständig vor dem Bearbeiten.**
> **Du implementierst alles selbst. Keine Platzhalter, keine TODOs.**

---

## KRITISCHE SECURITY-HARDENING

### Security C-FIX-1 — `config.py`: Produktions-Prüfung für JWT_SECRET

**Datei:** `/Users/abu/Projekt/trainiq/backend/app/core/config.py`

Der Default-Wert `"dev-secret-not-for-production"` für `jwt_secret` ist gefährlich. Wenn die App ohne env-Variable startet, ist das JWT unsicher. Füge eine Validator-Warnung hinzu:

**Ersetze den gesamten Settings-Block** (Zeile 4-28) mit:

```python
import os
import warnings
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    gemini_api_key: str = ""
    jwt_secret: str = "dev-secret-not-for-production"
    jwt_expire_minutes: int = 10080

    # Strava API
    strava_client_id: str = ""
    strava_client_secret: str = ""
    strava_redirect_uri: str = "http://localhost/api/watch/strava/callback"
    frontend_url: str = "http://localhost"

    # Dev-Modus: kein API-Key nötig, feste Demo-User-ID
    dev_mode: bool = True
    demo_user_id: str = "00000000-0000-0000-0000-000000000001"

    class Config:
        env_file = ".env"


settings = Settings()

# Sicherheitswarnung bei unsicherem JWT Secret
if settings.jwt_secret == "dev-secret-not-for-production" and not settings.dev_mode:
    warnings.warn(
        "SICHERHEITSRISIKO: JWT_SECRET ist der Standard-Dev-Wert! "
        "Setze JWT_SECRET in deiner .env auf einen sicheren zufälligen Wert.",
        RuntimeWarning,
        stacklevel=2,
    )
```

---

### Security C-FIX-2 — `main.py`: Helmet-Style Security Headers

**Datei:** `/Users/abu/Projekt/trainiq/backend/main.py`

Prüfe ob Security Headers in der FastAPI-App gesetzt werden. Falls nicht, füge eine Middleware hinzu.

Suche nach `from fastapi` Importen und füge nach den bestehenden Middleware-Einträgen hinzu:

```python
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(SecurityHeadersMiddleware)
```

**WICHTIG:** Füge `SecurityHeadersMiddleware` NACH den anderen Middleware (z.B. nach CORS) hinzu. Reihenfolge: CORS → SecurityHeaders.

---

## DOCKER PRODUKTIONSKONFIGURATION

### Docker C-1 — `docker-compose.prod.yml` prüfen und vervollständigen

**Datei:** `/Users/abu/Projekt/trainiq/docker-compose.prod.yml`

Lies die bestehende Datei. Sie muss folgende Anforderungen erfüllen:
1. **Kein `volumes` für Code** — keine `./backend:/app` mounts in Production
2. **Backend** nutzt Gunicorn (kein `--reload`)
3. **Frontend** nutzt `next start` (kein `npm run dev`)
4. **Scheduler** startet korrekt mit python-Modul
5. **Healthchecks** für Backend vorhanden

Falls Punkte fehlen, korrigiere die Datei. Eine vollständige korrekte Version:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./postgres/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
    env_file: .env
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  migrate:
    build: ./backend
    command: alembic upgrade head
    environment:
      - DATABASE_URL=${DATABASE_URL}
    depends_on:
      postgres:
        condition: service_healthy
    env_file: .env
    restart: "no"

  backend:
    build: ./backend
    depends_on:
      migrate:
        condition: service_completed_successfully
      redis:
        condition: service_healthy
    # KEINE Volume-Mounts — Production nutzt gebauten Container
    command: gunicorn main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120
    env_file: .env
    environment:
      - DEV_MODE=false
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    restart: unless-stopped

  scheduler:
    build: ./backend
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: python -m app.scheduler.runner
    env_file: .env
    environment:
      - DEV_MODE=false
    restart: unless-stopped

  frontend:
    build: ./frontend
    depends_on:
      - backend
    # KEINE Volume-Mounts — nutzt Standalone-Build
    command: node server.js
    environment:
      - NODE_ENV=production
      - PORT=3000
    env_file: .env
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    depends_on:
      - backend
      - frontend
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
```

---

### Docker C-2 — `.dockerignore` erstellen für Backend

**Neue Datei:** `/Users/abu/Projekt/trainiq/backend/.dockerignore`

```
__pycache__/
*.pyc
*.pyo
*.pyd
.pytest_cache/
test.db
.env
.env.*
*.egg-info/
dist/
build/
.git/
.gitignore
tests/
*.md
```

### Docker C-3 — `.dockerignore` erstellen für Frontend

**Neue Datei:** `/Users/abu/Projekt/trainiq/frontend/.dockerignore`

```
node_modules/
.next/
.git/
.env
.env.*
*.md
.DS_Store
```

---

## CI/CD — GITHUB ACTIONS

### CI C-4 — GitHub Actions Workflow erstellen

**Neue Datei:** `/Users/abu/Projekt/trainiq/.github/workflows/ci.yml`

Erstelle das Verzeichnis und die Datei (erstelle `.github/workflows/` wenn nötig):

```yaml
name: TrainIQ CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  backend-tests:
    name: Backend Tests
    runs-on: ubuntu-latest

    services:
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"
          cache-dependency-path: backend/requirements.txt

      - name: Install dependencies
        working-directory: backend
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio httpx aiosqlite

      - name: Run tests
        working-directory: backend
        env:
          DATABASE_URL: sqlite+aiosqlite:///./test.db
          REDIS_URL: redis://localhost:6379
          JWT_SECRET: test-secret-ci
          DEV_MODE: "true"
          DEMO_USER_ID: "00000000-0000-0000-0000-000000000001"
          GEMINI_API_KEY: ""
          CLOUDINARY_CLOUD_NAME: ""
          CLOUDINARY_API_KEY: ""
          CLOUDINARY_API_SECRET: ""
        run: python -m pytest tests/ -v --tb=short

  frontend-build:
    name: Frontend Build Check
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        working-directory: frontend
        run: npm ci

      - name: Type check
        working-directory: frontend
        run: npx tsc --noEmit

      - name: Build
        working-directory: frontend
        env:
          NEXT_TELEMETRY_DISABLED: 1
          BACKEND_URL: http://backend:8000
        run: npm run build
```

---

## ENVIRONMENT-KONFIGURATION

### Env C-5 — `.env.example` aktualisieren

**Datei:** `/Users/abu/Projekt/trainiq/.env.example`

Prüfe ob die Datei existiert und vervollständige sie. Eine vollständige Version:

```bash
# === Datenbank ===
DATABASE_URL=postgresql+asyncpg://trainiq:changeme@localhost:5432/trainiq
POSTGRES_USER=trainiq
POSTGRES_PASSWORD=changeme
POSTGRES_DB=trainiq

# === Redis ===
REDIS_URL=redis://localhost:6379

# === Security ===
# Generiere mit: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=AENDERN_VOR_DEPLOYMENT

# === APIs ===
GEMINI_API_KEY=dein_gemini_api_key

# === Bildupload (Cloudinary) ===
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=

# === Strava OAuth (optional) ===
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
STRAVA_REDIRECT_URI=http://localhost/api/watch/strava/callback

# === App ===
FRONTEND_URL=http://localhost
DEV_MODE=false
DEMO_USER_ID=00000000-0000-0000-0000-000000000001

# === Frontend ===
NEXT_PUBLIC_API_URL=http://localhost/api
BACKEND_URL=http://backend:8000
```

---

## LOGGING & MONITORING

### Logging C-6 — Strukturiertes Logging in Backend einrichten

**Datei:** `/Users/abu/Projekt/trainiq/backend/main.py`

Prüfe ob `logging` konfiguriert ist. Falls nicht — Füge am Anfang von `main.py` hinzu (nach den Importen):

```python
import logging
import sys

# Strukturiertes Logging für Production
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("trainiq")
```

Und in dem Health-Check Endpoint — logge Fehler:

```python
@app.get("/health")
async def health():
    # ... bestehender Code ...
    if not redis_ok:
        logger.warning("Health check: Redis nicht erreichbar")
    return {...}
```

---

## NGINX FINALE PRODUKTIONSKONFIGURATION

### Nginx C-7 — Rate Limiting für API

**Datei:** `/Users/abu/Projekt/trainiq/nginx/nginx.conf`

Füge am Anfang der Datei (vor `upstream backend`) hinzu:

```nginx
# Rate Limiting Zones
limit_req_zone $binary_remote_addr zone=api:10m rate=30r/m;
limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/m;
```

Und im `location /api/` Block:

```nginx
location /api/ {
    limit_req zone=api burst=10 nodelay;
    rewrite ^/api/(.*) /$1 break;
    ...
}
```

Für `location /api/auth/`:

```nginx
location /api/auth/ {
    limit_req zone=auth burst=3 nodelay;
    rewrite ^/api/(.*) /$1 break;
    proxy_pass http://backend;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

**WICHTIG:** Platziere `/api/auth/` **VOR** dem allgemeinen `/api/` Block in nginx.conf, da Nginx den ersten passenden Block nimmt.

---

## README AKTUALISIEREN

### Docs C-8 — `README.md` erstellen oder aktualisieren

**Datei:** `/Users/abu/Projekt/trainiq/README.md`

Prüfe ob README existiert. Erstelle oder aktualisiere es mit:

```markdown
# TrainIQ — KI Trainingscoach

KI-gestützter Trainingscoach für Ausdauersportler. Analysiert Biometrie (HRV, Schlaf, Stress), erstellt personalisierte Trainingspläne und gibt Echtzeit-Coaching via Chat.

## Features
- 🤖 KI-Coach (Gemini Flash 1.5) mit Kontext-Awareness
- 📊 Automatische Biometrie-Analyse und Recovery Scoring
- 🏃 Personalisierte Trainingspläne (Laufen, Radfahren, Schwimmen, Triathlon)
- 📷 Mahlzeiten-Analyse via Foto-Upload
- ⌚ Strava-Integration für automatische Datensynchronisation

## Schnellstart

### Prerequisites
- Docker + Docker Compose
- Ein Gemini API Key (kostenlos: https://aistudio.google.com/)

### Setup
\`\`\`bash
# 1. Repository klonen
git clone <repo-url> && cd trainiq

# 2. Environment konfigurieren
cp .env.example .env
# Bearbeite .env und setze GEMINI_API_KEY und JWT_SECRET

# 3. Starten (Development)
docker compose up --build

# 4. App öffnen
open http://localhost
\`\`\`

### Tests ausführen
\`\`\`bash
cd backend
pip install pytest pytest-asyncio httpx aiosqlite
python -m pytest tests/ -v
\`\`\`

### Production Deploy
\`\`\`bash
docker compose -f docker-compose.prod.yml up --build -d
\`\`\`

## Architektur
- **Backend:** FastAPI + PostgreSQL + Redis
- **Frontend:** Next.js 14 (App Router) + Tailwind CSS
- **KI:** Google Gemini Flash 1.5
- **Reverse Proxy:** Nginx

## Environment-Variablen (wichtig)
| Variable | Beschreibung |
|----------|-------------|
| `GEMINI_API_KEY` | Google AI API Key (Pflicht für KI-Features) |
| `JWT_SECRET` | Sicherer zufälliger String (32+ Zeichen) — NIE default lassen! |
| `DATABASE_URL` | PostgreSQL Connection String |
| `DEV_MODE` | `true` für Development (Demo-User ohne Login) |
```

---

## ABSCHLUSSKONTROLLE FÜR AGENT C

1. `.env.example` einvollständig mit allen Variablen und Kommentaren
2. `docker-compose.prod.yml` hat keine Code-Volume-Mounts, nutzt Gunicorn und `node server.js`
3. `backend/.dockerignore` und `frontend/.dockerignore` erstellt
4. `.github/workflows/ci.yml` erstellt — Tests laufen via GitHub Actions
5. Security Headers Middleware in `main.py` hinzugefügt
6. JWT Secret Sicherheitswarnung in `config.py` hinzugefügt
7. Nginx Rate Limiting für `/api/auth/` (streng: 5/min) und `/api/` (30/min) konfiguriert
8. `README.md` mit Quickstart, Tests und Architektur-Übersicht
9. Strukturiertes Logging in `main.py`

**Führe zum Schluss aus:**
```bash
# Docker-Build testen:
docker compose build
echo "Build erfolgreich — alle Docker-Images kompilieren"
```
