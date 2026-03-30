## Datenbank-Migrationen

### Neue Migration erstellen
```bash
docker compose exec backend alembic revision --autogenerate -m "beschreibung"
```

### Migrationen ausführen
```bash
docker compose exec backend alembic upgrade head
```

### Migration rückgängig machen
```bash
docker compose exec backend alembic downgrade -1
```

### Aktuellen Status sehen
```bash
docker compose exec backend alembic current
```
