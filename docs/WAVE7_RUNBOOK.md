# FinSyntra Wave 7 Runbook

> Canonical production deployment is native Linux (Nginx + systemd + FastAPI +
> Groq) — see [docs/NATIVE_DEPLOYMENT_RUNBOOK.md](NATIVE_DEPLOYMENT_RUNBOOK.md).
> Docker Compose below is retained only as a local dev/demo simulation and is
> not the supported production path.

## Local development: Ollama

1. Copy `.env.example` to `.env` and generate a local `SECRET_KEY`.
2. Keep `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://localhost:11434`, and `OLLAMA_MODEL=llama3.2:3b`.
3. Start Ollama and ensure `llama3.2:3b` is installed.
4. Run `alembic upgrade head`.
5. Start the API with `uvicorn src.backend.api.endpoints:app --reload --port 8000`.
6. In `frontend`, run `npm start`.

Local embeddings and Chroma remain self-contained. The local mode does not require a Groq key.

## Production-like local simulation: Groq

Set these values in the shell or an untracked environment file:

```text
SECRET_KEY=<cryptographically random value>
GROQ_API_KEY=<server-side Groq credential>
GROQ_MODEL=<currently supported Groq chat model>
ALLOWED_ORIGINS=["http://localhost:8080"]
```

Then run:

```text
docker compose -f docker-compose.production.yml up --build
```

Open `http://localhost:8080`. Only nginx is published. FastAPI, SQLite, and Chroma stay on the internal Compose network or named volumes. Ollama is not part of this topology.

For a real public origin, set `ENV=production` and use an explicit HTTPS `ALLOWED_ORIGINS` value. Production startup rejects a missing Groq key/model, weak signing key, wildcard origin, non-HTTPS origin, or an insecure Groq base URL.

## Public-demo controls

`PUBLIC_DEMO_ENABLED=true` enables only the predefined Demo Admin and Demo Employee login choices. They share `tenant_demo`, use normal access/refresh cookies and refresh-token rotation, and cannot mutate users or shared documents. Private admin credentials are never shown by the landing page and retain the normal tenant-admin capabilities.

Do not place `GROQ_API_KEY`, `SECRET_KEY`, `.env`, SQLite files, Chroma data, or uploaded documents in an image or commit.
