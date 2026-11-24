#!/bin/sh
# Staging checks for a small (cardless / 1 GB) host: HTTPS auth, complete SSE
# stream, SQLite/Chroma state snapshot, and process memory. Read-only against
# the application except for logging in, creating one empty conversation and
# asking two questions. It never prints a password, token or cookie value.
#
#   FINSOLVE_URL=https://<host> \
#   FINSOLVE_ADMIN_EMAIL=<admin> FINSOLVE_ADMIN_PASSWORD_FILE=/root/.finsolve-pw \
#   deploy/production/staging_checks.sh all|auth|sse|state|mem
#
# FINSOLVE_ADMIN_PASSWORD_FILE must be an owner-only (mode 600) file; the
# password is refused on the command line and in the environment, as in
# verify_host.sh. `auth` needs the admin; `sse`, `state` and `mem` do not.
# CURL_EXTRA is word-split on purpose (e.g. "-k --resolve host:443:127.0.0.1"
# for a self-signed test certificate; leave empty in production).
# `state` reads the stores directly: run it on the host (as root or the
# finsolve user); it opens SQLite and chroma.sqlite3 read-only.
set -u
URL="${FINSOLVE_URL:?set FINSOLVE_URL, e.g. https://finsolve.example.com}"
STATE_DIR="${FINSOLVE_STATE_DIR:-/var/lib/finsolve}"
APP_DIR="${FINSOLVE_APP_DIR:-/opt/finsolve/app}"
PY="${FINSOLVE_PYTHON:-$APP_DIR/venv/bin/python}"
[ -x "$PY" ] || PY=python3
CURL="curl -sS -m 60 ${CURL_EXTRA:-}"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
FAILS=0
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; FAILS=$((FAILS + 1)); }
code() { $CURL -o /dev/null -w '%{http_code}' "$@"; }

