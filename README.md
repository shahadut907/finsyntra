# FinSyntra

FinSyntra is a full-stack financial-intelligence assistant. It answers questions from an organization's own documents, in English or Bangla, and shows the source passages behind every answer. Access is role-based and multi-tenant: a user only retrieves documents their role and tenant may see.

Stack: FastAPI, React (CRA) app, Vite landing page, ChromaDB, SQLAlchemy (SQLite or PostgreSQL), Groq or Ollama for inference, and local or Cloudflare Workers AI embeddings.

## Public demo

The public demo runs on a **synthetic** corpus (a fictional company, "Northstar Analytics"). Visitors enter through *Try Demo* with a predefined role and no password; demo identities cannot sign in with a password, and each visitor's conversations are isolated from other visitors'. Nothing in the demo is real company data.

## Architecture

| Part | Where | Notes |
|---|---|---|
| API | `src/backend` | FastAPI, JWT cookies with CSRF, RBAC, SSE streaming chat |
| App | `frontend` | React, served under `/app` |
| Landing page | `landing-source/finsolve_ai_landing` | Vite, served at `/` |
| Migrations | `alembic` | SQLite and PostgreSQL |
| Deployment | `deploy/` | native Linux (`deploy/production`), Render Free (`deploy/render`, `render.yaml`) |

### Embeddings

`EMBEDDINGS_PROVIDER` selects the embedding backend:

- `local` (default): sentence-transformers / PyTorch in process. Needs roughly 1.2 GB of RAM.
- `cloudflare`: Cloudflare Workers AI (`@cf/baai/bge-m3`, 1024 dimensions). PyTorch is never imported, so the backend runs in a few hundred MB. Requires `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` in the environment. There is no silent fallback to the local model.

Each provider writes to its own Chroma collection, so vectors of different dimensions are never mixed.

## Run locally

```bash
python -m venv venv && . venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt                    # use requirements-render.txt for Cloudflare-only
cp .env.example .env                               # then set SECRET_KEY and, if used, GROQ_API_KEY
alembic upgrade head
uvicorn src.backend.api.endpoints:app --port 8000
cd frontend && npm ci && npm start
```

Secrets are read from the environment or an untracked `.env`. Never commit either.

## Accounts and passwords

- Production does **not** seed the private sample accounts, and startup refuses to run if any active private account still uses a password hash shipped in this repository.
- Create real accounts with `python scripts/manage_user.py` (the password is read from a prompt or the environment, never from the command line).
- The admin API has no default password; creating a user requires one.

## Tests

```bash
LLM_PROVIDER=ollama GROQ_API_KEY= python -m pytest tests/test_release_candidate.py tests/test_cloudflare_embeddings.py -o addopts=""
cd frontend && npm test -- --watchAll=false
```

## Before publishing a fork

`python scripts/check_publication_readiness.py` scans tracked files for secrets and local artifacts. Removing a secret from the current files does not remove it from Git history; see [docs/security/publication-remediation.md](docs/security/publication-remediation.md).

## Documentation

- [Native Linux deployment](docs/NATIVE_DEPLOYMENT_RUNBOOK.md)
- [Wave 7 runbook (Groq and Ollama modes)](docs/WAVE7_RUNBOOK.md)
- [Release candidate notes](docs/releases/production-readiness-rc1.md)

## License

See [LICENSE.md](LICENSE.md).
