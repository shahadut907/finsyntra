# FinSyntra Native Linux Deployment Runbook

Docker is **not** the supported production deployment path. Production is:

```
Internet → Nginx (TLS, static build, SPA) → FastAPI (Uvicorn, 127.0.0.1:8000)
         → SQLite / Chroma / raw documents on local persistent disk
         → Groq API (LLM_PROVIDER=groq)
```

Local development is unchanged: FastAPI → Ollama → `llama3.2:3b`.

`docker-compose*.yml` and `frontend/Dockerfile.production` remain in the repo
as legacy/optional artifacts. They are not exercised by this runbook and are
not required for release.

## 1. Server prerequisites

- Linux x86_64 (see §16 for ARM64 caveats), outbound HTTPS to `api.groq.com`.
- `python3.11`, `python3.11-venv`, `nginx`, `systemd`.
- No GPU, no Ollama package, no Docker required in production.
- Optional, only for OCR of **scanned** PDFs uploaded by a tenant admin:
  `poppler-utils` and `tesseract-ocr`. OCR runs with Tesseract's default
  (English) language data, so scanned Bangla is not supported. Text PDFs
  (including Bangla), Markdown, TXT and CSV need nothing extra. Without them a
  scanned PDF extracts no text and the upload is rejected as having no
  indexable content; nothing else is affected. The public demo is read-only, so
  this does not apply to demo visitors. The test
  `test_release_candidate::test_host_ocr_extracts_visible_text_from_scanned_pdf`
  is skipped on a host without them.

## 2. Application user and directories

```sh
sudo useradd --system --home /opt/finsolve --shell /usr/sbin/nologin finsolve
sudo mkdir -p /opt/finsolve/app /opt/finsolve/frontend-build
sudo mkdir -p /var/lib/finsolve /var/backups/finsolve /etc/finsolve
sudo chown -R finsolve:finsolve /opt/finsolve /var/lib/finsolve
sudo chown root:finsolve /etc/finsolve
sudo chmod 750 /var/lib/finsolve /etc/finsolve
```

Layout:

```
/opt/finsolve/app/            application code + venv/
/opt/finsolve/frontend-build/ React production build served by Nginx
/var/lib/finsolve/
  finsolve.db                 SQLite (owner finsolve:finsolve, 0640)
  chroma/                     Chroma persistence
  raw/                        uploaded documents
  demo_corpus/                synthetic public-demo corpus
  hf-cache/                   SentenceTransformer/huggingface_hub cache (HF_HOME) —
                               must be writable; ProtectSystem=strict makes
                               everything outside /var/lib/finsolve read-only
/var/backups/finsolve/        DB/Chroma/raw backups
/etc/finsolve/finsolve.env    production secrets, 0640, root:finsolve
```

## 3. Clone/copy application

```sh
sudo -u finsolve git clone <repo-url> /opt/finsolve/app
sudo -u finsolve git -C /opt/finsolve/app checkout <candidate-sha>
```

**Alternative without Git (source archive).** The deployment scripts do not
need Git metadata (the only use is `git rev-parse` in `backup.sh`, which falls
back to `app_commit=unknown`). From a `git archive` of the candidate commit and
its `.sha256` file, verify the checksum before unpacking:

```sh
sha256sum -c finsolve-<sha12>.tar.gz.sha256          # must print: OK
sudo -u finsolve tar -xzf finsolve-<sha12>.tar.gz -C /opt/finsolve/app
```

An archive deployment cannot use the `git pull` update step of §13; unpack the
next archive over a fresh directory instead, after the §12 backup.

## 4. Python environment

```sh
cd /opt/finsolve/app
sudo -u finsolve python3.11 -m venv venv
sudo -u finsolve venv/bin/pip install --require-hashes --no-deps \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements-linux-py311.lock
sudo -u finsolve venv/bin/pip check
```

`requirements-linux-py311.lock` pins the exact tested version of every
production package (x86_64, glibc ≥ 2.28, CPython 3.11) with sha256 hashes,
and takes the CPU build of torch 2.7.1 from the PyTorch index; `--no-deps`
installs exactly that set without re-resolving. Do not use
`pip install -r requirements.txt` on the host: it would resolve transitive
versions afresh and pull PyPI's CUDA torch wheel (several GB of NVIDIA
libraries) onto a host with no GPU. Two packages ship only as source
(`langdetect`, `pypika`) and are built by pip during the install.

