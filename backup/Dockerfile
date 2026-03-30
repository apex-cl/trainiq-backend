FROM alpine:3.20

RUN apk add --no-cache \
    postgresql16-client \
    aws-cli \
    bash \
    findutils \
    grep \
    coreutils

COPY backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

# Backup um 03:00 Uhr (Server-Zeit)
RUN echo "0 3 * * * /usr/local/bin/backup.sh >> /var/log/backup.log 2>&1" > /etc/crontabs/root

# Crond im Vordergrund starten + initiales Backup beim ersten Start
CMD ["sh", "-c", "crond -f -l 2 & /usr/local/bin/backup.sh >> /var/log/backup.log 2>&1; tail -f /var/log/backup.log"]
