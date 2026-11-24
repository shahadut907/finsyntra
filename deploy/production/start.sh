#!/bin/sh
# Native production startup: validate environment, ensure storage exists,
# migrate, seed demo data, then hand off to systemd's ExecStart for Uvicorn.
#
# Intended to run as an ExecStartPre-equivalent step invoked by the deploy
# procedure (not embedded in the systemd unit itself, per the "smallest safe
# native deployment" requirement) — see docs/NATIVE_DEPLOYMENT_RUNBOOK.md.
#
# A failed migration must prevent the backend from starting: `set -e` plus
# checking alembic's own exit code below guarantees that.
set -eu

APP_DIR="${FINSOLVE_APP_DIR:-/opt/finsolve/app}"
VENV_PY="$APP_DIR/venv/bin/python"
VENV_ALEMBIC="$APP_DIR/venv/bin/alembic"

cd "$APP_DIR"

if [ -z "${FINSOLVE_ENV_FILE:-}" ]; then
    FINSOLVE_ENV_FILE=/etc/finsolve/finsolve.env
fi
if [ ! -f "$FINSOLVE_ENV_FILE" ]; then
    echo "FATAL: environment file not found: $FINSOLVE_ENV_FILE" >&2
    exit 1
fi
set -a
. "$FINSOLVE_ENV_FILE"
set +a

DB_PATH="${DATABASE_URL#sqlite:///}"
DB_PATH="/${DB_PATH#/}"
mkdir -p "$(dirname "$DB_PATH")" "$VECTOR_DB_PATH" "$RAW_DOCUMENTS_PATH" "$DEMO_DOCUMENTS_PATH" "${HF_HOME:-/var/lib/finsolve/hf-cache}"

# The synthetic public-demo corpus ships in the repository but is served from
# persistent storage. Copy any file not already present (-n: never overwrite),
# so the demo tenant has its documents on first boot and on corpus additions.
if [ "${PUBLIC_DEMO_ENABLED:-false}" = "true" ]; then
    echo "[start.sh] provisioning public-demo corpus into $DEMO_DOCUMENTS_PATH"
    cp -n "$APP_DIR"/src/data/demo_corpus/* "$DEMO_DOCUMENTS_PATH"/
    if [ -z "$(ls -A "$DEMO_DOCUMENTS_PATH")" ]; then
        echo "FATAL: PUBLIC_DEMO_ENABLED=true but $DEMO_DOCUMENTS_PATH is empty" >&2
        exit 1
    fi
fi

echo "[start.sh] validating settings (import triggers fail-closed checks)"
"$VENV_PY" -c "from src.config.settings import settings" || {
    echo "FATAL: settings validation failed — see output above" >&2
    exit 1
}

echo "[start.sh] running alembic upgrade head"
"$VENV_ALEMBIC" upgrade head || {
    echo "FATAL: migration failed — backend will not start" >&2
    exit 1
}

echo "[start.sh] checking for active private accounts with committed credentials"
"$VENV_PY" scripts/manage_user.py audit-committed || {
    echo "FATAL: reset or deactivate the accounts above with scripts/manage_user.py" >&2
    exit 1
}

echo "[start.sh] migration complete at head; demo seed runs on app import (idempotent)"
echo "[start.sh] ready — systemd will now start uvicorn via finsolve.service"