See §16 for dependency compatibility notes (torch CPU, ChromaDB,
sentence-transformers).

## 5. Frontend build

Two static builds are served from one origin: the marketing landing page at
`/` and the FinSyntra application at `/app`. Build both on a machine with
Node (CI or the server itself), then copy them into
`/opt/finsolve/frontend-build` — the app build nests under `app/` so its
`homepage: "/app"`-relative asset paths resolve correctly:

```sh
# Landing page -> /
cd landing-source/finsolve_ai_landing
npm ci
npm run build
sudo -u finsolve cp -r dist/* /opt/finsolve/frontend-build/

# FinSyntra application -> /app
cd ../../frontend
cp .env.production.example .env.production   # gitignored; copy fresh each build

# REACT_APP_PUBLIC_DEMO_ENABLED is a CRA COMPILE-TIME variable — it has no
# effect if set after the build. LoginForm.js gates the entire public
# recruiter demo panel (Admin/Finance/HR/Engineering/General) on it. Verify
# it is present and "true" in the file `npm run build` will actually read,
# BEFORE building:
grep -q '^REACT_APP_PUBLIC_DEMO_ENABLED=true$' .env.production || {
    echo "FATAL: REACT_APP_PUBLIC_DEMO_ENABLED=true missing from .env.production" >&2
    exit 1
}

npm ci
npm run build
sudo -u finsolve mkdir -p /opt/finsolve/frontend-build/app
sudo -u finsolve cp -r build/* /opt/finsolve/frontend-build/app/
```

No `REACT_APP_API_URL` needs to be set: [config/env.js](../frontend/src/config/env.js),
[lib/apiClient.js](../frontend/src/lib/apiClient.js) and
[config/chat.js](../frontend/src/config/chat.js) all default to same-origin
(`window.location.origin`) outside `NODE_ENV=development`, verified by
[frontend/src/__tests__/wave7_production_api_base.test.js](../frontend/src/__tests__/wave7_production_api_base.test.js).
`frontend/.env.development` (local-only, gitignored) carries the
`http://localhost:8000` override used for local dev — CRA loads
`.env.production` over it during `npm run build`, so that override cannot
leak into a production bundle built from this checkout. The Groq key never
enters the frontend bundle; confirmed absent from `build/static/js/*.js` in
this session's build.

## 6. Production environment file

```sh
sudo cp deploy/production/.env.production.example /etc/finsolve/finsolve.env
sudo chown root:finsolve /etc/finsolve/finsolve.env
sudo chmod 640 /etc/finsolve/finsolve.env
sudo nano /etc/finsolve/finsolve.env   # fill in everything EXCEPT SECRET_KEY (see 6a)
```

**How the file is loaded — keep the shell quoting.** The same file is read two
different ways, and a value must be valid in both:

| Reader | How | Notes |
|---|---|---|
| `finsolve.service` | systemd `EnvironmentFile=` | Quotes are stripped like a shell would. |
| `start.sh`, `backup.sh`, `restore.sh`, `verify_host.sh` and the §7a `manage_user.py` recipe | `set -a; . /etc/finsolve/finsolve.env; set +a` in `sh` (`start.sh` runs `set -eu`) | A value with spaces or quotes that is not quoted aborts the script (`RAG: command not found`), or silently loses its quotes. |

The template therefore ships `APP_NAME="FinSyntra RAG Chatbot"` and
`ALLOWED_ORIGINS='["https://finsolve.example.com"]'` (single quotes keep the
JSON double quotes). Edit the domain **inside** the single quotes; keep several
origins inside one pair: `ALLOWED_ORIGINS='["https://a.example","https://b.example"]'`.
An unquoted `ALLOWED_ORIGINS=["https://…"]` reaches Python as
`[https://…]` and settings validation fails with
`error parsing value for field "allowed_origins"`. After editing, check the file
sources cleanly before going further (no output other than `ok` is acceptable):

```sh
sudo sh -eu -c 'set -a; . /etc/finsolve/finsolve.env; set +a; echo ok'
```

The application also falls back to a `.env` file in its working directory
(`/opt/finsolve/app/.env`) for any variable the environment does not set. Do not
create one on the host; the env file above is the single source.

