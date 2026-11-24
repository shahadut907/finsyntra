#!/bin/sh
# Consistent FinSyntra backup: SQLite + Chroma + uploaded documents + env file,
# captured together while the API is stopped so the three stores agree.
#
#   sudo deploy/production/backup.sh                 # stops/starts finsolve.service
#   FINSOLVE_NO_SERVICE=1 deploy/production/backup.sh   # caller guarantees no writer
#
# Output: $BACKUP_ROOT/<UTC timestamp>/ with finsolve.db, chroma.tar.gz,
# raw.tar.gz, finsolve.env (0600), MANIFEST (alembic revision, commit), SHA256SUMS.
# Downtime is the copy time only; the service is restarted even on failure.
set -eu

APP_DIR="${FINSOLVE_APP_DIR:-/opt/finsolve/app}"
ENV_FILE="${FINSOLVE_ENV_FILE:-/etc/finsolve/finsolve.env}"
BACKUP_ROOT="${FINSOLVE_BACKUP_ROOT:-/var/backups/finsolve}"
VENV_PY="${FINSOLVE_PYTHON:-$APP_DIR/venv/bin/python}"

set -a
. "$ENV_FILE"
set +a
DB_PATH="${DATABASE_URL#sqlite:///}"
case "$DB_PATH" in /*|[A-Za-z]:*) ;; *) DB_PATH="/$DB_PATH" ;; esac

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_ROOT/$STAMP"
umask 077
mkdir -p "$DEST"

restart() {
    if [ -z "${FINSOLVE_NO_SERVICE:-}" ]; then
        systemctl start finsolve || echo "WARNING: finsolve did not restart" >&2
    fi
}
if [ -z "${FINSOLVE_NO_SERVICE:-}" ]; then
    systemctl stop finsolve
    trap restart EXIT
fi

echo "[backup] SQLite -> $DEST/finsolve.db"
"$VENV_PY" - "$DB_PATH" "$DEST/finsolve.db" <<'EOF'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
rev = dst.execute("SELECT version_num FROM alembic_version").fetchone()
dst.close(); src.close()
if ok != "ok":
    sys.exit("integrity_check failed: %s" % ok)
print("alembic_revision", rev[0] if rev else "none")
EOF

echo "[backup] Chroma and documents"
tar -C "$(dirname "$VECTOR_DB_PATH")" -czf "$DEST/chroma.tar.gz" "$(basename "$VECTOR_DB_PATH")"
tar -C "$(dirname "$RAW_DOCUMENTS_PATH")" -czf "$DEST/raw.tar.gz" "$(basename "$RAW_DOCUMENTS_PATH")"
cp "$ENV_FILE" "$DEST/finsolve.env"
chmod 600 "$DEST/finsolve.env"

REV="$("$VENV_PY" -c "import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute('select version_num from alembic_version').fetchone()[0])" "$DEST/finsolve.db")"
{
    echo "created_utc=$STAMP"
    echo "alembic_revision=$REV"
    echo "app_commit=$(git -C "$APP_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
} > "$DEST/MANIFEST"
(cd "$DEST" && sha256sum finsolve.db chroma.tar.gz raw.tar.gz finsolve.env > SHA256SUMS)
echo "[backup] complete: $DEST"
