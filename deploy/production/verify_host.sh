#!/bin/bash
# FinSyntra Linux host verification gate. Run ON the deployment host after
# start.sh, systemd and Nginx are in place. Read-only except for: one test
# conversation, one test upload (deleted again), and one service restart.
#
#   sudo FINSOLVE_URL=https://finsolve.example.com \
#        FINSOLVE_ADMIN_EMAIL=ops@your-org.example \
#        deploy/production/verify_host.sh
#   (prompts for the admin password without echo)
#
# FINSOLVE_ADMIN_EMAIL must be a NON-demo tenant admin (needed for the upload
# boundary and persistence checks). The password is never accepted on the
# command line or from the environment (shell history, /proc/<pid>/environ):
#   - default: hidden interactive prompt on the terminal;
#   - non-interactive: FINSOLVE_ADMIN_PASSWORD_FILE=<path> naming a regular
#     file readable only by its owner (chmod 600), containing the password.
# It reaches curl only through a 0600 file in a private temp directory that is
# deleted right after login. Credentials and token values are never printed.
# Exit code = number of failed checks.
set -u
URL="${FINSOLVE_URL:?set FINSOLVE_URL=https://<your domain>}"
APP_DIR="${FINSOLVE_APP_DIR:-/opt/finsolve/app}"
ENV_FILE="${FINSOLVE_ENV_FILE:-/etc/finsolve/finsolve.env}"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
chmod 700 "$WORK"

if [ -n "${FINSOLVE_ADMIN_PASSWORD+x}" ]; then
    echo "Refusing FINSOLVE_ADMIN_PASSWORD from the environment; omit it to be prompted," \
         "or set FINSOLVE_ADMIN_PASSWORD_FILE to an owner-only file." >&2
    exit 2
fi
[ -n "${FINSOLVE_ADMIN_EMAIL:-}" ] || read -r -p "Admin email (non-demo tenant admin): " FINSOLVE_ADMIN_EMAIL
export FINSOLVE_ADMIN_EMAIL
# The login body is built inside Python so the password never enters a shell
# variable, an argument list or the environment.
python3 - "$WORK/login.json" <<'EOF' || exit 2
import getpass, json, os, stat, sys
path = os.environ.get("FINSOLVE_ADMIN_PASSWORD_FILE")
if path:
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        sys.exit("FINSOLVE_ADMIN_PASSWORD_FILE must be a regular file with mode 600 (owner-only)")
    with open(path, encoding="utf-8") as handle:
        password = handle.read().rstrip("\r\n")
else:
    password = getpass.getpass("Admin password (not echoed): ")
if not password:
    sys.exit("Empty admin password")
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as out:
    json.dump({"email": os.environ["FINSOLVE_ADMIN_EMAIL"], "password": password}, out)
EOF
FAILS=0
pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; FAILS=$((FAILS + 1)); }
check() { local name="$1"; shift; if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi; }
code() { curl -sS -o /dev/null -w '%{http_code}' --max-time 30 "$@"; }

echo "== 1. Nginx and systemd configuration"
check "nginx -t" nginx -t
check "systemd-analyze verify finsolve.service" systemd-analyze verify /etc/systemd/system/finsolve.service
check "finsolve.service active" systemctl is-active --quiet finsolve
[ "$(systemctl show -p User --value finsolve)" = "finsolve" ] && pass "service runs as user finsolve" \
    || fail "service runs as user finsolve"
[ "$(stat -c '%a %U:%G' "$ENV_FILE")" = "640 root:finsolve" ] && pass "env file is 0640 root:finsolve" \
    || fail "env file is 0640 root:finsolve (got $(stat -c '%a %U:%G' "$ENV_FILE"))"

echo "== 2. Listening sockets (internal services not public)"
LISTEN="$(ss -ltnH)"
echo "$LISTEN" | awk '{print $4}' | grep -qE '^127\.0\.0\.1:8000$' && pass "API listens on 127.0.0.1:8000" \
    || fail "API listens on 127.0.0.1:8000"
echo "$LISTEN" | awk '{print $4}' | grep -qE '^(0\.0\.0\.0|\[::\]|\*):8000$' && fail "API also bound publicly" \
    || pass "API not bound to a public address"
