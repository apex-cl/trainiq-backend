# AGENT A — Phase 2: Backend, Advanced AI & Background Tasks

> **Priorität: MITTEL bis HOCH** — Fokus liegt auf Background-Processing, Langzeit-Gedächtnis der KI und E-Mails.
> **Arbeitsverzeichnis:** `/Users/abu/Projekt/trainiq/backend/`

---

## 1. Long-Term AI Memory (RAG mit pgvector)

Aktuell vergisst der KI-Coach alte Chatverläufe oder spezifische Vorlieben, wenn der Kontext-Window-Limit erreicht ist (oder nutzt nur die letzten Nachrichten). 
**Ziel:**
- Nutze das PostgreSQL `pgvector` Plugin.
- Speichere wichtige extrahierte Fakten aus Benutzer-Chats (z.B. Verletzungen, Lieblingsessen, Ziele) als Vektor-Embeddings (via Gemini Embeddings API).
- Hole bei jedem Chat-Aufruf relevante alte Vorlieben aus der DB und übergib sie als System-Prompt.

## 2. Asynchrone Background Worker (Celery / ARQ)

Aktuell werden lange Aufgaben (wie Trainingsplangenerierung oder API Calls für Strava-Sync) synchron innerhalb des Requests verarbeitet.
**Ziel:**
- Implementiere einen Message-Broker (Redis wird ja schon genutzt) und nutze `ARQ` (Async Redis Queue) oder `Celery`.
- Lagere KI-Trainingsplan-Generierung in Background-Worker aus und informiere das Frontend via WebSockets/SSE, wenn der Plan fertig ist.

## 3. Strava Webhooks Integration

Aktuell muss der User vermutlich die App öffnen oder einen Button klicken, um Strava-Aktivitäten zu synchronisieren.
**Ziel:**
- Erstelle Endpoint `/api/watch/strava/webhook` zur Validierung und zum Empfang von Echtzeit-Events von Strava.
- Wenn der User einen Lauf beendet, schickt Strava einen Ping. Der Background-Worker lädt die Aktivität herunter, verrechnet die Belastung und lässt die KI den Trainingsplan sofort dynamisch anpassen.

## 4. E-Mail Service & Notifications

**Ziel:**
- Setup eines E-Mail-Clients (z.B. `aiosmtplib` oder API-Clients für Resend / SendGrid).
- **Welcome-E-Mail:** Nach erfolgreicher Registrierung.
- **Passwort vergessen:** Secure Token generieren und Reset-Link verschicken.
- **Wöchentlicher Report:** Löst jeden Sonntagabend durch den Scheduler einen Job aus, der eine Zusammenfassung der Woche (Puls, verbrannte Kalorien, erledigte Trainings) generiert und per Mail verschickt.
