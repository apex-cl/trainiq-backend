FROM python:3.12-slim

# Security: Non-root user
RUN groupadd --gid 1001 appuser && \
    useradd --uid 1001 --gid appuser --no-create-home --shell /bin/false appuser

WORKDIR /app

# System-Dependencies für PostgreSQL und Compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn uvicorn[standard]

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default: Production mit Gunicorn + Uvicorn Worker
# Worker-Formel: 2 × CPUs + 1 (max 8 um RAM zu schonen)
CMD ["sh", "-c", "gunicorn main:app -w ${WORKERS:-2} -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120 --graceful-timeout 30 --keep-alive 5 --access-logfile -"]