echo "$LISTEN" | awk '{print $4}' | grep -qE ':11434$' && fail "Ollama port 11434 is listening" \
    || pass "no Ollama listener"
echo "   (also run from ANOTHER machine: curl -m5 http://<server-ip>:8000/health  -> must fail to connect)"

echo "== 3. Routing through Nginx"
[ "$(code "$URL/")" = 200 ] && pass "/ -> 200 (landing)" || fail "/ -> 200"
ROOT_HTML="$(curl -sS "$URL/")"
echo "$ROOT_HTML" | grep -q '/assets/index-' && ! echo "$ROOT_HTML" | grep -q '/app/static/' \
    && pass "/ serves the landing build (Vite assets), not the app" || fail "/ serves the landing build"
[ "$(code "$URL/app/chat")" = 200 ] && curl -sS "$URL/app/chat" | grep -q '/app/static/js/main' \
    && pass "/app/chat nested reload -> CRA index" || fail "/app/chat nested reload -> CRA index"
ASSET="$(curl -sS "$URL/app/" | grep -o '/app/static/js/main[^"]*\.js' | head -1)"
[ -n "$ASSET" ] && [ "$(code "$URL$ASSET")" = 200 ] && pass "/app static asset served" || fail "/app static asset served"
[ "$(code "$URL/api/conversations")" = 401 ] && pass "/api/* reaches FastAPI (401 JSON, not SPA)" \
    || fail "/api/* reaches FastAPI"
curl -sS "$URL/docs" | grep -qi swagger && fail "/docs exposes Swagger" || pass "/docs not exposed"
[ "$(code "http://${URL#*://}/app")" = 301 ] && pass "HTTP redirects to HTTPS" || fail "HTTP redirects to HTTPS"
HDRS="$(curl -sSI "$URL/app/")"
echo "$HDRS" | grep -qi '^strict-transport-security' && pass "HSTS header" || fail "HSTS header"
echo "$HDRS" | grep -qi '^content-security-policy' && pass "CSP header" || fail "CSP header"

echo "== 4. HTTPS login, cookies, CSRF, refresh"
JAR="$WORK/jar"
LOGIN_HDR="$(curl -sS -D - -o "$WORK/login.out" -c "$JAR" -H "Origin: $URL" -H 'Content-Type: application/json' \
    --data @"$WORK/login.json" "$URL/auth/login")"
rm -f "$WORK/login.json"
echo "$LOGIN_HDR" | head -1 | grep -q ' 200' && pass "login 200" || fail "login 200"
echo "$LOGIN_HDR" | grep -i '^set-cookie: session_token=' | grep -qi 'httponly' \
    && echo "$LOGIN_HDR" | grep -i '^set-cookie: session_token=' | grep -qi 'secure' \
    && echo "$LOGIN_HDR" | grep -i '^set-cookie: session_token=' | grep -qi 'samesite=lax' \
    && pass "session cookie HttpOnly; Secure; SameSite=Lax" || fail "session cookie attributes"
echo "$LOGIN_HDR" | grep -i '^set-cookie: refresh_token=' | grep -qi 'path=/auth' \
    && echo "$LOGIN_HDR" | grep -i '^set-cookie: refresh_token=' | grep -qi 'httponly' \
    && pass "refresh cookie HttpOnly, Path=/auth" || fail "refresh cookie attributes"
CSRF="$(awk '$6=="csrf_token"{print $7}' "$JAR")"
[ "$(code -b "$JAR" -X POST -H "Origin: $URL" -H 'Content-Type: application/json' -d '{}' "$URL/api/conversations")" = 403 ] \
    && pass "cookie mutation without CSRF header -> 403" || fail "cookie mutation without CSRF -> 403"
CONV_JSON="$(curl -sS -w '\n%{http_code}' -b "$JAR" -X POST -H "Origin: $URL" -H "X-CSRF-Token: $CSRF" \
    -H 'Content-Type: application/json' -d '{"title":"verify_host"}' "$URL/api/conversations")"
C="$(echo "$CONV_JSON" | tail -1)"
CONV_ID="$(echo "$CONV_JSON" | head -1 | python3 -c 'import json,sys;print(json.load(sys.stdin).get("id",""))' 2>/dev/null)"
case "$C" in 200|201) pass "cookie mutation with CSRF header -> $C";; *) fail "cookie mutation with CSRF -> $C";; esac
cp "$JAR" "$WORK/jar.old"
[ "$(code -b "$JAR" -c "$JAR" -X POST -H "Origin: $URL" -H "X-CSRF-Token: $CSRF" "$URL/auth/refresh")" = 200 ] \
    && pass "refresh rotates (200)" || fail "refresh rotates"
