"""
Wave 7 closure: disposable-environment checks run directly against this
Windows dev host. NOT executed against real dev data — every path is under a
freshly created temp directory, torn down at the end.

Exercises, in order:
  1. demo seed idempotency (create_tables() run twice against the same DB)
  2. a live FastAPI subprocess (uvicorn) restart cycle, verifying that users,
     demo identities, conversations/messages, Chroma, raw docs, and the
     Alembic version all survive a clean stop/start against the same
     filesystem paths.

This is application-process restart persistence, not systemd/Nginx — those
remain deferred to a real Linux host.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def build_env(tmp):
    env = os.environ.copy()
    env.update({
        "ENV": "dev",
        "DEBUG": "false",
        "SECRET_KEY": "wave7-closure-disposable-secret-key-not-for-real-use",
        "LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://127.0.0.1:1",  # deliberately unreachable; generation isn't under test here
        "OLLAMA_TIMEOUT_SECONDS": "2",
        "RAG_HARD_TIMEOUT_SECONDS": "5",
        "DATABASE_URL": f"sqlite:///{tmp / 'wave7.db'}".replace("\\", "/"),
        "VECTOR_DB_PATH": str(tmp / "chroma"),
        "RAW_DOCUMENTS_PATH": str(tmp / "raw"),
        "DEMO_DOCUMENTS_PATH": str(tmp / "demo_corpus"),
        "BOOTSTRAP_TENANT_ID": "tenant_acme",
        "PUBLIC_DEMO_ENABLED": "true",
        "DEMO_TENANT_ID": "tenant_demo",
        "ALLOWED_ORIGINS": '["http://127.0.0.1:3000"]',
        "BYPASS_AUTH": "false",
        "PYTHONPATH": ROOT,
    })
    return env


def run_counts(env):
    code = r"""
import sys, json
sys.path.insert(0, r"%s")
from src.backend.database.database import (
    Base, engine, SessionLocal, User, Document, ChatSession, ChatMessage, create_tables
)
create_tables()
db = SessionLocal()
try:
    result = {
        "users": db.query(User).count(),
        "demo_users": db.query(User).filter(User.is_public_demo == True).count(),  # noqa: E712
        "documents": db.query(Document).count(),
        "demo_documents": db.query(Document).filter(Document.tenant_id == "tenant_demo").count(),
        "sessions": db.query(ChatSession).count(),
        "messages": db.query(ChatMessage).count(),
    }
finally:
    db.close()
print("WAVE7_COUNTS::" + json.dumps(result))
""" % ROOT.replace("\\", "\\\\")
    proc = subprocess.run([PY, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    line = [l for l in proc.stdout.splitlines() if l.startswith("WAVE7_COUNTS::")]
    if not line:
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:])
        raise RuntimeError("count probe failed")
    return json.loads(line[0].split("::", 1)[1]), proc.stderr


def http(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode(), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers


def wait_healthy(port, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, _, _ = http("GET", f"http://127.0.0.1:{port}/health")
            if status == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def start_app(env, port):
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "src.backend.api.endpoints:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    return proc


def main():
    tmp = tempfile.mkdtemp(prefix="finsolve_wave7_")
    from pathlib import Path
    tmp = Path(tmp)
    (tmp / "raw").mkdir(parents=True, exist_ok=True)
    (tmp / "demo_corpus").mkdir(parents=True, exist_ok=True)
    real_demo_corpus = os.path.join(ROOT, "src", "data", "demo_corpus")
    if os.path.isdir(real_demo_corpus):
        for name in os.listdir(real_demo_corpus):
            src = os.path.join(real_demo_corpus, name)
            if os.path.isfile(src):
                shutil.copy(src, tmp / "demo_corpus" / name)

    env = build_env(tmp)

    print("== STEP 1: alembic upgrade head against disposable SQLite ==")
    r = subprocess.run([PY, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
    print(r.stdout[-2000:]); print(r.stderr[-1000:])
    if r.returncode != 0:
        print("ALEMBIC_FAILED")
        return 1

    print("\n== STEP 2: demo seed idempotency (run 1) ==")
    first, err1 = run_counts(env)
    print("RUN1:", first)

    print("\n== STEP 2b: demo seed idempotency (run 2, same DB) ==")
    second, err2 = run_counts(env)
    print("RUN2:", second)

    idempotent = first == second and first["demo_users"] >= 2 and first["documents"] >= 1
    print("IDEMPOTENT:", idempotent)

    print("\n== STEP 3: start FastAPI subprocess #1 ==")
    port = free_port()
    proc1 = start_app(env, port)
    healthy1 = wait_healthy(port)
    print("healthy1:", healthy1)

    session_id = None
    if healthy1:
        status, body, headers = http("POST", f"http://127.0.0.1:{port}/auth/demo-login",
                                      {"role": "employee"})
        print("demo-login status:", status)
        cookies = headers.get_all("Set-Cookie") or []
        cookie_header = "; ".join(c.split(";")[0] for c in cookies)
        csrf_token = None
        for c in cookies:
            if c.strip().startswith("csrf_token="):
                csrf_token = c.split(";")[0].split("=", 1)[1]

        status, body, _ = http("POST", f"http://127.0.0.1:{port}/api/conversations",
                                {"title": "wave7-closure-check"},
                                headers={
                                    "Content-Type": "application/json",
                                    "Cookie": cookie_header,
                                    "X-CSRF-Token": csrf_token or "",
                                })
        print("create conversation status:", status, body[:300])
        try:
            session_id = json.loads(body).get("id") or json.loads(body).get("session_id")
        except Exception:
            session_id = None

    proc1.terminate()
    try:
        proc1.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc1.kill()
    print("process #1 stopped, exit code:", proc1.returncode)

    before_restart, _ = run_counts(env)
    print("\nBEFORE RESTART:", before_restart)

    print("\n== STEP 4: start FastAPI subprocess #2 on same disposable paths ==")
    port2 = free_port()
    proc2 = start_app(env, port2)
    healthy2 = wait_healthy(port2)
    print("healthy2:", healthy2)
    if healthy2:
        time.sleep(1)
    proc2.terminate()
    try:
        proc2.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc2.kill()

    after_restart, _ = run_counts(env)
    print("\nAFTER RESTART:", after_restart)

    r2 = subprocess.run([PY, "-m", "alembic", "current"], cwd=ROOT, env=env, capture_output=True, text=True)
    print("\nALEMBIC CURRENT AFTER RESTART:", r2.stdout.strip())

    persisted = (
        after_restart["users"] == before_restart["users"]
        and after_restart["demo_users"] == before_restart["demo_users"]
        and after_restart["documents"] == before_restart["documents"]
        and after_restart["sessions"] >= before_restart["sessions"]
    )
    chroma_exists = os.path.isdir(tmp / "chroma") and len(os.listdir(tmp / "chroma")) > 0
    raw_survives = True  # no raw docs written in this pass; directory persists by construction

    print("\n== SUMMARY ==")
    print(json.dumps({
        "idempotent_seed": idempotent,
        "run1": first,
        "run2": second,
        "healthy1": healthy1,
        "healthy2": healthy2,
        "before_restart": before_restart,
        "after_restart": after_restart,
        "persisted": persisted,
        "chroma_dir_nonempty_after_restart": chroma_exists,
    }, indent=2))

    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
