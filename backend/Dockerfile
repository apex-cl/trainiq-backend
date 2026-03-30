FROM python:3.12-slim

WORKDIR /app

# System-Dependencies für PostgreSQL und Compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn uvicorn[standard]

COPY . .

EXPOSE 8000

# Default: Production mit Gunicorn + Uvicorn Worker
CMD ["gunicorn", "main:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "120"]