### 6a. Signing key (SECRET_KEY) — generate, never type or paste it

Every `SECRET_KEY` that ever appeared in this repository's Git history is
compromised (anyone with a clone can mint valid tokens). Production startup
refuses them by SHA-256 fingerprint, refuses keys shorter than 32 characters,
and refuses the known weak defaults. Install a fresh key with the rotation
script, which generates it inside the process, writes it atomically (keeping
the file's mode/owner), never prints it, and revokes all refresh tokens:

```sh
cd /opt/finsolve/app
sudo python3 scripts/rotate_secret_key.py /etc/finsolve/finsolve.env
sudo systemctl restart finsolve        # only once the service exists (§8)
```

Use the same two commands to rotate later. After the restart every access and
refresh token signed with the previous key is rejected (401) and users sign in
again. If a key leaks later, also add its fingerprint to the environment so it
can never be reinstated (`FINSOLVE_COMPROMISED_KEY_SHA256=<sha256 hex>[,…]`,
computed with `python3 -c 'import hashlib,getpass;print(hashlib.sha256(getpass.getpass().encode()).hexdigest())'`).
Backups made before a rotation contain the old key in their `finsolve.env`
copy; `restore.sh` never restores that file.

Startup fails closed (verified against [src/config/settings.py](../src/config/settings.py))
if: `SECRET_KEY` is missing, shorter than 32 characters, a known weak default
or a committed (compromised) value, `DEBUG=true` (enables SQLAlchemy SQL echo,
which can log sensitive bound values such as `visitor_session_id`),
`LLM_PROVIDER=groq` and `GROQ_API_KEY` or `GROQ_MODEL` is missing,
`GROQ_BASE_URL` isn't HTTPS, `ALLOWED_ORIGINS` contains `*` or a non-HTTPS
entry, or the provider timeout isn't strictly below `RAG_HARD_TIMEOUT_SECONDS`.

## 7. Migration and demo bootstrap

**Order for a first deployment (verified against the scripts and
`src/backend/api/endpoints.py`; do not reorder):**

| # | Step | Why it must be here |
|---|---|---|
| 1 | §2–§5: user, directories, code, venv, both builds | — |
| 2 | §6: env file, fully filled except `SECRET_KEY`; the `sh -eu … echo ok` check passes | Every later step reads this file. |
| 3 | §6a: `rotate_secret_key.py` | Production refuses to start without a fresh key. Needs no database: with no DB file yet it revokes nothing and still writes the key. |
| 4 | `start.sh` (this section), as user `finsolve` | Creates `/var/lib/finsolve/{chroma,raw,demo_corpus,hf-cache}`, copies the demo corpus, validates settings, runs `alembic upgrade head`, then `audit-committed`. This is the only step that creates the schema with a recorded revision. |
| 5 | §7a: `manage_user.py create` (first admin) | The CLI needs the migrated `users` table; it does not create tables. |
| 6 | §8: `systemctl enable --now finsolve` | First start runs `create_tables()` (a no-op on the migrated schema), seeds the public-demo identities and demo documents, indexes the demo corpus (downloads the embedding model into `HF_HOME` on first boot, so the host needs outbound HTTPS to huggingface.co), and refuses to start if a private account still has a committed password hash. |
| 7 | §9: Nginx + TLS, §9a firewall | Nginx proxies to a running backend. |
| 8 | §12 baseline backup, then §10a smoke test and §10b gate | The baseline is the first-deployment rollback point (§14). |

Do not start the service before step 4. At startup the application calls
`Base.metadata.create_all`, which would create tables without an Alembic
revision; that order was not tested and later migrations assume they own the
schema.

```sh
cd /opt/finsolve/app && sudo -u finsolve deploy/production/start.sh
```

Runs settings validation, creates storage directories, copies the synthetic
public-demo corpus into `DEMO_DOCUMENTS_PATH` when `PUBLIC_DEMO_ENABLED=true`
(never overwriting), runs `alembic upgrade head`, and refuses to continue if
any active private account still uses a password hash committed to the
repository (`scripts/manage_user.py audit-committed`). Any failure exits
non-zero and must not be followed by a service start. `start.sh` itself seeds
nothing in the database: public-demo identities and demo documents are seeded
idempotently when the application starts (step 6), so re-running `start.sh` is
safe.

### 7a. Accounts (required before first use)

Production never seeds the sample private accounts (`admin@finsolve.com`,
`tony.sharma@…`, `beta.admin@…`, …): their password hashes are committed and
the passwords appear in repository documentation. Create real accounts with
the operator CLI (password from `FINSOLVE_NEW_PASSWORD` or an interactive
prompt; minimum 12 characters; never printed):

```sh
cd /opt/finsolve/app
sudo -u finsolve sh -c 'set -a; . /etc/finsolve/finsolve.env; set +a; \
  venv/bin/python scripts/manage_user.py create --email <admin-email> \
  --tenant <tenant_id> --role admin --name "Operations Admin"'
```

Further users of that tenant can then be created from the admin dashboard.
`manage_user.py reset-password|deactivate --email …` also revoke the
account's refresh tokens. If a database was ever started in a non-production
mode (which seeds the sample accounts), run `manage_user.py audit-committed`
and deactivate or reset every account it lists; production startup fails
closed until that is done.

## 8. systemd

```sh
sudo cp deploy/production/finsolve.service /etc/systemd/system/finsolve.service
sudo systemctl daemon-reload
sudo systemctl enable --now finsolve
sudo systemctl status finsolve
```

Binds to `127.0.0.1:8000` only, `Restart=on-failure`, no `--reload`, secrets
via `EnvironmentFile=`, logs to journald (`journalctl -u finsolve -f`).

**Exactly one worker.** The rate limiter, response cache and Chroma
`PersistentClient` are process-local and SQLite/Chroma are not designed for
multi-process writers, so the unit pins `--workers 1`. Do not raise it. There
is no `ExecReload` (Uvicorn would simply exit on SIGHUP); use
`systemctl restart finsolve`. Shutdown is graceful for up to 30 s
(`--timeout-graceful-shutdown`), then systemd kills after `TimeoutStopSec=40`.
`UMask=0027` keeps the database, Chroma files and uploads private to the
service account.

**Proxy headers / rate-limit client IP (verified, no change needed):**
Uvicorn 0.24.0 (the pinned version) defaults `proxy_headers=True` and
`forwarded_allow_ips` to `os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")`
(`uvicorn/config.py`) — with no extra flags on the `ExecStart` above, its
`ProxyHeadersMiddleware` already trusts `X-Forwarded-For` exactly when the
connecting peer is `127.0.0.1`, which is exactly how Nginx reaches this
service (`proxy_pass http://127.0.0.1:8000` in `nginx.conf`). `request.client.host`
(read by the rate limiter's `_client_key()` in `security.py`) therefore
already reflects the real visitor IP, not Nginx's loopback address. No
`--proxy-headers`/`--forwarded-allow-ips` flag or unit change is required.

## 9. Nginx

```sh
sudo cp deploy/production/nginx.conf /etc/nginx/sites-available/finsolve
sudo ln -s /etc/nginx/sites-available/finsolve /etc/nginx/sites-enabled/finsolve
sudo nginx -t && sudo systemctl reload nginx
```

Replace `finsolve.example.com` and the certificate paths with real values.
`/api/` accepts request bodies up to 32 MB (`client_max_body_size`; Nginx's
1 MB default would reject uploads before the backend's 10 MB-per-file check).
`/api/chat/stream` has buffering off and a 120 s read timeout (the backend's
own bound is `RAG_HARD_TIMEOUT_SECONDS=45`). FastAPI's `/docs` and
`/openapi.json` are not proxied; those paths fall through to the landing SPA.

### 9a. Firewall

Only 80/443 (and SSH) should be reachable. The API listens on loopback only;
Ollama is not installed in production.

```sh
sudo ufw default deny incoming && sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
ss -ltnp | grep -E ':8000|:11434'   # expect only 127.0.0.1:8000, nothing on 11434
```

## 10. Health check

`/health` is liveness only — it returns 200 unconditionally and never touches
the DB or RAG/vector store. `/health/ready` is the real readiness probe: 200
only when a live DB `SELECT 1` succeeds AND RAG/vector-store initialized
successfully at startup; 503 otherwise. Use `/health` for "is the process
up", `/health/ready` for "is it actually able to serve a real request" (e.g.
before cutting traffic over during a deploy).

```sh
curl -sf https://finsolve.example.com/health
curl -sf https://finsolve.example.com/health/ready
```

### 10a. Post-deployment smoke test (expected results)

```sh
H=https://finsolve.example.com
curl -s -o /dev/null -w '%{http_code}\n' $H/                   # 200 landing
curl -s -o /dev/null -w '%{http_code}\n' $H/app/chat           # 200 (SPA fallback)
curl -s -o /dev/null -w '%{http_code}\n' $H/api/conversations  # 401 (API, not SPA)
curl -s $H/docs | head -c 60                                    # landing HTML, not Swagger
curl -sI $H/app/ | grep -i -E 'strict-transport|content-security'
```

SSE through the proxy as a public-demo visitor (`PUBLIC_DEMO_ENABLED=true`).
Read the **whole** stream to its end — never pipe it to `head`: curl is killed
by SIGPIPE after the first lines, so completion is never observed, and a bare
`data: [DONE]` is also sent after an error. The check below fails unless the
stream starts, carries tokens, ends with exactly one `complete` event that has
`"success": true` and a non-empty `sources` list naming the handbook and an
answer containing `20`, has no `error` event, and ends with `[DONE]`:

```sh
H=https://finsolve.example.com
C=$(mktemp); OUT=$(mktemp)
curl -s -c $C -H "Origin: $H" -H 'Content-Type: application/json' \
  -d '{"role":"employee"}' $H/auth/demo-login >/dev/null
curl -sN --max-time 90 -b $C -H 'Accept: text/event-stream' \
  "$H/api/chat/stream?q=How%20many%20days%20of%20annual%20leave%20do%20full-time%20employees%20get%3F" > $OUT
python3 - "$OUT" <<'PY'
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
answer = "".join(e.get("token", "") for e in ev if e["type"] == "token")
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
    print(("PASS " if ok else "FAIL ") + name)
print("answer:", answer[:160].replace("\n", " "))
sys.exit(0 if all(checks.values()) else 1)
PY
echo "sse-check exit=$?"; rm -f $C $OUT
```

Then in a browser: sign in with the account from §7a, upload a small document
from the admin dashboard, ask about a fact only it contains, confirm the
answer and its citation, reload, and sign out.

### 10b. Host verification gate (required before go-live)

`deploy/production/verify_host.sh` runs every host check and prints PASS/FAIL
per item; exit code = number of failures. It needs a non-demo tenant admin
(from §7a) for the upload and persistence checks; the password is read from
the environment and never printed. It creates one conversation and one small
document (deleted again) and restarts the service once.

```sh
cd /opt/finsolve/app
sudo FINSOLVE_URL=https://<your-domain> FINSOLVE_ADMIN_EMAIL=<admin-email> \
     deploy/production/verify_host.sh
# prompts: Admin password (not echoed):
```

Never put the admin password on the command line or in an environment
variable: it would land in shell history and `/proc/<pid>/environ`. The
checker refuses `FINSOLVE_ADMIN_PASSWORD`. For a non-interactive run, store
the password in an owner-only file and point the checker at it (the file
is read, never printed, and must be mode 600):

```sh
install -m 600 /dev/null /root/.finsolve-verify-pw
${EDITOR:-vi} /root/.finsolve-verify-pw     # type the password; not in history
sudo FINSOLVE_URL=https://<your-domain> FINSOLVE_ADMIN_EMAIL=<admin-email> \
     FINSOLVE_ADMIN_PASSWORD_FILE=/root/.finsolve-verify-pw deploy/production/verify_host.sh
shred -u /root/.finsolve-verify-pw           # remove it afterwards
```

| Section | Expected |
|---|---|
| 1 Config | `nginx -t` ok; `systemd-analyze verify` ok; service active as user `finsolve`; env file `640 root:finsolve` |
| 2 Sockets | only `127.0.0.1:8000`; nothing on `0.0.0.0:8000`/`[::]:8000`; nothing on `:11434`. Also from another machine: `curl -m5 http://<server-ip>:8000/health` must fail to connect |
| 3 Routing | `/` landing (Vite assets); `/app/chat` reload → CRA index; `/app/static/...` 200; `/api/conversations` 401 (FastAPI, not SPA); `/docs` not Swagger; `http://` → 301; HSTS + CSP headers |
| 4 Auth | login 200; `session_token` HttpOnly+Secure+SameSite=Lax; `refresh_token` HttpOnly, Path=/auth; mutation without CSRF 403, with CSRF 200; refresh 200; replayed old refresh 401 |
| 5 SSE | `text/event-stream`; first event < 2 s; events spread over time (not one burst); **full stream**: `start`, tokens, exactly one `complete`, no `error` event, ends with `[DONE]`. Record the printed arrival times and event types as evidence |
| 6 Uploads | 11 MB body passes Nginx (FastAPI answers); 33 MB → 413 from Nginx; an 11 MB file → backend "File too large"; small file indexed; 11 MB body to `/auth/` → 413 |
| 7 Restart | ready after restart; new PID; conversation and document survive; uploaded file content readable |
| 8 Bad config | short key, `["*"]` origins, `DEBUG=true`, missing Groq key, `BYPASS_AUTH=true` each refused with `FATAL` (checked in a separate process; the service is untouched); no account with a committed password hash |

## 11. Logs

- Backend: `journalctl -u finsolve -f`
- Nginx: `/var/log/nginx/access.log`, `/var/log/nginx/error.log`

## 12. Backup and restore

SQLite, Chroma and the raw documents must be captured at the same moment or
they disagree (rows without vectors, vectors for deleted files). A raw copy of
live files is not a consistent backup.

```sh
sudo /opt/finsolve/app/deploy/production/backup.sh
# -> /var/backups/finsolve/<UTC>/ finsolve.db chroma.tar.gz raw.tar.gz
#    finsolve.env (0600) MANIFEST (alembic revision, commit) SHA256SUMS
sudo /opt/finsolve/app/deploy/production/restore.sh /var/backups/finsolve/<UTC>
```

`backup.sh` stops the service for the copy (seconds for small corpora), uses
SQLite's online-backup API plus `PRAGMA integrity_check`, and restarts the
service even on failure. `restore.sh` verifies checksums, moves the current
data aside to `*.pre-restore-<UTC>` (never deletes it), restores, runs
`start.sh` (migrates forward if the code is newer) and starts the service. It
also revokes every refresh token in the restored database, because an older
database would otherwise re-activate tokens revoked after the backup (logouts,
deactivated users, key rotation); everyone signs in again. The env file is
never restored, so a pre-rotation key cannot come back with the data; if you
copy it by hand, startup still refuses committed keys but would accept any
other retired key. Backups contain
secrets (the env file) and private documents: keep `/var/backups/finsolve`
root-only and copy it off-host. Schedule it (cron or a systemd timer).

## 13. Application update procedure

```sh
sudo /opt/finsolve/app/deploy/production/backup.sh   # restarts the service afterwards
sudo systemctl stop finsolve
sudo -u finsolve git -C /opt/finsolve/app pull
sudo -u finsolve /opt/finsolve/app/venv/bin/pip install --require-hashes --no-deps \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r /opt/finsolve/app/requirements-linux-py311.lock
sudo -u finsolve /opt/finsolve/app/venv/bin/pip check
sudo -u finsolve /opt/finsolve/app/deploy/production/start.sh   # migrates
sudo systemctl start finsolve
```

## 14. Rollback

1. `sudo systemctl stop finsolve`
2. `sudo -u finsolve git -C /opt/finsolve/app checkout <previous-tag>`, reinstall
   deps, and redeploy that tag's frontend builds.
3. `sudo deploy/production/restore.sh /var/backups/finsolve/<pre-update-backup>`
   (the data taken before the update, at that release's schema).
4. Health-check (§10) and smoke-test (§10a).

Do not rely on `alembic downgrade`: downgrade paths were not exercised for
this release, and some migrations backfill data that a downgrade cannot
reconstruct. Restore-from-backup is the tested rollback.

### 14a. Rollback for a first deployment (no previous tag, no previous data)

Steps 1–4 above assume a prior release and a pre-update backup. On the very
first deployment neither exists, so "previous-tag" is meaningless and
`backup.sh` has nothing to copy until `start.sh` has created the database. Use
this instead.

**Before cutover**, record what is being deployed (the archive has no `.git`, so
`backup.sh` writes `app_commit=unknown` into each `MANIFEST`):

```sh
# git clone: the candidate commit        archive: the SHA printed with its checksum
sudo -u finsolve git -C /opt/finsolve/app rev-parse HEAD   # or write the SHA down
```

Then take a **baseline backup immediately after step 5 of §7** (database
migrated, first admin created, service stopped or freshly started and idle) and
again once the §10b gate passes:

```sh
sudo /opt/finsolve/app/deploy/production/backup.sh      # -> /var/backups/finsolve/<UTC>/
```

Which rollback applies:

| Situation | Action |
|---|---|
| **A step before the service first started failed** (env check, `start.sh`, admin creation) | Nothing is live. Fix the cause and re-run from that step. `start.sh` is idempotent; if a half-created data directory must be discarded, move it aside (`sudo mv /var/lib/finsolve /var/lib/finsolve.failed-$(date -u +%Y%m%dT%H%M%SZ)`), recreate it with the §2 `mkdir`/`chown`/`chmod` lines and restart at step 4. Do not delete it. |
| **Service or §10b gate fails before DNS points at the host** | Same as above; also `sudo systemctl disable --now finsolve` while fixing. Public traffic is unaffected because DNS was not changed. |
| **Gate fails or a defect appears after DNS cutover** | Take the site out of service first: `sudo rm /etc/nginx/sites-enabled/finsolve && sudo nginx -t && sudo systemctl reload nginx`, then `sudo systemctl stop finsolve`. There is no earlier release to return to, so "rollback" is *withdraw, then redeploy a fixed commit*. Revert DNS only if you changed it. |
| **Data damaged or wrong after first use** (bad upload, mistaken delete, failed manual change) | `sudo systemctl stop finsolve`, then `sudo deploy/production/restore.sh /var/backups/finsolve/<baseline-UTC>` (current data is moved to `*.pre-restore-<UTC>`, never deleted; refresh tokens are revoked, so everyone signs in again), then §10 and §10a. |
| **Code defect, data fine** | `git -C /opt/finsolve/app checkout <candidate-sha>` (or unpack the archive again), reinstall from the lock file, rebuild both frontends, `start.sh`, `systemctl start finsolve`. Without a tag, the candidate commit SHA is the only reference, so keep it in the deployment log; tagging it (for example `git tag rc1 <sha>`) is optional and needs the owner's approval. |

The `.env` file is never part of a restore (§12), so a restore cannot bring an
old `SECRET_KEY` back; re-run §6a if the key itself is suspect.

## 15. Groq failures / quota troubleshooting

- 401/403 → check `GROQ_API_KEY` in `/etc/finsolve/finsolve.env`; provider
  maps this to a generic "service unavailable" to the client (see
  [llm_provider.py](../src/backend/services/llm_provider.py)) — check
  `journalctl` for `LLM_AUTH_ERROR`.
- 429 → `LLM_RATE_LIMITED` in logs with `retry_after`; client sees a
  generic busy message.
- Timeout → confirm `GROQ_TIMEOUT_SECONDS < RAG_HARD_TIMEOUT_SECONDS`.
- "The language model returned an empty response" → look for
  `LLM_EMPTY_RESPONSE ... finish_reason=length reasoning_tokens=N`. Reasoning
  models (`openai/gpt-oss-*`) spend the completion budget on hidden
  reasoning; keep `GROQ_REASONING_EFFORT=auto` (sends `low` to gpt-oss) and/or
  raise `GROQ_MAX_COMPLETION_TOKENS` (default 1024). With the former fixed
  320-token budget, real RAG prompts returned no answer.
- Failed generations are shown to the user with a retry chip and are **not**
  saved to the conversation, so a reload never presents a failure as an
  answer.

## 16. ARM64 note

Not evaluated on real ARM64 hardware in this session. `fastapi`, `uvicorn`,
`SQLAlchemy`, `alembic` are pure-Python and expected to work on ARM64.
`torch` CPU wheels, `chromadb`, and `sentence-transformers` ship
platform-specific binaries; manylinux ARM64 wheels exist for recent versions
of all three on PyPI as of this writing, but this was not installed or run
on ARM64 here — treat as **unverified, likely-compatible** rather than
confirmed.