OLDCSRF="$(awk '$6=="csrf_token"{print $7}' "$WORK/jar.old")"
[ "$(code -b "$WORK/jar.old" -X POST -H "Origin: $URL" -H "X-CSRF-Token: $OLDCSRF" "$URL/auth/refresh")" = 401 ] \
    && pass "replayed old refresh token -> 401" || fail "replayed old refresh token -> 401"
CSRF="$(awk '$6=="csrf_token"{print $7}' "$JAR")"

echo "== 5. SSE through Nginx (arrival time of each event)"
# curl -N disables output buffering; a python -u reader timestamps each line as
# it arrives. (urllib's line iterator buffers chunked responses and would
# misreport arrival times.)
curl -sS -N --max-time 120 -b "$JAR" -H 'Accept: text/event-stream' -D "$WORK/sse.hdr" \
    "$URL/api/chat/stream?q=verify%20host%20streaming%3A%20summarise%20any%20document" \
  | python3 -u -c '
import json, sys, time
t0 = time.time(); stamps = []; types = []; done = False; complete = None
for raw in iter(sys.stdin.buffer.readline, b""):
    if raw.startswith(b"data: "):
        stamps.append(round(time.time() - t0, 2))
        body = raw[6:].strip()
        if body == b"[DONE]":
            done = True
            break
        try:
            event = json.loads(body)
        except ValueError:
            types.append("unparseable"); continue
        types.append(event.get("type", "?"))
        if event.get("type") == "complete":
            complete = event
print("   events=%d first_event=%.2fs last=%.2fs" % (len(stamps), stamps[0], stamps[-1]) if stamps else "   no events")
print("   arrivals(s)=%s ... %s" % (stamps[:6], stamps[-3:]))
ok = len(stamps) > 3 and stamps[0] < 2 and len(set(stamps)) > 2 and stamps[-1] - stamps[0] > 0.2
print(("PASS" if ok else "FAIL") + "  SSE events arrive incrementally (first < 2s, spread over time)")
# Full-stream integrity: the stream must start, carry tokens, end with exactly
# one "complete" event followed by [DONE], and contain no "error" event.
# (A bare [DONE] is also sent after errors, so it proves nothing on its own.)
whole = (types[:1] == ["start"] and "token" in types and types.count("complete") == 1
         and "error" not in types and "unparseable" not in types and done)
print(("PASS" if whole else "FAIL") + "  SSE full stream: start, tokens, one complete, no error, [DONE]  (types=%s)"
      % sorted(set(types)))
sys.exit(0 if (ok and whole) else 1)
' || FAILS=$((FAILS + 1))
grep -qi '^content-type: text/event-stream' "$WORK/sse.hdr" && pass "SSE content-type text/event-stream" \
    || fail "SSE content-type text/event-stream"

echo "== 6. Upload size boundaries"
head -c $((11*1024*1024)) /dev/zero > "$WORK/11m"; head -c $((33*1024*1024)) /dev/zero > "$WORK/33m"
C11="$(code --data-binary @"$WORK/11m" -H 'Content-Type: application/octet-stream' "$URL/api/admin/upload-department-data")"
[ "$C11" != 413 ] && pass "11 MB body passes Nginx (got $C11 from FastAPI)" || fail "11 MB body rejected by Nginx"
[ "$(code --data-binary @"$WORK/33m" -H 'Content-Type: application/octet-stream' "$URL/api/admin/upload-department-data")" = 413 ] \
    && pass "33 MB body -> 413 at Nginx" || fail "33 MB body -> 413"
head -c $((11*1024*1024)) /dev/zero | tr '\0' 'a' > "$WORK/big.md"
R="$(curl -sS -b "$JAR" -H "Origin: $URL" -H "X-CSRF-Token: $CSRF" -F department=general \
    -F "files=@$WORK/big.md;type=text/markdown" "$URL/api/admin/upload-department-data")"
echo "$R" | grep -q 'too large' && pass "11 MB file -> backend 'File too large' (10 MB/file limit)" \
    || fail "11 MB file rejected by backend limit"
