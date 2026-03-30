#!/bin/bash
#
# provision-server.sh — TrainIQ Server Provisioning (Infrastructure as Code)
#
# Führt ein blankes Ubuntu 22.04+ Server zum produktionsbereiten TrainIQ-Server auf.
# Usage:
#   ./provision-server.sh <ssh-user>@<server-ip>
#
# Beispiel:
#   ./provision-server.sh root@203.0.113.42
#   ./provision-server.sh ubuntu@trainiq.example.com
#
# Voraussetzungen:
#   - SSH-Zugang zum Server (Passwort oder Key)
#   - Server läuft Ubuntu 22.04 oder neuer
#   - Lokal installiert: ssh, scp

set -euo pipefail

# === Konfiguration ===
REPO_URL="${REPO_URL:-https://github.com/dein-org/trainiq.git}"
APP_DIR="/opt/trainiq"
BRANCH="main"

# === Argumente prüfen ===
if [ $# -lt 1 ]; then
    echo "Usage: $0 <ssh-user>@<server-ip>"
    echo "Beispiel: $0 root@203.0.113.42"
    exit 1
fi

SERVER="$1"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

echo "=== TrainIQ Server Provisioning ==="
echo "Server: $SERVER"
echo "Repo:   $REPO_URL"
echo "App:    $APP_DIR"
echo ""

# SSH-Funktion
remote() {
    ssh $SSH_OPTS "$SERVER" "$@"
}

# Prüfen ob Server erreichbar ist
echo ">> Server-Verbindung testen..."
if ! remote "echo 'OK'" > /dev/null 2>&1; then
    echo "FEHLER: Server $SERVER ist nicht erreichbar!"
    exit 1
fi
echo "   Verbindung OK."

# === 1. System aktualisieren ===
echo ">> System aktualisieren..."
remote "apt-get update && apt-get upgrade -y"

# === 2. Basis-Tools installieren ===
echo ">> Basis-Tools installieren..."
remote "apt-get install -y \
    curl \
    git \
    ufw \
    fail2ban \
    unattended-upgrades \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    htop \
    jq"

# === 3. Docker installieren ===
echo ">> Docker installieren..."
remote "bash -s" <<'DOCKER_INSTALL'
# Docker GPG Key
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

# Docker Repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > \
    /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Docker ohne sudo nutzbar
systemctl enable docker
systemctl start docker
DOCKER_INSTALL

# === 4. Firewall (UFW) konfigurieren ===
echo ">> Firewall konfigurieren..."
remote "bash -s" <<'FIREWALL'
ufw --force reset
ufw default deny incoming
ufw default allow outgoing

# Nur notwendige Ports öffnen
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'

# SSH brute-force Schutz
ufw limit 22/tcp

# Firewall aktivieren
ufw --force enable
ufw status verbose
FIREWALL

# === 5. Fail2ban konfigurieren ===
echo ">> Fail2ban konfigurieren..."
remote "bash -s" <<'FAIL2BAN'
cat > /etc/fail2ban/jail.local <<EOF
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 86400
EOF

systemctl enable fail2ban
systemctl restart fail2ban
FAIL2BAN

# === 6. Automatische Sicherheitsupdates ===
echo ">> Automatische Sicherheitsupdates aktivieren..."
remote "bash -s" <<'AUTO_UPDATES'
cat > /etc/apt/apt.conf.d/20auto-upgrades <<EOF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

systemctl enable unattended-upgrades
systemctl start unattended-upgrades
AUTO_UPDATES

# === 7. App-Verzeichnis erstellen & Repo klonen ===
echo ">> Repository klonen..."
remote "bash -s" <<REPO_SETUP
if [ -d "$APP_DIR" ]; then
    echo "Verzeichnis $APP_DIR existiert bereits. Pulling latest..."
    cd "$APP_DIR"
    git fetch origin
    git checkout $BRANCH
    git pull origin $BRANCH
else
    git clone -b $BRANCH "$REPO_URL" "$APP_DIR"
fi
REPO_SETUP

# === 8. .env Setup ===
echo ">> .env konfigurieren..."
remote "bash -s" <<ENV_SETUP
cd "$APP_DIR"
if [ ! -f .env ]; then
    cp .env.example .env

    # JWT Secret generieren
    JWT_SECRET=\$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
    sed -i "s/AENDERN_VOR_DEPLOYMENT/\$JWT_SECRET/" .env

    echo ".env erstellt — BITTE: DOMAIN, SENTRY_DSN und andere Werte manuell setzen!"
    echo "  nano $APP_DIR/.env"
else
    echo ".env existiert bereits — überspringe."
fi
ENV_SETUP

# === 9. Docker Images bauen & starten ===
echo ">> Docker Container starten..."
remote "bash -s" <<DEPLOY
cd "$APP_DIR"
docker compose -f docker-compose.prod.yml pull 2>/dev/null || true
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
DEPLOY

# === 10. Health Check ===
echo ">> Health Check..."
sleep 10
REMOTE_HEALTH=$(remote "curl -sf http://localhost:8000/health 2>/dev/null || echo 'FAIL'")
if echo "$REMOTE_HEALTH" | grep -q '"status"'; then
    echo "   Backend: OK"
else
    echo "   Backend: WARNUNG — Health Check fehlgeschlagen (kann normal sein beim ersten Start)"
fi

# === Zusammenfassung ===
echo ""
echo "============================================="
echo "  TrainIQ Server Provisioning abgeschlossen!"
echo "============================================="
echo ""
echo "Nächste Schritte:"
echo "  1. SSH zum Server: ssh $SERVER"
echo "  2. .env anpassen:  nano $APP_DIR/.env"
echo "     → DOMAIN, ADMIN_EMAIL setzen"
echo "     → SENTRY_DSN setzen (optional)"
echo "     → S3_BACKUP_BUCKET setzen (optional)"
echo "  3. SSL aktivieren: cd $APP_DIR && ./init-letsencrypt.sh"
echo "  4. Logs prüfen:   docker compose -f docker-compose.prod.yml logs -f"
echo ""
echo "Firewall Status:"
remote "ufw status" 2>/dev/null || echo "  (konnte nicht abgerufen werden)"
