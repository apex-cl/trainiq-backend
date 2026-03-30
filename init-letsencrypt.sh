#!/bin/bash
#
# init-letsencrypt.sh — Erstmalige SSL-Zertifikate via Let's Encrypt abrufen
#
# Voraussetzungen:
#   1. DNS-Eintrag für DOMAIN zeigt auf diesen Server
#   2. Port 80 ist von außen erreichbar
#   3. .env enthält DOMAIN=deinedomain.de und ADMIN_EMAIL=admin@example.com
#
# Usage: chmod +x init-letsencrypt.sh && ./init-letsencrypt.sh

set -euo pipefail

# .env laden
if [ -f .env ]; then
    export $(grep -E '^(DOMAIN|ADMIN_EMAIL)=' .env | xargs)
fi

if [ -z "${DOMAIN:-}" ]; then
    echo "FEHLER: DOMAIN ist nicht in .env gesetzt!"
    echo "Füge DOMAIN=deinedomain.de zu .env hinzu."
    exit 1
fi

if [ -z "${ADMIN_EMAIL:-}" ]; then
    echo "FEHLER: ADMIN_EMAIL ist nicht in .env gesetzt!"
    echo "Füge ADMIN_EMAIL=admin@example.com zu .env hinzu."
    exit 1
fi

echo "=== TrainIQ Let's Encrypt Initialisierung ==="
echo "Domain: $DOMAIN"
echo "E-Mail: $ADMIN_EMAIL"
echo ""

# Pfade
CERTS_PATH="./certbot/conf/live/$DOMAIN"
DATA_PATH="./certbot/www"

# Prüfen ob Zertifikate bereits existieren
if [ -d "$CERTS_PATH" ]; then
    echo "Zertifikate für $DOMAIN existieren bereits."
    read -p "Zertifikate erneuern? (j/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Jj]$ ]]; then
        echo "Abgebrochen."
        exit 0
    fi
fi

echo ">> Temporäre Nginx-Konfiguration ohne SSL erstellen..."
cat > ./nginx/nginx-ssl-staging.conf <<EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 200 'TrainIQ SSL-Initialisierung laeuft...';
        add_header Content-Type text/plain;
    }
}
EOF

# Backup aktuelle nginx.conf und staging verwenden
cp ./nginx/nginx.conf ./nginx/nginx.conf.bak
cp ./nginx/nginx-ssl-staging.conf ./nginx/nginx.conf

echo ">> Nginx starten (nur HTTP für ACME-Challenge)..."
docker compose -f docker-compose.prod.yml up -d nginx

echo ">> Warte auf Nginx..."
sleep 5

echo ">> Dummy-Zertifikat erstellen (für initiales Nginx-Start)..."
docker compose -f docker-compose.prod.yml run --rm --entrypoint "\
    sh -c 'mkdir -p /etc/letsencrypt/live/$DOMAIN && \
    openssl req -x509 -nodes -newkey rsa:4096 -days 1 \
    -keyout /etc/letsencrypt/live/$DOMAIN/privkey.pem \
    -out /etc/letsencrypt/live/$DOMAIN/fullchain.pem \
    -subj \"/CN=localhost\"'" certbot 2>/dev/null || true

echo ">> Nginx mit SSL-Ports neu starten..."
docker compose -f docker-compose.prod.yml up -d nginx
sleep 3

echo ">> Dummy-Zertifikat entfernen..."
docker compose -f docker-compose.prod.yml run --rm --entrypoint "\
    rm -rf /etc/letsencrypt/live/$DOMAIN" certbot 2>/dev/null || true

echo ">> Let's Encrypt Zertifikat anfordern..."
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$ADMIN_EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN" \
    -d "www.$DOMAIN"

echo ">> Originale Nginx-Konfiguration wiederherstellen..."
cp ./nginx/nginx.conf.bak ./nginx/nginx.conf
rm ./nginx/nginx-ssl-staging.conf

echo ">> Nginx mit echtem SSL-Zertifikat neu laden..."
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload

echo ""
echo "=== SSL-Initialisierung abgeschlossen ==="
echo "Zertifikat: /etc/letsencrypt/live/$DOMAIN/"
echo "Automatische Erneuerung: läuft alle 12h über certbot-Container"
echo "Test: https://$DOMAIN"
