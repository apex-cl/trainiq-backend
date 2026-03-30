# PROMPT FÜR AGENT A — Foundation

Kopiere alles zwischen den Strichen in einen neuen Chat.

---

Du bist ein erfahrener Senior Software Engineer. Deine einzige Aufgabe in diesem Chat ist es,
die **komplette Projektstruktur und alle Grundlagen** für das Projekt "TrainIQ" aufzubauen.
Du schreibst KEINEN Business-Logik-Code. Du legst nur das Fundament.

## PFLICHT: Lies zuerst diese Datei komplett

Die Datei `/Users/abu/Projekt/app/BLUEPRINT.md` enthält ALLE Spezifikationen.
Lies sie vollständig bevor du anfängst. Sie definiert:
- Die exakte Ordnerstruktur
- Den gesamten Tech Stack
- Das Datenbank-Schema
- Das Design System
- Alle Fehler die vermieden werden müssen

Das Arbeitsverzeichnis für das neue Projekt ist: `/Users/abu/Projekt/trainiq/`

---

## Deine Aufgaben (in dieser Reihenfolge)

### 1. Docker Compose Setup

Erstelle `/Users/abu/Projekt/trainiq/docker-compose.yml` mit diesen 7 Services:
- `postgres` (postgres:16-alpine) — Port 5432, Volume, Healthcheck
- `redis` (redis:7-alpine) — Port 6379, Volume, Healthcheck
- `minio` (minio/minio:latest) — Port 9000+9001, Volume, Healthcheck
- `backend` (build: ./backend) — Port 8000, depends_on postgres+redis (healthy), Volume Mount für Hot-Reload, Command: `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- `scheduler` (build: ./backend) — depends_on postgres+redis (healthy), Command: `python -m app.scheduler.runner`
- `frontend` (build: ./frontend) — Port 3000, depends_on backend, Volume Mount für Hot-Reload, Command: `npm run dev`
- `nginx` (nginx:alpine) — Port 80, depends_on backend+frontend, Volume: ./nginx/nginx.conf

Alle Services bekommen `env_file: .env` und `restart: unless-stopped`.

### 2. Nginx Konfiguration

Erstelle `/Users/abu/Projekt/trainiq/nginx/nginx.conf`:
- `/api/` → proxy zu `http://backend:8000/` (strip /api prefix)
- `/api/coach/chat` → proxy mit WebSocket Upgrade Headers
- `/` → proxy zu `http://frontend:3000`
- Setze alle nötigen proxy_set_header

### 3. Umgebungsvariablen

Erstelle `/Users/abu/Projekt/trainiq/.env` mit den Werten aus BLUEPRINT.md (Abschnitt "Umgebungsvariablen").
Erstelle `/Users/abu/Projekt/trainiq/.env.example` mit denselben Keys aber leeren Werten + Kommentaren.
Erstelle `/Users/abu/Projekt/trainiq/.gitignore` — `.env` muss drin sein.

### 4. Datenbank Schema

Erstelle `/Users/abu/Projekt/trainiq/postgres/init.sql` mit dem EXAKTEN Schema aus BLUEPRINT.md (Abschnitt "Datenbank Schema"). Kein Zeichen ändern.

### 5. Backend Grundstruktur

#### 5a. Dockerfile
Erstelle `/Users/abu/Projekt/trainiq/backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
```

#### 5b. requirements.txt
Erstelle `/Users/abu/Projekt/trainiq/backend/requirements.txt` mit EXAKT diesen Versionen:
```
fastapi==0.111.0
uvicorn[standard]==0.30.1
sqlalchemy[asyncio]==2.0.30
asyncpg==0.29.0
alembic==1.13.1
pydantic==2.7.1
pydantic-settings==2.3.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9
httpx==0.27.0
redis==5.0.4
apscheduler==3.10.4
minio==7.2.7
google-generativeai==0.5.4
Pillow==10.3.0
python-dotenv==1.0.1
```

#### 5c. app/core/config.py
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    minio_endpoint: str
    minio_user: str
    minio_password: str
    minio_bucket: str = "nutrition-photos"
    gemini_api_key: str
    jwt_secret: str
    jwt_expire_minutes: int = 10080

    class Config:
        env_file = ".env"

settings = Settings()
```

#### 5d. app/core/database.py
Async SQLAlchemy Setup mit `create_async_engine`, `AsyncSession`, `get_db` Dependency.
Engine URL: `settings.database_url.replace("postgresql://", "postgresql+asyncpg://")`.
`get_db` als async generator mit `async_sessionmaker`.

#### 5e. app/core/security.py
JWT Funktionen: `create_access_token(data: dict)`, `verify_token(token: str)`.
Password Funktionen: `hash_password(password: str)`, `verify_password(plain, hashed)`.
OAuth2PasswordBearer scheme für `/auth/login`.

#### 5f. app/models/ — Alle SQLAlchemy Models
Erstelle alle 7 Model-Dateien aus BLUEPRINT.md Projektstruktur.
Verwende SQLAlchemy 2.0 Mapped Column Syntax:
```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, Integer, Boolean, DateTime, JSON, ForeignKey
from datetime import datetime
import uuid

class Base(DeclarativeBase):
    pass
```

Jede Model-Datei enthält NUR die Model-Klasse — keine Business Logik.

#### 5g. app/api/dependencies.py
```python
async def get_current_user(token = Depends(oauth2_scheme), db = Depends(get_db)):
    # Token verifizieren, User aus DB laden, zurückgeben
    # Bei Fehler: HTTPException 401
