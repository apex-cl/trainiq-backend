# AGENT C — Phase 2: Infrastruktur, Automatisierung & Security (Enterprise)

> **Priorität: HOCH** — Bevor echte User-Daten das System fluten, müssen Backups, HTTPS und Fehler-Tracking sitzen.
> **Arbeitsverzeichnis:** `/Users/abu/Projekt/trainiq/`

---

## 1. Automatisiertes HTTPS / SSL via Let's Encrypt

Aktuell lauscht der Nginx-Container nur auf Port 80 (HTTP). Das ist für Production absolut unzureichend (Benutzerpasswörter übertragen via Plaintext!).
**Ziel:**
- Konfiguriere einen Certbot-Container für Nginx (`docker-compose.prod.yml`).
- Automatisiere das Abrufen von SSL-Zertifikaten (Let's Encrypt) für eine simulierte oder echte Domain.
- Optimiere `nginx.conf` so, dass HTTP-Requests immer auf HTTPS (Port 443) weitergeleitet werden und HSTS aktiviert ist.

## 2. Automatisierte Cloud-Backups (PostgreSQL)

Ein Serverausfall darf nicht zum Verlust von Trainingsdaten führen.
**Ziel:**
- Erstelle einen neuen Docker-Service (`db-backup`) in Production.
- Schreibe ein Cronjob-Script (Alpine + `pg_dump`), das nachts um 03:00 Uhr die komplette PostgreSQL-Datenbank dumpt.
- Lade den Dump z.B. automatisiert via AWS CLI auf einen S3 Bucket hoch (oder in ein anderes Backup-Verzeichnis) und lösche Dumps, die älter als 7 Tage sind.

## 3. Centralized Logging & Error Tracking (Sentry)

Logs im Container-Stdout (`docker logs`) reichen bei Skalierung nicht zur Fehleranalyse aus.
**Ziel:**
- Füge Sentry (`sentry-sdk`) ins FastAPI-Backend ein.
- Füge Sentry ins Next.js-Frontend ein (inklusive Source-Maps Lade-Support).
- Führe alle Error-Logs zentralisiert zusammen um Frontend-Bugs (z.B. React Crashes) und Backend HTTP-500 Fehler sofort per E-Mail an Admins zu senden.

## 4. Infrastructure as Code (IaC) & Advanced Deployment

Sollte der TrainIQ Server sterben, muss ein neuer sofort hochgefahren werden können.
**Ziel:**
- Schreibe ein Bash-Script oder ein einfaches `Ansible`-Playbook/`Terraform`-HCL-File für das Server-Provisioning.
- Das Script loggt sich per SSH in einen blanken Ubuntu-Server ein, installiert Docker, Firewall-Regeln (UFW, schließt alle Ports außer 80, 443 und 22), klont das Repo und führt den Startbefehl durch.
