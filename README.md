# TrainIQ — KI Trainingscoach

KI-gestützter Trainingscoach für Ausdauersportler. Analysiert Biometrie (HRV, Schlaf, Stress), erstellt personalisierte Trainingspläne und gibt Echtzeit-Coaching via Chat.

## Features
- 🤖 KI-Coach (LLM) mit Echtzeit-Streaming
- 📊 Recovery Scoring aus HRV, Schlaf und Stress
- 🏃 Personalisierte Trainingspläne (Laufen, Radfahren, Schwimmen, Triathlon)
- 📷 Mahlzeiten-Analyse via Foto-Upload (Cloudinary)
- ⌚ Strava-Integration für automatische Datensynchronisation
- 📱 PWA-fähig — Installation auf iPhone/Android möglich

## Schnellstart

### Voraussetzungen
- Docker + Docker Compose
- LLM API Key (OpenAI-kompatible API erforderlich)

### Setup & Start

```bash
# Repository klonen
git clone <repo-url> && cd trainiq

# Environment konfigurieren
cp .env.example .env
# Öffne .env und setze LLM_API_KEY und ändere JWT_SECRET!

# Starten (Development — mit Hot-Reload)
docker compose up --build

# App öffnen
open http://localhost
```

Im Dev-Modus (`DEV_MODE=true`) ist kein Login nötig — ein Demo-User ist automatisch eingeloggt.

### Tests ausführen

```bash
cd backend
pip install pytest pytest-asyncio httpx aiosqlite
python -m pytest tests/ -v
```

### Production Deploy

```bash
# .env anpassen: DEV_MODE=false, JWT_SECRET auf sicheren Wert setzen
docker compose -f docker-compose.prod.yml up --build -d
```

## Architektur

```
nginx (Port 80)
  ├── /api/         → FastAPI Backend (Port 8000)
  └── /             → Next.js Frontend (Port 3000)

Backend:   FastAPI + SQLAlchemy + PostgreSQL + Redis
Frontend:  Next.js 14 (App Router) + Tailwind CSS
KI:        LLM (OpenAI-kompatible API)
```

## Wichtige Environment-Variablen

| Variable | Beschreibung | Pflicht |
|----------|-------------|---------|
| `LLM_API_KEY` | API Key für LLM-Provider (OpenAI-kompatibel) | ✅ |
| `LLM_BASE_URL` | Base URL des LLM-Providers | ✅ |
| `LLM_MODEL` | Modellname (z.B. gpt-4o-mini, llama3.1) | ✅ |
| `JWT_SECRET` | Sicherer zufälliger String (32+ Zeichen) | ✅ |
| `DATABASE_URL` | PostgreSQL Connection String | ✅ |
| `DEV_MODE` | `true` = Demo-User, kein Login nötig | — |
| `STRAVA_CLIENT_ID` | Für Strava-Integration (optional) | — |
| `CLOUDINARY_*` | Für Foto-Upload (optional) | — |

## CI/CD

GitHub Actions führt automatisch aus:
- Backend Tests (pytest) auf jedem Push
- Frontend TypeScript-Check + Build-Verifikation

Workflow: `.github/workflows/ci.yml`

## Security

- JWT_SECRET-Warnung bei Verwendung des Standard-Dev-Werts
- Security Headers: X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy
- Rate Limiting: API (30 req/min), Auth (5 req/min)
- Connection Limits pro IP
- HSTS (Strict Transport Security)
- Nginx Version versteckt
