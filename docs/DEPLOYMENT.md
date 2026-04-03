# Deployment: Self-Hosted auf Oracle Cloud (eigene Domain)

## Architektur

```
Oracle Cloud VM
├── nginx          → :443  eigene Domain  (trainiq.example.com)
├── frontend       → :3000 Next.js (interner Container)
├── backend        → :8000 FastAPI (interner Container)
├── postgres       → :5432 (intern)
├── redis          → :6379 (intern)
├── scheduler
├── worker
└── certbot        → automatische Let's-Encrypt-Erneuerung
```

GitHub Actions deployed per SSH auf die VM — kein externer Dienst (kein Vercel).

---

## Server-Setup (einmalig)

```bash
# 1. Repo klonen
git clone https://github.com/<org>/trainiq.git ~/trainiq
cd ~/trainiq

# 2. .env anlegen
cp .env.example .env
nano .env      # DOMAIN, FRONTEND_URL, JWT_SECRET, DB-Passwörter setzen

# 3. OCI Security List + iptables: Ports 80 + 443 freigeben
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT

# 4. SSL-Zertifikat
bash init-letsencrypt.sh

# 5. Stack starten
docker compose -f docker-compose.backend.yml up -d
```

### Wichtige .env-Werte

```env
DOMAIN=trainiq.example.com
FRONTEND_URL=https://trainiq.example.com
NEXT_PUBLIC_API_URL=https://trainiq.example.com/api
BACKEND_URL=http://backend:8000
```

---

## GitHub Actions Secrets

| Secret | Beschreibung |
|---|---|
| `ORACLE_HOST` | Öffentliche IP der OCI-Instanz |
| `ORACLE_USER` | SSH-Benutzer (`ubuntu` oder `opc`) |
| `ORACLE_SSH_KEY` | Privater SSH-Schlüssel (Inhalt von `~/.ssh/id_rsa`) |
| `ORACLE_SSH_PORT` | SSH-Port (optional, Standard `22`) |

---

## DNS

| Record | Typ | Ziel |
|---|---|---|
| `trainiq.example.com` | A | Öffentliche IP der OCI-Instanz |
| `www.trainiq.example.com` | CNAME | `trainiq.example.com` |

---

## Deploy-Ablauf (automatisch via GitHub Actions)

Bei jedem Push auf `main` (wenn `backend/**` oder `frontend/**` geändert):

1. SSH auf Oracle-VM
2. `git pull origin main`
3. `docker compose build --pull backend scheduler worker frontend`
4. `docker compose up -d migrate backend scheduler worker frontend nginx`
5. Alte Images bereinigen
