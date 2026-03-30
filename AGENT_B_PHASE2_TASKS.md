# AGENT B — Phase 2: Frontend, UX, Offline & Gamification

> **Priorität: MITTEL bis HOCH** — Fokus liegt auf User-Bindung (Retention) und besserer Offline-Fähigkeit.
> **Arbeitsverzeichnis:** `/Users/abu/Projekt/trainiq/frontend/src/`

---

## 1. Offline Mode & Erweitertes PWA Setup

Wenn der User im Fitnessstudio ist und keinen guten Empfang hat, darf die App nicht kaputt aussehen.
**Ziel:**
- Registriere einen komplexeren Service Worker (z.B. mit `workbox`).
- Cache wichtige API-Endpunkte für Training (`/api/training/plan`) und Metriken offline in die `IndexedDB`.
- Zeige einen kleinen Indikator an ("Sie sind offline"), erlaube es dem User aber, seinen heutigen Trainingsplan weiterhin zu sehen und abzuhaken. Eine Synchronisierung erfolgt automatisch sobald das Internet wieder da ist (Background Sync).

## 2. Web Push Notifications

Um den User zu motivieren, müssen wir ihn aktiv erreichen.
**Ziel:**
- Bitte den User im Dashboard (oder in den Einstellungen) Push-Benachrichtigungen zu aktivieren.
- Hole einen Push-Token vom Browser und sende ihn ans Backend.
- Lausche im Service Worker auf Notifications (z.B. "Dein wöchentlicher Trainingsplan ist fertig!" oder "Vergiss dein Workout heute Abend nicht.").

## 3. Gamification System (Streaks & Achievements)

Ein Workout-Plan allein motiviert manche nicht genug.
**Ziel:**
- Baue eine "Streak"-Anzeige oben rechts in der Navigation ein (🔥 5 Tage in Folge trainiert / eingeloggt).
- Baue eine Badge/Medaillen-Sektion in die Profil-Seite ein (z.B. für "Erster 10km Lauf abgeschlossen" oder "7 Tage lang perfekte Recovery").

## 4. Internationalisierung (i18n)

Aktuell ist das Projekt deutsch. Ein Skalieren fordert Mehrsprachigkeit.
**Ziel:**
- Setup von `next-intl` oder ähnlichen Libraries.
- Ersetze harte deutsche Strings durch Keys.
- Einstellungs-Seite um die Sprache des UI (und der KI) zwischen Deutsch und Englisch umzuschalten.

## 5. Skeleton Loaders für alle Seiten

Aktuell hat nur das Dashboard Skeleton-Loaders.
**Ziel:**
- Baue fließende Skeleton-Loaders für den Chat (Nachrichten-Lade-Indikator).
- Baue Skeletons für die Trainings-Ansicht, während der Tagesplan geladen wird.
