#!/bin/sh
# Render Free web service entrypoint: migrate Neon, audit accounts, one uvicorn worker.
set -eu
mkdir -p "$VECTOR_DB_PATH" "$RAW_DOCUMENTS_PATH"
echo "[render] alembic upgrade head"
alembic upgrade head
echo "[render] audit committed credentials"
python scripts/manage_user.py audit-committed
echo "[render] starting uvicorn on port ${PORT:-10000}"
exec uvicorn src.backend.api.endpoints:app --host 0.0.0.0 --port "${PORT:-10000}" --workers 1