check_auth() {
    echo "== HTTPS auth, cookies, CSRF, refresh rotation"
    [ "$(code "$URL/health/ready")" = 200 ] && pass "TLS + /health/ready 200" || fail "/health/ready"
    [ "$(code "$URL/api/conversations")" = 401 ] && pass "unauthenticated API -> 401" || fail "unauthenticated API -> 401"
    PWF="${FINSOLVE_ADMIN_PASSWORD_FILE:-}"; EMAIL="${FINSOLVE_ADMIN_EMAIL:-}"
    if [ -z "$PWF" ] || [ -z "$EMAIL" ]; then fail "set FINSOLVE_ADMIN_EMAIL and FINSOLVE_ADMIN_PASSWORD_FILE"; return; fi
    if [ -n "${FINSOLVE_ADMIN_PASSWORD:-}" ]; then fail "FINSOLVE_ADMIN_PASSWORD in the environment is refused; use the file"; return; fi
    [ "$(stat -c %a "$PWF" 2>/dev/null)" = 600 ] || { fail "$PWF must be mode 600"; return; }
    BODY="$("$PY" -c 'import json,sys; print(json.dumps({"email": sys.argv[1], "password": open(sys.argv[2]).read().rstrip("\r\n")}))' "$EMAIL" "$PWF")"
    [ "$(code -H 'Content-Type: application/json' -d '{"email":"'"$EMAIL"'","password":"wrong-password-for-check"}' "$URL/auth/login")" = 401 ] \
        && pass "wrong password -> 401" || fail "wrong password -> 401"
    J="$WORK/jar"
    L="$(code -c "$J" -H "Origin: $URL" -H 'Content-Type: application/json' -d "$BODY" "$URL/auth/login")"; BODY=""
    [ "$L" = 200 ] && pass "password login -> 200" || { fail "password login -> $L"; return; }
    SEC="$(awk 'BEGIN{FS="\t"} /^#HttpOnly_/ || !/^#/ {if (NF>=7 && $4=="TRUE") n++} END{print n+0}' "$J")"
    HO="$(awk 'BEGIN{FS="\t"} /^#HttpOnly_/ && NF>=7 {print $6}' "$J" | sort | tr '\n' ' ')"
    [ "$SEC" -ge 3 ] && pass "cookies are Secure ($SEC)" || fail "cookies are Secure (found $SEC, expected >= 3)"
    case "$HO" in *refresh_token*session_token*|*session_token*refresh_token*) pass "session_token and refresh_token are HttpOnly";; *) fail "HttpOnly cookies (got: $HO)";; esac
    CSRF="$(awk '$6=="csrf_token"{print $7}' "$J")"
    [ "$(code -b "$J" -X POST -H "Origin: $URL" -H 'Content-Type: application/json' -d '{}' "$URL/api/conversations")" = 403 ] \
        && pass "mutation without CSRF header -> 403" || fail "mutation without CSRF header -> 403"
    C2="$(code -b "$J" -X POST -H "Origin: $URL" -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' -d '{"title":"staging_checks"}' "$URL/api/conversations")"
    case "$C2" in 200|201) pass "mutation with CSRF header -> $C2";; *) fail "mutation with CSRF header -> $C2";; esac
    [ "$(code -b "$J" -X POST -H "Origin: https://evil.example" -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' -d '{"title":"x"}' "$URL/api/conversations")" != 200 ] \
        && pass "foreign Origin refused" || fail "foreign Origin accepted"
    cp "$J" "$WORK/jar.old"; OLDCSRF="$CSRF"
    [ "$(code -b "$J" -c "$J" -X POST -H "Origin: $URL" -H "X-CSRF-Token: $CSRF" "$URL/auth/refresh")" = 200 ] \
        && pass "refresh rotates -> 200" || fail "refresh rotates"
    [ "$(code -b "$WORK/jar.old" -X POST -H "Origin: $URL" -H "X-CSRF-Token: $OLDCSRF" "$URL/auth/refresh")" = 401 ] \
        && pass "replayed refresh token -> 401" || fail "replayed refresh token -> 401"
    NEWCSRF="$(awk '$6=="csrf_token"{print $7}' "$J")"
    cp "$J" "$WORK/jar.pre-logout"
    [ "$(code -b "$J" -c "$J" -X POST -H "Origin: $URL" -H "X-CSRF-Token: $NEWCSRF" "$URL/auth/logout")" = 200 ] \
        && pass "logout -> 200" || fail "logout"
    [ "$(code -b "$WORK/jar.pre-logout" -X POST -H "Origin: $URL" -H "X-CSRF-Token: $NEWCSRF" "$URL/auth/refresh")" = 401 ] \
        && pass "refresh token revoked by logout -> 401" || fail "refresh token revoked by logout"
}

check_sse() {
    echo "== complete SSE stream as a public-demo visitor (needs PUBLIC_DEMO_ENABLED=true)"
    J="$WORK/vis"; OUT="$WORK/sse.txt"
    $CURL -o /dev/null -c "$J" -H "Origin: $URL" -H 'Content-Type: application/json' -d '{"role":"employee"}' "$URL/auth/demo-login"
    T0="$(date +%s)"
    $CURL -N --max-time 120 -b "$J" -H 'Accept: text/event-stream' \
        "$URL/api/chat/stream?q=How%20many%20days%20of%20annual%20leave%20do%20full-time%20employees%20get%3F" > "$OUT"
    echo "   stream wall time: $(( $(date +%s) - T0 ))s"
    "$PY" - "$OUT" <<'PY' || FAILS=$((FAILS + 1))
import json, sys
ev, done = [], False
for line in open(sys.argv[1], encoding="utf-8"):
    if not line.startswith("data: "):
        continue
    body = line[6:].strip()
    if body == "[DONE]":
        done = True
        continue
    ev.append(json.loads(body))
types = [e["type"] for e in ev]
complete = [e for e in ev if e["type"] == "complete"]
answer = "".join(e.get("token", "") for e in ev if e["type"] == "token").replace(" ", " ")
checks = {
    "starts with start": types[:1] == ["start"],
    "has tokens": "token" in types,
    "exactly one complete": len(complete) == 1,
    "complete success=true": bool(complete) and complete[0].get("success") is True,
    "non-empty sources": bool(complete) and bool(complete[0].get("sources")),
    "cites the handbook": bool(complete) and any("employee_handbook" in str(s) for s in complete[0].get("sources", [])),
    "answer contains 20": "20" in answer,
    "no error event": "error" not in types,
    "[DONE] is last": done,
}
for name, ok in checks.items():
    print(("PASS  " if ok else "FAIL  ") + name)
sys.exit(0 if all(checks.values()) else 1)
PY
}

