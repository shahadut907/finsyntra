"""Wave 7 closure: concurrency probe against the real server + real Groq.

Fires one Bangla /api/chat request and, while it's in flight, repeatedly
polls /health and one authorized lightweight /auth/me call, confirming they
stay fast. This is the same class of evidence as the pytest regression test,
but against the real dev corpus/Groq path instead of a mock.
"""
import json
import os
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


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_healthy(port, timeout=90):
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


def http(method, url, body=None, headers=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return None, str(e)


def mint_cookie_header(email, csrf):
    from src.backend.auth.authentication import create_access_token
    token = create_access_token({"sub": email, "type": "access"})
    return f"session_token={token}; csrf_token={csrf}"


def main():
    env = os.environ.copy()
    env["PYTHONPATH"] = ROOT
    env["PYTHONIOENCODING"] = "utf-8"

    port = free_port()
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "src.backend.api.endpoints:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    threading.Thread(target=lambda: [None for _ in iter(proc.stdout.readline, "")], daemon=True).start()

    if not wait_healthy(port):
        log("APP_FAILED_TO_START")
        proc.terminate()
        return 1
    log("app healthy")

    csrf = "probe-csrf"
    cookie = mint_cookie_header("employee@finsolve.com", csrf)

    chat_result = {}

    def run_chat():
        t0 = time.time()
        status, body = http(
            "POST", f"http://127.0.0.1:{port}/api/chat",
            {"message": "কোম্পানির ছুটির নীতি সম্পর্কে বিস্তারিত বলুন।", "session_id": "concurrency-probe"},
            headers={"Content-Type": "application/json", "Cookie": cookie, "X-CSRF-Token": csrf},
        )
        chat_result["status"] = status
        chat_result["latency"] = round(time.time() - t0, 2)

    chat_thread = threading.Thread(target=run_chat)
    chat_thread.start()
    time.sleep(0.1)  # let the chat request actually reach the server

    health_latencies = []
    me_latencies = []
    while chat_thread.is_alive():
        t0 = time.time()
        hs, _ = http("GET", f"http://127.0.0.1:{port}/health", timeout=5)
        health_latencies.append((hs, round(time.time() - t0, 2)))

        t0 = time.time()
        ms, _ = http("GET", f"http://127.0.0.1:{port}/auth/me",
                      headers={"Cookie": cookie}, timeout=5)
        me_latencies.append((ms, round(time.time() - t0, 2)))
        time.sleep(0.2)

    chat_thread.join()

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    log(f"chat result: {chat_result}")
    log(f"/health calls during chat: {health_latencies}")
    log(f"/auth/me calls during chat: {me_latencies}")

    max_health = max((lat for _, lat in health_latencies), default=0)
    max_me = max((lat for _, lat in me_latencies), default=0)
    all_health_ok = all(s == 200 for s, _ in health_latencies)
    all_me_ok = all(s == 200 for s, _ in me_latencies)

    print(json.dumps({
        "chat_status": chat_result.get("status"),
        "chat_latency_s": chat_result.get("latency"),
        "concurrent_health_calls": len(health_latencies),
        "max_health_latency_s": max_health,
        "all_health_200": all_health_ok,
        "concurrent_me_calls": len(me_latencies),
        "max_me_latency_s": max_me,
        "all_me_200": all_me_ok,
        "server_stayed_responsive": max_health < 1.0 and max_me < 1.0 and all_health_ok and all_me_ok,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
