"""
Wave 7 closure: real Groq E2E through FinSyntra's actual RAG/provider path,
against the real (existing) dev SQLite DB and Chroma corpus.

Fixed from the previous version: that run deadlocked because it called
`proc.stdout.read()` (blocks until the child's stdout pipe closes) before
`proc.terminate()` — if the health check gave up while the app was merely
slow to start, the read waited forever for a pipe that never closed while
uvicorn kept running. This version drains stdout on a background thread
instead, uses a bounded per-scenario timeout with no retries, and prints
progress immediately (flushed) so a stall is visible while it happens.

No user rows are created/modified; session cookies are minted with the
app's own `create_access_token` (same function `/auth/login` calls after
password verification) since this session does not have the seeded users'
plaintext passwords. RBAC/tenant filtering downstream is untouched and runs
for real. GROQ_API_KEY is never printed.
"""
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
sys.path.insert(0, ROOT)

STARTUP_TIMEOUT_S = 90       # cold start: torch + sentence-transformers + real Chroma corpus
PER_SCENARIO_TIMEOUT_S = 60  # RAG_HARD_TIMEOUT_SECONDS (45) + buffer for HTTP/JSON overhead


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def drain_stdout(proc, sink):
    for line in iter(proc.stdout.readline, ""):
        sink.put(line)


def wait_healthy(port, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def http(method, url, body=None, headers=None, timeout=PER_SCENARIO_TIMEOUT_S):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except urllib.error.URLError as e:
        return None, f"URLError: {e.reason}"
    except TimeoutError:
        return None, "TIMEOUT"


def mint_cookie_header(email, csrf):
    from src.backend.auth.authentication import create_access_token
    token = create_access_token({"sub": email, "type": "access"})
    return f"session_token={token}; csrf_token={csrf}"


def chat(port, email, message, session_id=None):
    csrf = "wave7-e2e-csrf"
    cookie = mint_cookie_header(email, csrf)
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    return http(
        "POST", f"http://127.0.0.1:{port}/api/chat", payload,
        headers={"Content-Type": "application/json", "Cookie": cookie, "X-CSRF-Token": csrf},
    )


def main():
    env = os.environ.copy()
    env["PYTHONPATH"] = ROOT  # real .env, real LLM_PROVIDER=groq, real corpus — no overrides
    env["PYTHONIOENCODING"] = "utf-8"  # the app logs Bangla query/response text to stdout

    port = free_port()
    log(f"starting app on 127.0.0.1:{port} (timeout {STARTUP_TIMEOUT_S}s for cold embeddings/Chroma load)")
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "src.backend.api.endpoints:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    out_q = queue.Queue()
    threading.Thread(target=drain_stdout, args=(proc, out_q), daemon=True).start()

    healthy = wait_healthy(port, STARTUP_TIMEOUT_S)
    if not healthy:
        log("APP_FAILED_TO_START within timeout — terminating (not reading stdout synchronously)")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        tail = []
        while not out_q.empty():
            tail.append(out_q.get_nowait())
        print("".join(tail[-60:]))
        return 1
    log("app healthy")

    scenarios_def = [
        ("employee_en_handbook", "employee@finsolve.com",
         "What is the company's policy on paid time off?", None),
        ("finance_en_financial", "finance.lead@finsolve.com",
         "What was the company's revenue performance last quarter?", None),
        ("employee_en_followup", "employee@finsolve.com",
         "Can you summarize that in one sentence?", "__use_employee_en__"),
        ("employee_bn_handbook", "employee@finsolve.com",
         "কোম্পানির ছুটির নীতি সম্পর্কে বলুন।", None),
        ("employee_bn_followup", "employee@finsolve.com",
         "এটা সংক্ষেপে বলুন।", "__use_employee_bn__"),
        ("finance_bn_financial", "finance.lead@finsolve.com",
         "গত প্রান্তিকে কোম্পানির রাজস্ব পারফরম্যান্স কেমন ছিল?", None),
        ("employee_unauthorized_finance", "employee@finsolve.com",
         "What is the exact revenue and profit margin breakdown for last quarter?", None),
        ("tenant_beta_cross_tenant_probe", "beta.employee@finsolve.com",
         "What is the company's policy on paid time off?", None),
    ]

    session_map = {}
    results = []

    for name, email, message, follow_key in scenarios_def:
        session_id = None
        if follow_key == "__use_employee_en__":
            session_id = session_map.get("employee_en_handbook")
        elif follow_key == "__use_employee_bn__":
            session_id = session_map.get("employee_bn_handbook")

        log(f"RUN {name} (email={email}) ...")
        t0 = time.time()
        status, body = chat(port, email, message, session_id)
        latency = round(time.time() - t0, 2)

        outcome = "FAIL"
        parsed = {}
        if status is None:
            outcome = "TIMEOUT" if body == "TIMEOUT" else "NETWORK_ERROR"
        elif status == 200:
            outcome = "PASS"
            try:
                parsed = json.loads(body)
                session_map[name] = parsed.get("session_id")
            except Exception:
                outcome = "MALFORMED_RESPONSE"
        elif status == 429:
            outcome = "RATE_LIMITED"
        else:
            outcome = f"HTTP_{status}"

        log(f"  -> {outcome} in {latency}s (http_status={status})")

        results.append({
            "scenario": name,
            "email": email,
            "outcome": outcome,
            "http_status": status,
            "latency_s": latency,
            "documents_found": parsed.get("documents_found"),
            "sources": parsed.get("sources"),
            "response_preview": (parsed.get("response") or (body[:300] if isinstance(body, str) else ""))[:400],
        })

    log("stopping app")
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    print("\n=== RESULTS ===")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