check_state() {
    echo "== SQLite / Chroma / raw state snapshot (compare before and after a restart)"
    "$PY" - "$STATE_DIR" <<'PY'
import json, os, sqlite3, sys
d = sys.argv[1]
db = sqlite3.connect("file:%s/finsolve.db?mode=ro" % d, uri=True)
q = lambda s: db.execute(s).fetchone()[0]
out = {"alembic": q("select version_num from alembic_version"), "users": q("select count(*) from users"),
       "documents": q("select count(*) from documents"), "chat_sessions": q("select count(*) from chat_sessions"),
       "chat_messages": q("select count(*) from chat_messages")}
ch = sqlite3.connect("file:%s/chroma/chroma.sqlite3?mode=ro" % d, uri=True)
out["chroma_embeddings"] = ch.execute("select count(*) from embeddings").fetchone()[0]
for name in ("raw", "demo_corpus"):
    p = os.path.join(d, name)
    out[name + "_files"] = len(os.listdir(p)) if os.path.isdir(p) else -1
print("STATE " + json.dumps(out, sort_keys=True))
PY
}

check_mem() {
    echo "== memory of the uvicorn process (single worker)"
    PID="$(systemctl show -p MainPID --value finsolve 2>/dev/null)"
    [ -n "$PID" ] && [ "$PID" != 0 ] || PID="$(pgrep -f 'uvicorn src.backend.api.endpoints' | head -1)"
    [ -n "$PID" ] || { fail "uvicorn process not found"; return; }
    grep -E 'VmRSS|VmHWM|RssAnon|RssFile' "/proc/$PID/status" | tr -s ' \t' ' ' | sed 's/^/   /'
    echo "   MemAvailable: $(awk '/MemAvailable/ {printf "%d MB", $2/1024}' /proc/meminfo)  MemTotal: $(awk '/MemTotal/ {printf "%d MB", $2/1024}' /proc/meminfo)  SwapTotal: $(awk '/SwapTotal/ {printf "%d MB", $2/1024}' /proc/meminfo)"
    if [ -r /sys/fs/cgroup/memory.max ]; then echo "   cgroup max=$(cat /sys/fs/cgroup/memory.max) current=$(cat /sys/fs/cgroup/memory.current) peak=$(cat /sys/fs/cgroup/memory.peak 2>/dev/null)"; fi
    if [ -r /sys/fs/cgroup/memory/memory.limit_in_bytes ]; then echo "   cgroup(v1) limit=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes) usage=$(cat /sys/fs/cgroup/memory/memory.usage_in_bytes) peak=$(cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes)"; fi
    dmesg 2>/dev/null | grep -i 'out of memory\|oom-kill' | tail -2 | sed 's/^/   dmesg: /'
}

case "${1:-all}" in
    auth)  check_auth ;;
    sse)   check_sse ;;
    state) check_state ;;
    mem)   check_mem ;;
    all)   check_auth; check_sse; check_state; check_mem ;;
    *) echo "usage: $0 all|auth|sse|state|mem" >&2; exit 2 ;;
esac
[ "$FAILS" -eq 0 ] && echo "ALL CHECKS PASSED" || echo "$FAILS CHECK(S) FAILED"
exit "$FAILS"
