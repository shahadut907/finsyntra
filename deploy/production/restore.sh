#!/bin/sh
# Restore a backup made by backup.sh. Current data is moved aside (never
# deleted) to <path>.pre-restore-<timestamp> so a bad restore can be undone.
#
#   sudo deploy/production/restore.sh /var/backups/finsolve/<timestamp>
#   FINSOLVE_NO_SERVICE=1 deploy/production/restore.sh <dir>   # caller stops the API
#
# The env file is NOT restored (it may hold rotated secrets): a backup taken
# before a SECRET_KEY rotation must never bring the old key back. If you copy
# <dir>/finsolve.env by hand, start.sh still refuses keys known to be
# compromised, but any other retired key would be accepted again.
# The restored database must be at or below the code's alembic head: run
# `alembic upgrade head` (start.sh does this) after restoring onto newer code.
set -eu

SRC="${1:?usage: restore.sh <backup-dir>}"
APP_DIR="${FINSOLVE_APP_DIR:-/opt/finsolve/app}"
ENV_FILE="${FINSOLVE_ENV_FILE:-/etc/finsolve/finsolve.env}"

(cd "$SRC" && sha256sum -c SHA256SUMS --quiet) || {
    echo "FATAL: backup checksum verification failed" >&2
    exit 1
}

set -a
. "$ENV_FILE"
set +a
DB_PATH="${DATABASE_URL#sqlite:///}"
case "$DB_PATH" in /*|[A-Za-z]:*) ;; *) DB_PATH="/$DB_PATH" ;; esac
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

if [ -z "${FINSOLVE_NO_SERVICE:-}" ]; then
    systemctl stop finsolve
fi

for path in "$DB_PATH" "$VECTOR_DB_PATH" "$RAW_DOCUMENTS_PATH"; do
    if [ -e "$path" ]; then
        mv "$path" "$path.pre-restore-$STAMP"
    fi
done

cp "$SRC/finsolve.db" "$DB_PATH"
# A restored database can re-activate refresh tokens that were revoked after
# the backup was taken (logouts, deactivated users, key rotation). Revoke them
# all: every user signs in again after a restore.
"${FINSOLVE_PYTHON:-$APP_DIR/venv/bin/python}" - "$DB_PATH" <<'EOF'
import sqlite3, sys
from datetime import datetime, timezone
conn = sqlite3.connect(sys.argv[1])
n = conn.execute("UPDATE refresh_tokens SET revoked_at = ? WHERE revoked_at IS NULL",
                 (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),)).rowcount
conn.commit(); conn.close()
print(f"[restore] revoked {n} refresh token(s) from the restored database")
EOF
tar -C "$(dirname "$VECTOR_DB_PATH")" -xzf "$SRC/chroma.tar.gz"
tar -C "$(dirname "$RAW_DOCUMENTS_PATH")" -xzf "$SRC/raw.tar.gz"
if [ -z "${FINSOLVE_NO_SERVICE:-}" ]; then
    chown -R finsolve:finsolve "$DB_PATH" "$VECTOR_DB_PATH" "$RAW_DOCUMENTS_PATH"
fi
echo "[restore] restored from $SRC; previous data kept as *.pre-restore-$STAMP"

if [ -z "${FINSOLVE_NO_SERVICE:-}" ]; then
    (cd "$APP_DIR" && sudo -u finsolve deploy/production/start.sh)
    systemctl start finsolve
fi