```

#### 5h. app/api/routes/ — STUB Routen
Erstelle alle 6 Route-Dateien (auth, coach, training, metrics, nutrition, watch).
Jede Route gibt erstmal `{"status": "ok", "route": "NAME"}` zurück.
ABER: Definiere alle Endpoints mit korrekten Pfaden und HTTP-Methoden aus BLUEPRINT.md.
Schreibe Docstrings in jeden Endpoint was er tun WIRD.

#### 5i. main.py
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import auth, coach, training, metrics, nutrition, watch

app = FastAPI(title="TrainIQ API", version="1.0.0")

app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,      prefix="/auth",      tags=["auth"])
app.include_router(coach.router,     prefix="/coach",     tags=["coach"])
app.include_router(training.router,  prefix="/training",  tags=["training"])
app.include_router(metrics.router,   prefix="/metrics",   tags=["metrics"])
app.include_router(nutrition.router, prefix="/nutrition", tags=["nutrition"])
app.include_router(watch.router,     prefix="/watch",     tags=["watch"])

@app.get("/health")
async def health():
    return {"status": "ok"}
```

#### 5j. app/scheduler/runner.py
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio

scheduler = AsyncIOScheduler()

# Jobs hier registrieren (später implementiert von Agent B)
# scheduler.add_job(sync_watch_data, 'interval', hours=4)
# scheduler.add_job(generate_tomorrow_plan, 'cron', hour=21)

if __name__ == "__main__":
    scheduler.start()
    asyncio.get_event_loop().run_forever()
```

#### 5k. app/services/ — STUB Services
Erstelle alle 5 Service-Dateien mit leeren Klassen/Funktionen und Docstrings.
Klassen: `CoachAgent`, `TrainingPlanner`, `NutritionAnalyzer`, `WatchSync`, `RecoveryScorer`.

### 6. Frontend Grundstruktur

#### 6a. Dockerfile
```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
```

#### 6b. package.json
Erstelle mit diesen Dependencies:
```json
{
  "dependencies": {
    "next": "14.2.3",
    "react": "^18",
    "react-dom": "^18",
    "@tanstack/react-query": "^5.40.0",
    "axios": "^1.7.2",
    "recharts": "^2.12.7",
    "framer-motion": "^11.2.10",
    "zustand": "^4.5.2",
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.3.0",
    "lucide-react": "^0.390.0"
  },
  "devDependencies": {
    "typescript": "^5",
    "@types/node": "^20",
    "@types/react": "^18",
    "@types/react-dom": "^18",
    "tailwindcss": "^3.4.4",
    "autoprefixer": "^10.4.19",
    "postcss": "^8.4.38"
  }
}
```

#### 6c. tailwind.config.ts
EXAKT das Design System aus BLUEPRINT.md implementieren (Abschnitt "Design System").
Farben, Fonts alles aus BLUEPRINT.md. Keine Abweichungen.

#### 6d. src/app/layout.tsx
- Google Fonts importieren: VT323, Share Tech Mono, Inter (via next/font/google)
- HTML Grundstruktur mit bg-bg Klasse
- ReactQueryProvider wrapper

#### 6e. src/lib/api.ts
Axios Instance mit:
- `baseURL: process.env.NEXT_PUBLIC_API_URL`
- Request Interceptor: Bearer Token aus localStorage anhängen
- Response Interceptor: 401 → redirect zu /login

#### 6f. src/lib/types.ts
TypeScript Interfaces für ALLE Datenmodelle (User, HealthMetrics, TrainingPlan, NutritionLog, Conversation, RecoveryScore, DailyWellbeing, UserGoal, WatchConnection).

#### 6g. Alle Seiten als STUB anlegen
Erstelle alle Seiten aus der Projektstruktur.
Jede Seite gibt erstmal `<div>PAGE NAME</div>` zurück.
ABER: Schreibe Kommentare in jede Seite was sie enthalten WIRD.

#### 6h. src/app/(app)/layout.tsx — App Shell
Bottom Navigation mit den 5 Tabs (Dashboard, Training, Coach, Ernährung, Metriken).
Aktiver Tab basierend auf `usePathname()`.
Design EXAKT wie in BLUEPRINT.md.

#### 6i. shadcn/ui initialisieren
Führe aus: `npx shadcn-ui@latest init` mit diesen Einstellungen (schreibe die config.json direkt):
- style: default
- baseColor: slate
- cssVariables: true

Installiere diese shadcn Komponenten (schreibe die Dateien direkt in src/components/ui/):
Button, Input, Card, Badge, Separator, ScrollArea, Sheet, Dialog

---

## Abschluss-Checkliste (ALLE Punkte müssen erfüllt sein)

Nach deiner Arbeit muss folgendes funktionieren:

```bash
cd /Users/abu/Projekt/trainiq
docker compose up --build
```

- [ ] `docker compose up --build` läuft ohne Fehler durch
- [ ] `http://localhost/health` → `{"status": "ok"}`
- [ ] `http://localhost:3000` → Next.js Seite lädt
- [ ] `http://localhost/api/health` → `{"status": "ok"}` (via Nginx)
- [ ] `http://localhost:9001` → MinIO Console erreichbar
- [ ] Alle 7 Docker Container sind `healthy` oder `running`
- [ ] `http://localhost/api/docs` → FastAPI Swagger UI mit allen Endpoints

## Was du NICHT tust

- KEIN echter Business-Logik Code (kein Gemini API Call, kein Garmin Sync, keine ML)
- KEINE echten Daten in den Endpoints zurückgeben (nur Stub-Antworten)
- KEINE Tests schreiben
- KEINE CI/CD Pipeline
- NICHT von der BLUEPRINT.md abweichen