printf '# Verify host %s\n\nHost verification probe figure 7,654,321.\n' "$(date +%s)" > "$WORK/probe.md"
R="$(curl -sS -b "$JAR" -H "Origin: $URL" -H "X-CSRF-Token: $CSRF" -F department=general \
    -F "files=@$WORK/probe.md;type=text/markdown" "$URL/api/admin/upload-department-data")"
DOC_ID="$(echo "$R" | python3 -c 'import json,sys;print(json.load(sys.stdin)["results"][0]["file_info"]["document_id"])' 2>/dev/null)"
[ -n "$DOC_ID" ] && pass "small upload indexed" || fail "small upload indexed"
[ "$(code --data-binary @"$WORK/11m" -H 'Content-Type: application/json' "$URL/auth/login")" = 413 ] \
    && pass "11 MB body to /auth -> 413 (1 MB default)" || fail "11 MB body to /auth -> 413"

echo "== 7. Persistence across service restart"
DOCS_BEFORE="$(curl -sS -b "$JAR" "$URL/api/admin/documents" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')"
PID_BEFORE="$(systemctl show -p MainPID --value finsolve)"
systemctl restart finsolve
for i in $(seq 1 60); do [ "$(code "$URL/health/ready")" = 200 ] && break; sleep 3; done
[ "$(code "$URL/health/ready")" = 200 ] && pass "ready after restart" || fail "ready after restart"
[ "$(systemctl show -p MainPID --value finsolve)" != "$PID_BEFORE" ] && pass "service process actually restarted" \
    || fail "service process actually restarted"
DOCS_AFTER="$(curl -sS -b "$JAR" "$URL/api/admin/documents" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')"
[ -n "${CONV_ID:-}" ] && [ "$(code -b "$JAR" "$URL/api/conversations/$CONV_ID")" = 200 ] \
    && pass "conversation created before restart still readable" || fail "conversation survives restart"
[ "$DOCS_BEFORE" = "$DOCS_AFTER" ] && pass "document count unchanged across restart ($DOCS_AFTER)" \
    || fail "document count across restart ($DOCS_BEFORE -> $DOCS_AFTER)"
[ -n "${DOC_ID:-}" ] && curl -sS -b "$JAR" "$URL/api/admin/documents/$DOC_ID/content" | grep -q '7,654,321' \
    && pass "uploaded file content survives restart" || fail "uploaded file content survives restart"
if [ -n "${DOC_ID:-}" ]; then
    [ "$(code -b "$JAR" -X DELETE -H "Origin: $URL" -H "X-CSRF-Token: $CSRF" "$URL/api/admin/documents/$DOC_ID")" = 200 ] \
        && pass "probe document removed" || fail "probe document removed"
fi

echo "== 8. Invalid production configuration fails safely (does not touch the running service)"
bad() {  # $1 = description, rest = VAR=value overrides on top of the real env file
    local desc="$1"; shift
    if (set -a; . "$ENV_FILE"; set +a; export "$@"; cd "$APP_DIR" && \
        sudo -E -u finsolve "$APP_DIR/venv/bin/python" -c 'from src.config.settings import settings') >/dev/null 2>"$WORK/err"; then
        fail "$desc rejected"
    else
        grep -q FATAL "$WORK/err" && pass "$desc rejected at startup" || fail "$desc rejected with FATAL message"
    fi
}
bad "short SECRET_KEY" SECRET_KEY=short-key
bad "wildcard ALLOWED_ORIGINS" 'ALLOWED_ORIGINS=["*"]'
bad "DEBUG=true" DEBUG=true
bad "missing GROQ_API_KEY" GROQ_API_KEY=
bad "BYPASS_AUTH=true" BYPASS_AUTH=true
(set -a; . "$ENV_FILE"; set +a; cd "$APP_DIR" && sudo -E -u finsolve "$APP_DIR/venv/bin/python" \
    scripts/manage_user.py audit-committed) >/dev/null 2>&1 \
    && pass "no active account uses a committed password hash" || fail "accounts with committed password hashes exist"

echo
[ "$FAILS" -eq 0 ] && echo "ALL CHECKS PASSED" || echo "$FAILS CHECK(S) FAILED"
exit "$FAILS"
