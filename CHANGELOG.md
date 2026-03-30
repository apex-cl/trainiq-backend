# Changelog

## [1.1.0] - 2026-03-29

### Sicherheitsfixes (Kritisch)

#### XSS-Schutz
- **Frontend**: `dangerouslySetInnerHTML` in Chat-Seite durch DOMPurify geschützt
  - Datei: `src/app/(app)/chat/page.tsx`
  - Hinzugefügt: DOMPurify-Sanitization mit erlaubten Tags/Attributen
  - Verhindert XSS-Angriffe über KI-generierte Inhalte

#### CORS-Konfiguration
- **Backend**: Flexible CORS-Konfiguration für Produktion
  - Datei: `backend/main.py`
  - Hinzugefügt: `ADDITIONAL_CORS_ORIGINS` Umgebungsvariable
  - Unterstützt komma-getrennte Liste zusätzlicher Origins

### Bugfixes

#### Backend
1. **Strava API URL korrigiert**
   - Datei: `backend/main.py:270`
   - Fix: `https://www.strava.com/api/v3athlete` → `https://www.strava.com/api/v3/athlete`
   - Betroffen: Health-Check Endpoint

2. **Division durch Null verhindert**
   - Datei: `backend/app/api/routes/coach.py:199-203`
   - Fix: `days = len(logs) or 1` statt feste `days = 7`
   - Betroffen: Nutrition-Gaps Endpoint

3. **Race Condition bei Gast-Nachrichtenzähler**
   - Datei: `backend/app/api/routes/coach.py:57-68`
   - Fix: Atomic increment via SQL UPDATE
   - Verhindert parallele Zählerinkremente

#### Frontend
4. **Onboarding-Step-Logik korrigiert**
   - Datei: `src/app/onboarding/page.tsx`
   - Fix: `step === 4` → `step === 3`
   - Fix: "Schritt 3/4" → "Schritt 2/3" und "Schritt 3/3"
   - Betroffen: Onboarding-Flow

5. **Offline-Sync: Fehlgeschlagene Aktionen behalten**
   - Datei: `src/lib/offline.ts:87-110`
   - Fix: Nur erfolgreiche Aktionen aus Queue löschen
   - Fehlgeschlagene Aktionen bleiben für nächsten Sync-Versuch

### Design-Verbesserungen

1. **Nginx Location-Reihenfolge korrigiert**
   - Datei: `nginx/nginx.dev.conf`
   - Fix: Spezifischere Regeln (`/api/coach/chat`) vor allgemeinen (`/api/`)
   - SSE-Streaming funktioniert jetzt korrekt

2. **React-Version konsistent**
   - Datei: `frontend/package.json`
   - Fix: `react: "^18"` → `react: "18.3.1"`
   - Gleiche Version wie react-dom

3. **Tailwind Content-Pfade erweitert**
   - Datei: `frontend/tailwind.config.ts`
   - Hinzugefügt: `./src/hooks/**/*.{js,ts}` und `./src/lib/**/*.{js,ts}`

4. **DOMPurify Abhängigkeit hinzugefügt**
   - Datei: `frontend/package.json`
   - Hinzugefügt: `dompurify: "^3.1.0"`

### Abhängigkeiten

1. **Version-Pinning für unsichere Pakete**
   - Datei: `backend/requirements.txt`
   - `pyotp>=2.9.0` → `pyotp>=2.9.0,<3.0.0`
   - `stripe>=8.0.0` → `stripe>=8.0.0,<9.0.0`
   - `greenlet>=3.0.0` → `greenlet>=3.0.0,<4.0.0`

### Konfiguration

1. **.env.example aktualisiert**
   - Hinzugefügt: `ADDITIONAL_CORS_ORIGINS`
   - Hinzugefügt: `STRIPE_*` Variablen
   - Hinzugefügt: `VAPID_*` Variablen
   - Hinzugefügt: `GARMIN_*` Variablen

### Tests

1. **Offline-Sync Tests hinzugefügt**
   - Datei: `src/test/offline.test.ts`
   - Testet: Nur erfolgreiche Aktionen werden gelöscht

2. **XSS-Schutz Tests hinzugefügt**
   - Datei: `src/test/xss-protection.test.ts`
   - Testet: DOMPurify blockiert verschiedene XSS-Vektoren

---

## Technische Details

### Betroffene Dateien

| Datei | Änderung | Priorität |
|-------|----------|-----------|
| `frontend/src/app/(app)/chat/page.tsx` | XSS-Schutz via DOMPurify | Kritisch |
| `frontend/src/app/onboarding/page.tsx` | Step-Logik korrigiert | Hoch |
| `frontend/src/lib/offline.ts` | Sync-Logik verbessert | Hoch |
| `frontend/package.json` | DOMPurify + React-Version | Mittel |
| `frontend/tailwind.config.ts` | Content-Pfade erweitert | Niedrig |
| `backend/main.py` | Strava URL + CORS | Kritisch |
| `backend/app/api/routes/coach.py` | Division/Null + Race Condition | Hoch |
| `backend/requirements.txt` | Version-Pinning | Mittel |
| `nginx/nginx.dev.conf` | Location-Reihenfolge | Mittel |
| `.env.example` | Neue Variablen | Niedrig |
| `src/test/offline.test.ts` | Neue Tests | Niedrig |
| `src/test/xss-protection.test.ts` | Neue Tests | Niedrig |

### Kompatibilität

- **Python**: 3.12
- **FastAPI**: 0.111.0
- **Next.js**: 14.2.3
- **React**: 18.3.1
- **PostgreSQL**: 16 mit pgvector
- **Redis**: 7

### Migration

Keine Datenbank-Migration erforderlich.

### Deployment

1. `docker-compose down`
2. `docker-compose build --no-cache`
3. `docker-compose up -d`
4. Frontend-Tests ausführen: `npm run test`
