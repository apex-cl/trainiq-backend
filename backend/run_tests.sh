#!/bin/bash
set -e

echo "=== TrainIQ Backend Tests ==="
echo ""

# Install test dependencies if needed
pip install pytest pytest-asyncio httpx aiosqlite --quiet

# Run tests
python -m pytest tests/ -v --tb=short 2>&1

echo ""
echo "=== Tests abgeschlossen ==="
