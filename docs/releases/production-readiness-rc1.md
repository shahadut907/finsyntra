# FinSyntra production-readiness report — release candidate 1

Date: 2026-10-30 (pass 4: dependency reproducibility; pass 3: PDF stack, parsing and SSE) · Branch: `rc/production-readiness` (from `master` @ `3091f6b18`, changes **uncommitted**) ·
Assessor environment: Windows 11 dev workstation, Python 3.11.6, Node 20.19.2, Uvicorn 0.24.0,
FastAPI 0.116.2 / Starlette 0.48.0 / python-multipart 0.0.32 (upgraded in pass 2), ChromaDB 0.4.22,
pdfminer.six 20251230 / pdfplumber 0.11.9 / pypdfium2 4.30.0 / Pillow 13.0.0 (pass 3; PyPDF2 removed),
Groq `openai/gpt-oss-20b` (dev key).

| Area | Status |
|---|---|
| **Application verification** | PASS on final code: release gate (38 files) 660 passed / 0 failed / 3 skipped (§3a-2); PDF upload→chat acceptance 28/28 on a fresh environment with the final dependency set and real Groq (§3e); core flow 89/89 (pass 2, §4); key rotation and restore guarantees exercised on a running service (§3d) |
| **Remaining test failures** | Release gate: 663 collected → 660 passed, 0 failed, 3 skipped (PostgreSQL-only, out of launch scope; NOT VERIFIED). Full tree: 1,107 → 874 passed, 206 failed, 23 errors, 4 skipped. Compared by test identity with the pass-2 run: 0 newly failing, 6 fixed (5 `test_document_parsing`, 1 order-dependent SSE); none of the 229 remaining failures passed in the pre-change baseline (§3a-2) |
| **Dependency risk** | PDF stack remediated: pdfminer.six code-execution CVEs fixed, PyPDF2 removed, Pillow raised to the first release with no open advisories; PDF support preserved (§3c, §3e). Remaining: PyJWT, routine upgrades and frontend jspdf — not reachable in current code (§3c) |
| **Dependency reproducibility** | `torch` pinned to the tested 2.7.1; new hashed lock `requirements-linux-py311.lock` (133 packages, every tested package at its tested version, CPU torch). Resolved and every artifact hash-verified for Linux cp311 from this host. **Install on Linux: NOT VERIFIED** — no isolated Linux environment available (§3f) |
| **Secret-rotation prerequisites** | Production refuses all 10 committed signing keys; the operator must install a fresh key with `scripts/rotate_secret_key.py` (runbook §6a). No Groq key found in any history blob (§3b) |
| **Host verification** | **NOT VERIFIED** — no Linux host available; gate script `deploy/production/verify_host.sh` + expected results ready (runbook §10b) |
| **Deployment** | **NOT DEPLOYED** |

**Verdict: NOT READY FOR LAUNCH until (1) `requirements-linux-py311.lock` installs
cleanly on Linux with `pip check`, import and PDF checks passing (§3f), (2) the host
gate (runbook §10b) passes on the real Linux host and (3) a fresh signing key is
installed (runbook §6a).** The
two application-level owner decisions from pass 2 are closed: the PDF parser
risk is remediated with PDF support preserved, and the order-dependent SSE test
is root-caused and fixed (§3a-2, §3e). All application checks in scope pass.

Status vocabulary: **PASS** (executed, evidence below) · **FAIL** · **NOT VERIFIED**
(not executed; reason given) · **N/A** (with reason).

## 1. Scope and method

- API routes: `/api/*` (chat, SSE, conversations, documents, admin, knowledge),
  `/auth/*` (login, demo-login, refresh, logout, me), `/health`, `/health/ready`.
- All runtime testing used isolated SQLite/Chroma/document directories under a
  scratch directory, freshly migrated, with accounts created by
  `scripts/manage_user.py`. Development and production data were never touched.
- End-to-end traffic went through a local same-origin edge that mirrors
  `deploy/production/nginx.conf` routing (landing at `/`, CRA at `/app` with
  SPA fallback, unbuffered proxy for `/api`, `/auth`, `/health`). This is **not**
  a substitute for running real Nginx (§6).
- Real Groq was used for chat (bounded, ~70 requests total). Failure paths were
  tested with deterministic fakes.
- Synthetic documents with unguessable facts: tenant A general (`HELIOTROPE-7`,
  BDT 48,731,205), tenant A finance-restricted (`KESTREL-19`, USD 3,917,442; PDF
  `ZEPHYR-3301`, USD 271,908), tenant A Bangla (`নীলকণ্ঠ-৪২`, ৭৩,৫১৯,০৮৮ টাকা),
  tenant B (`MARIGOLD-55`, EUR 12,604,377), and a prompt-injection document.

## 2. Findings register

| ID | Sev | Flow | Evidence | Root cause | Fix | Verification | Status |
|---|---|---|---|---|---|---|---|
| F-01 | P0 | Auth | All 16 seeded accounts (incl. private tenant admins `admin@finsolve.com`, `beta.admin@…`, c_level `tony.sharma@…`) have passwords present in repo docs/tests; `create_tables()` seeded them in every environment incl. production | Sample accounts with committed bcrypt hashes seeded unconditionally | Production seeds only public-demo identities; production startup and `start.sh` fail closed if an active private account uses a committed hash; `/auth/login` rejects public-demo identities; new `scripts/manage_user.py` (create/reset/deactivate/audit) | `test_release_candidate.py` (4 tests); CLI used to provision all E2E accounts | Fixed |
| F-02 | P1 | Document delete | Admin delete unlinked the file but left Chroma chunks; deleted facts stayed answerable and citable | Delete never touched the vector store or response cache | Verified vector removal first (`raise_on_error`), then cache clear, DB deactivate, file unlink; protected demo docs refused | Unit tests (3); runtime: fact not retrievable/cited after delete, 404 on content, no stale chunks, re-upload allowed | Fixed |
| F-19 | P1 | Data integrity | `_check_document_status()` (every startup) synced `"src/data/raw"` (CWD-relative, ignoring `RAW_DOCUMENTS_PATH`) and deleted every bootstrap-tenant source absent from it | Hard-coded path + prune of all non-present sources | Sync the configured path; prune only bundled (classified) filenames, never uploads | 2 failing-then-passing unit tests | Fixed |
| F-11 | P1 | Chat (Groq) | Real Groq: "The language model returned an empty response"; log `finish_reason=length reasoning_tokens=318` of 320 | Fixed 320-token budget consumed by gpt-oss hidden reasoning | `GROQ_MAX_COMPLETION_TOKENS` (1024) and `GROQ_REASONING_EFFORT` (`auto` → `low` for gpt-oss); empty-content diagnostics | Unit tests (6); real Groq: all chat answers correct | Fixed |
| F-07 | P1 | Deploy | `nginx.conf` had no `client_max_body_size` (default 1 MB) vs backend 10 MB/file | Missing directive | `client_max_body_size 32m` on `/api/` | Config review only | Fixed (NOT VERIFIED on Nginx) |
| F-10 | P1 | Deploy/demo | `DEMO_DOCUMENTS_PATH=/var/lib/finsolve/demo_corpus` was only `mkdir`-ed; demo would start with no documents | Missing provisioning step | `start.sh` copies the corpus (no overwrite) and fails if empty | Shell syntax check; demo corpus answers verified at runtime (dev path) | Fixed (host run NOT VERIFIED) |
| F-08 | P2 | SSE/persistence | RAG timeout or pipeline error produced "I couldn't find documents…" and was saved; failed generations saved as normal answers | Exception branch fell back to the general "no docs" reply; persistence ignored `success` | Failures stream a curated message with `complete.success=false` and are **not persisted** | Unit tests (3) incl. timeout; runtime interruption test | Fixed |
| F-09 | P2 | CSRF | `GET /api/chat/stream` mutates state with cookie auth; SameSite=Lax cookies accompany cross-site top-level navigation | CSRF middleware covers only unsafe methods | Reject `Sec-Fetch-Site: cross-site` and non-allowlisted `Origin` on the GET stream | Unit tests (3); runtime 403 | Fixed |
| F-12 | P2 | Prompt injection | Injected doc made the model print its system prompt and steer answers | Rules and retrieved text in one user message; low-relevance chunks padded every prompt | Rules in system channel; documents delimited and marked untrusted; relevance floor (≥0.6×top) on prompt context; deterministic block on answers that reproduce instruction lines | Unit tests (4); runtime: no disclosure, no restricted data | Mitigated (prompting cannot guarantee resistance; RBAC is enforced before retrieval) |
| F-13 | P2 | Citations | Every retrieved doc (up to 8) cited, incl. docs never shown to the model and on "I don't know" replies | `sources` = all verified docs | Cite only in-prompt docs that score near the top or whose figures the answer reproduces | Unit tests (6); runtime: single correct citation per answer, none for no-evidence | Fixed |
| F-20 | P2 | Grounding | Employee without access got an invented "BDT 9,876,543,210" | Model fabrication | If an answer states figures and none occurs in the prompt documents/question, replace with an honest no-evidence answer and cite nothing | Unit tests (2); runtime re-test | Mitigated |
| F-21 | P2 | Chat | Authorized finance user refused ("can't provide that information") for a doc marked "Only finance may view" | Model made its own access decision | System prompt states the server has already authorized every provided document | Runtime: answered on repeated runs | Fixed |
| F-17 | P2 | Follow-up | "Who may view it?" → generic "couldn't find documents" | Follow-ups recognised only by fixed phrases | Short questions with a referring pronoun use history for retrieval; follow-up wording targets the current question | Runtime: pronoun follow-up correct on 3 consecutive runs | Fixed |
| F-03 | P2 | RBAC metadata | `/api/documents/list` and `/status` returned every department's filenames to any role | Missing department scoping (already present in `/api/knowledge/stats`) | Same role-department scoping | Unit test; runtime employee list | Fixed |
| F-04 | P2 | Upload | Identical content indexed twice → duplicate chunks/citations | No content check | 409 with the existing filename (per tenant, active docs) | Unit + runtime | Fixed |
| F-05 | P2 | Availability | PDF parse + embedding ran on the event loop during upload | Sync CPU work in async handler | `asyncio.to_thread` | Concurrency probe | Fixed |
| F-06 | P2 | Admin UX | Upload success showed "undefined"; partial failures silent; real rejection reasons replaced by "Upload rejected"; UI claimed 50 MB | Backend/frontend contract mismatch | Backend returns `message`, `total_chunks`, per-file `status`/reason; UI shows errors; 10 MB limit | UI (real admin dashboard) + API | Fixed |
| F-16 | P2 | UI honesty | Mic button announced "Voice recording started" and recorded nothing; attach button did nothing | Placeholder handlers | Controls removed from both composers | Build + UI | Fixed |
| F-14 | P2 | Config | Production accepted any non-blocklisted `SECRET_KEY` (e.g. 28 chars) | Blocklist-only check | Minimum 32 characters in production | Subprocess test | Fixed |
| F-15 | P3 | UI | Department dialog rendered twice; toasts stuck and blocked header actions (duplicate `Date.now()` keys); storage names with UUIDs in citation chips; mobile header covered first messages | — | Single dialog; sequential toast ids; display original names; top inset | UI checks desktop + 390 px | Fixed |
| F-18 | P3 | Ingestion | `print("📄 …")` could raise on a cp1252 stdout and be swallowed as "no indexable content" | Print inside broad `except` | `logging` | Test batch | Fixed |
| F-22 | P3 | Runbook | `/etc/finsolve` left root:root 0750 (start.sh could not read env); "backup" was a raw copy; rollback relied on untested `alembic downgrade`; no first-admin path | Docs | Runbook rewritten sections; `backup.sh`/`restore.sh` | Backup → loss → restore executed | Fixed |
| F-23 | P3 | systemd | `ExecReload` sent SIGHUP (Uvicorn exits); worker count implicit | — | No ExecReload; `--workers 1`, graceful shutdown 30 s, `TimeoutStopSec=40`, `UMask=0027` | Flags verified against installed Uvicorn | Fixed (systemd run NOT VERIFIED) |
| F-24 | P1 | Availability | FastAPI 0.104.1 / Starlette 0.27.0 / python-multipart 0.0.6: request bodies for `UploadFile`/`Form` are parsed **before** auth runs, so any client can trigger CVE-2024-24762 (Content-Type ReDoS), CVE-2024-53981, CVE-2026-42561/40347 (multipart DoS), CVE-2024-47874/2025-54121 (Starlette multipart) against the single worker | Outdated request-parsing stack | Upgraded to fastapi 0.116.2 + starlette 0.48.0 + python-multipart 0.0.32 (keeps pydantic 2.5 / chromadb 0.4.22; Starlette 1.x would force a pydantic upgrade) | Relevant suite 628/0/3 and core flow 89/89 on the new stack | Fixed |
| F-25 | P2 | Auth/rate limit | Security middleware chose the CSRF exemption and rate-limit bucket from `request.url.path`, which a crafted `Host` can make differ from the routed path (CVE-2026-48710 in Starlette < 1.0.1): a client could move `/auth/login` into the 60/min general bucket | Decision on reconstructed URL | Decide on `request.scope["path"]` | 2 regression tests with poisoned Host on Starlette 0.48 | Fixed |
| F-26 | P2 | Availability | Starlette < 1.3.1 parses `application/x-www-form-urlencoded` without field/size limits (CVE-2026-54283); the app never accepts that type | — | Middleware refuses urlencoded bodies with 415 before any parsing | Regression test | Fixed |
| F-27 | P1 | Secrets | 10 distinct signing-key values are in Git history (`.env`, `.env.backup`, `.env.bak.audit`, `env.example`, `jwt_key.txt`, `secret_key.txt`, docs); production accepted them; `cookies.txt` in history holds 2 session JWTs signed with one of them | Committed secrets | Production refuses those keys by SHA-256 fingerprint (extensible via `FINSOLVE_COMPROMISED_KEY_SHA256`); `scripts/rotate_secret_key.py` installs a fresh key without printing it and revokes refresh tokens | 4 tests + live rotation 5/5 (§3d) | Fixed (operator must rotate in production) |
| F-28 | P2 | Sessions | Restoring an older DB re-activated refresh tokens revoked after the backup (logouts, deactivations, rotation) | Restore copied token table verbatim | `restore.sh` revokes all refresh tokens after restoring; env file is never restored | Backup→restore on disposable data: 5 active → 0, env unchanged | Fixed |
| F-29 | P3 | Output safety | The "no documents" fallbacks quoted the raw user query into the assistant answer (streamed, persisted, exported), e.g. `<script>…` or `os.environ['SECRET_KEY']` | Query echo in templates | No echo | `test_security` XSS/injection cases | Fixed |
| F-30 | P3 | Config honesty | `BLOCK_BACKUP_FOLDERS` declared (default on) but never implemented | — | VectorStore refuses to open a store under a `*backup*` folder | `test_backup_folder_blocking` | Fixed |
| F-31 | P3 | Robustness | Stream handler used `hasattr(app.state, "rag")`; a present-but-`None` slot crashed every stream (surfaced as a test-order dependence after another module cleared the slot). Not reachable in production, where startup fails closed without RAG | Wrong fallback test | `getattr(..., None) or RAGService()` | Failing order re-run: 84/84 | Fixed |

Test-infrastructure fixes (no product behaviour change): per-test rate-limiter reset
(429 cascade), session-level schema creation (order dependency), stale token
fixtures repointed at seeded users with `type: access`, UTF-8 reads on Windows, a
mock that returned zero chunks for a positive-path test. Pass 2: seven tests
(four of mine, three pre-existing) built "bare" `RAGService`/`VectorStore` objects
with the classes' singleton `__new__` and then replaced their vector store,
provider or collection — mutating the **shared** instance used by later tests
(found as a full-tree-only failure in `test_stream_contract`). They now use
`object.__new__`, so no test alters shared state.

## 3. Verification summary

| Check | Command / procedure | Result |
|---|---|---|
| Relevant backend suite (36 contract files + `test_release_candidate.py`), final code | `LLM_PROVIDER=ollama GROQ_API_KEY= DEBUG=false venv/Scripts/python.exe -m pytest <37 files> -o addopts="" -p no:cacheprovider -v -rs` | **631 collected: 628 passed, 0 failed, 0 errors, 3 skipped** (PostgreSQL-only, §3a). Pass 1 of this file set: 399 passed / 38 failed |
| Release-candidate regression file | `pytest tests/test_release_candidate.py` | 44 collected, 44 passed (part of the above) |
| Frontend unit tests | `CI=true npx react-scripts test --watchAll=false` | PASS — 10 suites, 30 tests |
| CRA production build | `REACT_APP_PUBLIC_DEMO_ENABLED=true npm run build` | PASS; `homepage=/app`; no inline scripts (compatible with `script-src 'self'`); no secrets in bundle |
| Landing production build | `npm run build` (Vite 5.4.21) | PASS |
| Fresh migration | `alembic upgrade head` on empty DB | PASS 0001→0005 |
| Legacy upgrade | copy of pre-Alembic `backups/db.pre-wave4…` → head | PASS: 157 sessions/702 messages kept, integrity ok, FK ok, idempotent; 127 ownerless sessions left `tenant_id NULL` (unreachable by design) |
| Backup/restore | `backup.sh` → corrupt DB, wipe Chroma+raw → `restore.sh` | PASS: identical counts, revision, raw files, Chroma bytes; tampered archive refused |
| Concurrency (local, not capacity) | 6 concurrent SSE chats (3 users) + 1 upload | PASS 7/7, 0 errors, 1.5–4.2 s each; `/health` max 2.0 s (see caveat C-2) |

### 3a. Disposition of the 38 pass-1 failures

Baseline comparison: `baseline_v.txt`, a verbose full-suite run started before any
code change in this engagement (same venv, same `LLM_PROVIDER=ollama`, same
isolated fixtures). 37 of the 38 failed there too; `test_health_no_external_calls`
passed there and failed later on latency only. Limitation: the baseline is the
working tree as found (your uncommitted work included), not `HEAD`; `HEAD` alone
does not represent the pre-change state.

| Group (tests) | Actual failure and cause | Launch scope | Pre-existing? | Disposition |
|---|---|---|---|---|
| `test_enterprise_rag` (9) | `from src.config import settings` imported the module, not the `Settings` instance → every fixture errored. Behind it: assertions on lifecycle metadata (`is_active`, `deleted_at`) that vectors never store, an unpersisted `relevance` key, `$and` with one clause, a test-named tmp dir containing "backup", and a PostgreSQL-only deletion worker | Tenant isolation, deletion, precision: yes. PostgreSQL deletion worker/reconciler: no (SQLite launch; `ENABLE_DELETION_WORKER=false`; the lifecycle migration was already moved to `alembic/legacy_unrunnable/` in your pre-existing work) | Yes (9 errors) | Import fixed; assertions moved to the shipped contract (explicit tenant, hard delete, source-based precision; same 0.8 threshold); `BLOCK_BACKUP_FOLDERS` implemented (F-30). **6 pass, 3 skipped only when PostgreSQL is unreachable** (precondition skip with reason) — NOT VERIFIED, out of launch scope. Measured on real Chroma: P95 0.089 s over 10k chunks, precision@5 1.00 |
| `test_rag_tenant_isolation` (5) | Generation needed a live Ollama; `from main import app` (empty `main.py`); login to non-existent `/api/auth/login` as non-existent users; `Department.EMPLOYEE` (does not exist; employees read `GENERAL`) | Yes (finance-vs-HR isolation, golden retrieval, SSE citations) | Yes | Deterministic quote-first-document provider (retrieval/RBAC real); real app import; real `/auth/login` with users created in the isolated DB; enum fixed. 6/6 pass, isolation assertions unchanged |
| `test_security_hardening_v2` (6) | `_build_user` removed (identity is DB-authoritative); `deps.py` no longer has any fallback user; refresh deliberately does not trust tenant claims; `MagicMock` `headers.get` ignored its default; `railway.env.example` now uses `MUST_BE_SET_VIA_ENV` (your staged change) | Yes (auth) | Yes | Re-pointed to the current, stricter contract: missing tenant → 401; `deps.py` only re-exports authoritative deps; refresh must call `resolve_active_user`; mock fixed and the authoritative extractor also asserted; every secret-bearing key must be empty or the placeholder. 38/38 pass |
| `test_chat_sessions` (8), `test_streaming` (5) | Used `mock_auth_bypass`, which sets a `BYPASS_AUTH` flag the app no longer honours (bypass was removed) | Yes (SSE contract, persistence) | Yes | Real DB-backed tokens via the `auth_token` fixture (no bypass reintroduced). 24/24 pass |
| `test_security` (2) | URL built with raw newlines → `httpx.InvalidURL`; and the stream echoed the query (`<script>`, `os.environ['SECRET_KEY']`) through the "no documents" fallback | Yes | Yes | Payload passed as query params; product fix F-29 (no echo). Pass |
| `test_tenant_isolation::test_finance_role_sees_only_own_tenant_finance_docs` (1) | Asserted department filtering against its own mock search, which filtered tenant only | Yes (RBAC) | Yes | Now runs the real `VectorStore.search_documents` where-clause against a collection that evaluates Chroma `$and/$eq/$in`. Pass |
| `test_auth_security::test_secret_key_not_predictable` (1) | Substring heuristic on the local random key ("dev" occurs by chance) while missing the real risk | Yes (secrets) | Yes | Asserts the configured key is not a committed key, not a weak default, ≥32 chars. Pass |
| `test_sse_auth_cors::test_health_no_external_calls` (1) | Latency proxy (avg < 50 ms, no warm-up): 57 ms on the memory-starved host | Yes | No (passed in baseline) — environment timing | Now fails on any outbound HTTP (`requests`/`httpx`/`urllib`) during `/health`; latency bound kept after a warm-up. Pass |

### 3a-2. Final suite results (pass 3 supersedes pass 2)

Common command prefix (Git Bash, repo root): `PYTHONIOENCODING=utf-8 LLM_PROVIDER=ollama GROQ_API_KEY= DEBUG=false venv/Scripts/python.exe -m pytest -o addopts="" -p no:cacheprovider -v`
(Ollama is not running, so no test can reach a live LLM; isolated temp SQLite/Chroma via the root `conftest.py`).

| Suite | Scope | Pass 2 | Pass 3 (final code and dependency set) |
|---|---|---|---|
| **Relevant suite (release gate)** | 36 contract files + `tests/test_document_parsing.py` (added in pass 3, now root-caused and green) + `tests/test_release_candidate.py` (list: `test_api_endpoints, test_enterprise_rag, test_rag_tenant_isolation, test_env_example, test_publication_readiness, test_bootstrap_classification, test_chat_event_loop, test_conversation_persistence, test_data_isolation, test_db_selection, test_generation_semantics, test_knowledge_stats, test_migrations, test_phase2_demo_identities, test_phase3_visitor_isolation, test_phase3_vsid_session_id_derivation, test_phase4_deployment_hardening, test_security_hardening, test_security_hardening_v2, test_startup_readiness, test_tenant_indexing_contract, test_vector_store_safety, test_wave5_security, test_wave6_runtime, test_wave7_provider_demo, test_auth_security, test_document_upload_auth, test_sse_auth_cors, test_stream_contract, test_tenant_isolation, test_rbac_retrieval_filter, test_rbac_security, test_input_validation, test_security, test_streaming, test_chat_sessions`) | 631 collected: 628 passed, 0 failed, 3 skipped (37 files) | **663 collected: 660 passed, 0 failed, 0 errors, 3 skipped** (38 files, exit 0; +20 parsing, +12 PDF tests) |
| Entire tree (reference, run once) | `tests/` (adds legacy `tests/unit/*`, `critical_*`, `medium_*`, `low_*` and older suites) | 1,095 collected: 856 passed, 212 failed, 23 errors, 4 skipped | **1,107 collected: 874 passed, 206 failed, 23 errors, 4 skipped** (exit 1). By test identity vs pass 2: 0 newly failing; fixed: the 5 `test_document_parsing` tests and `test_stream_contract::test_small_talk_returns_tokens_not_422`; 12 new tests, all passing |

"Test-isolation fixes" = the seven tests that mutated the `RAGService`/`VectorStore`
singletons (above). They did not change any count: the one relevant-set test that
fails only in full-tree order (below) is caused by something else.

**Why the relevant suite is the release gate.** Its files encode the current
contract of the SQLite/single-worker deployment (auth, CSRF, RBAC, tenant
isolation, demo restrictions, upload lifecycle, retrieval, citations, SSE,
persistence, migrations, startup fail-closed, config validation) and every
module they exercise is on a production request path. It runs green as a set.
The full tree additionally contains suites written against earlier designs.
The gate is *not* "pre-existing ⇒ harmless": each full-tree failure group below
was checked for whether it exercises production code.

**Full-tree failures (229 = 206 failed + 23 errors after pass 3), by shared root cause.** All
229 also failed in the pre-change baseline; no test that passed in the baseline fails now.

| Group | Count | Root cause | Exercises production path? | Launch impact |
|---|---|---|---|---|
| `tests/unit/{hr_card, grounding_validator, audit_log, entity_registry, table_retriever, policy, query_rewriter, answer_consistency, memory, retrieval, language}` | 199 | API drift: constructors/methods renamed since the tests were written | No for 9 of 11 modules: grep finds **no production importer** of `formatters.hr_card`, `rag.grounding_validator`, `audit.log`, `entities.registry`, `retrieval.table_retriever`, `policy.engine`, `rag.query_rewriter`, `rag.answer_consistency`; `memory.session_kv` is imported only by those unused modules. `unit/test_retrieval` (7) and `unit/test_language` (3) touch `RAGService`/`language_utils` with outdated signatures | None for unused modules. Retrieval/language behaviour is covered by the relevant suite and E2E (Bangla, mixed) |
| `test_collection_cache_fixes` | 12 | Same import bug as `test_enterprise_rag` (`from src.config import settings` → module); flags `CANONICAL_COLLECTION_ENFORCED`, `ENABLE_CROSS_PROCESS_CACHE_SYNC` | Flags default off; cross-process sync only matters with >1 worker (production pins 1) | None at launch scope; not fixed (out of this closeout) |
| `test_document_parsing` | 5 → **0** | **Fixed in pass 3 (app defect).** Not intended validation and not a broken fixture or config pollution: `DocumentProcessor.process_markdown` (also used for `.txt`) dropped every chunk of ≤ 50 characters — a floor meant for header-only fragments produced by splitting — so a whole short document (`b"Content"`, `"Test document content"`, a one-line Unicode text) produced zero chunks and was rejected as "no indexable content" (at `HEAD` it was worse: stored and reported as success with 0 chunks). Fix: when no fragment survives the floor but the document has non-whitespace text, index the whole document as one chunk; corpus chunking unchanged, whitespace-only files still rejected. Fixing it exposed one cross-test leak (`test_special_filename_characters` re-uploads bytes another test now stores → correct 409); a module fixture removes rows each test created. All assertions unchanged | Yes (upload endpoint) | Resolved; 20/20, now in the gate |
| `test_rag_fixes_simple` | 3 | `success == False`: needs a live LLM (same pattern fixed in `test_rag_tenant_isolation`) | Yes (RAG) | Covered by the fixed equivalent tests and real-Groq E2E |
| `test_rag_retrieval` (4), `medium_api` (3), `test_audit_proof` (2), `test_performance` (2), `test_integration` (1) | 12 | Stale auth (no token / token for non-existent user / no `type`), old `/health` payload (`healthy`, `version`), log-text assertions | Yes (endpoints) but assertions target the old contract | None: current contract covered by relevant suite; load behaviour covered by the concurrency probe (7/7) |
| `test_rag_accuracy` | 2 | Asserts against a hard-coded `mock_response` dict | No product code | None |
| `test_rag_fallback` | 1 | Treats any "couldn't find … knowledge base" wording as a corporate disclaimer | Yes (fallback text) | Cosmetic expectation |
| `test_stream_contract::test_small_talk_returns_tokens_not_422` | 1 → **0** | **Fixed in pass 3 (test isolation + app shutdown defect).** One run of the 38 preceding files with a state probe showed `app.state.rag` was a `MagicMock` when the test started. Source: `test_startup_readiness::TestLifespanFailClosed::test_successful_startup_then_health_ready_reports_200` runs the real `lifespan` on the shared `app` with `RAGService` patched; the lifespan set `app.state.rag` at startup and never cleared it at shutdown. `chat_stream` serves from `app.state.rag`, and a mock result's `documents_found` is never `== 0`, so the `rag_status` branch was skipped. Minimal reproducer: that one test followed by the target → `.F`. Fixes: the lifespan now resets `rag`, `vector_store`, `rag_ready` on shutdown (the app no longer reports ready or holds a stale service after shutdown); `test_startup_readiness` restores the `app.state` fields it writes. Reproducer → `..`; no sleep, skip or weakened assertion | Yes (SSE, startup) | Resolved |

### 3b. Secret scan (corrects the pass-1 claim)

Pass 1 stated "no Groq key was ever committed (checked every `.env` revision)";
that covered one file only. Pass 2 scanned **every blob reachable from every local
ref** (`git rev-list --all --objects` + `git cat-file --batch`; 68,055 blobs: 41,357
text blobs with provider, JWT, private-key and `*SECRET_KEY|API_KEY|PASSWORD|TOKEN*=`
assignment patterns, plus 26,698 binary/>8 MB blobs incl. tracked `.pyc` and
SQLite files with provider/JWT/private-key patterns) and all 104,230 working-tree
files (tracked and untracked). Values are never printed; findings carry kind,
path, length and a SHA-256 prefix.

| Result | Detail |
|---|---|
| Groq API keys | **0 in history.** One in the untracked local `.env` (never committed). The two other `GROQ_API_KEY=` hits are placeholders (`<…>`, `${…}`) in untracked files |
| AWS / GitHub / Slack / Google / private-key blocks | 0 in project history (third-party `venv/` and `node_modules/` excluded for these patterns, scanned for `gsk_`) |
| Signing keys | 10 distinct values in history → all refused in production by fingerprint (F-27) |
| Session JWTs | 2 in `cookies.txt` (history) — signed with a committed key, neutralised by refusing that key; 1 in untracked `_tmp_login.json` |
| Passwords | Sample-account passwords in docs (`QUICK_FIX_GUIDE.txt`, `QUICK_START.md`, …) — addressed by F-01 (never seeded in production; startup refuses accounts using them) |

Limitations: pattern-based (no gitleaks/trufflehog installed; installing new
tooling was out of scope) — unknown key formats can be missed; only objects
reachable from local refs (not dangling objects, reflog, other clones, forks or
server-side PR refs); assignment patterns skip values < 8 characters.

### 3c. Dependency security check

Tools: `npm audit` (registry advisories) for both frontends; OSV.dev API
(`/v1/querybatch`, `/v1/vulns`) for the backend, since `pip-audit` is not
installed. Backend findings were scoped to the transitive closure of
`requirements.txt` (148 packages; the dev venv holds 260).

| Package (installed) | Finding | Reachability | Decision |
|---|---|---|---|
| fastapi 0.104.1 / starlette 0.27.0 / python-multipart 0.0.6 | Unauthenticated parsing DoS/ReDoS (see F-24); Host/URL reconstruction, urlencoded limits (F-25, F-26) | Reachable without auth | **Fixed**: upgraded; F-25/F-26 mitigated in middleware for issues only fixed in Starlette ≥1.0.1/1.3.1 |
| pdfminer.six 20250506 (pinned by pdfplumber 0.11.7) | CVE-2025-64512 / GHSA-wf5f-4jwr-ppcp (HIGH): pickled CMap loaded from an attacker-influenced path → code execution (fixed 20251107); CVE-2025-70559 / GHSA-f83h-ghpp-7wcc (HIGH): incomplete fix, writable CMap path (fixed 20251230). Verified on OSV.dev/GHSA in pass 3 | Reachable from any PDF a tenant admin uploads (parsing runs in the API process as the service user) | **Fixed (pass 3)**: `pdfminer.six==20251230` + `pdfplumber==0.11.9` (which pins exactly that version). OSV: 0 advisories for both. 20251230 needs Python ≥ 3.10, charset-normalizer ≥ 2, cryptography ≥ 36 — satisfied |
| PyJWT 2.8.0 | 15 advisories (incl. CVE-2026-102268 critical, CVE-2026-32597, -102271, -48526 high), all in JWK/`PyJWKClient`, `crit` header or asymmetric/PEM-key handling; fixed 2.12–2.15 | Evidence: the code's only JWT calls are `jwt.encode`/`jwt.decode` in `src/backend/auth/authentication.py` with the server secret and `algorithms=[settings.algorithm]` (HS256); no `PyJWK`/`PyJWKClient` usage (grep); token claims are not trusted for identity (DB re-resolution) | Not reachable in current code; upgrade recommended (owner) |
| Pillow 10.4.0, PyPDF2 3.0.1, pypdfium2 4.30.1 | Pillow 10.4.0: 82 OSV entries incl. decoder heap overflows (12.3.0 still 59; **13.0.0: 0**). PyPDF2: GHSA-4vvm-4w3v-6mr8 infinite loop, fixed only in the renamed `pypdf`. pypdfium2 4.30.1: **yanked on PyPI** (text-extraction regression) — found by the clean install | No `src/` import of PIL; pdfplumber imports it, and the OCR fallback (pdf2image + poppler, installed in the Dockerfile) decodes rendered pages with it — reachable in a container. PyPDF2 was the third text fallback | **Fixed (pass 3)**: `Pillow==13.0.0` (requires Python ≥ 3.11 = both deploy targets; every consumer is uncapped: pdfplumber ≥ 9.1, pdf2image, pytesseract, sentence-transformers, torchvision); PyPDF2 removed, replaced by `pypdfium2==4.30.0` (already a pdfplumber dependency; 0 advisories; not yanked) as the last text fallback |
| transformers 4.36.0, torch 2.7.1, sentence-transformers 2.3.1 | Model-loading code execution / ReDoS | Only the fixed local model `all-MiniLM-L6-v2` is loaded; no user-supplied models | Not reachable |
| chromadb 0.4.22 | Server auth bypass, code injection | Embedded `PersistentClient`; no Chroma server exposed | Not reachable |
| requests 2.31.0, urllib3 2.4.0, certifi 2025.6.15, anyio 3.7.1, idna 3.10 | `.netrc` leak, redirect/decompression issues, a distrusted CA bundle entry | Outbound calls go only to the configured Groq HTTPS endpoint | Low; recommended routine upgrade |
| streamlit 1.28.1 (+ GitPython, tornado, pyarrow, protobuf) | Many | Imported only by the legacy `src/frontend/app.py`, launched only by the dev launchers (`start_server.py` option 1, `main_launcher.py`); not by `deploy/production` or the Dockerfile | **Removed from `requirements.txt` (pass 3)**; documented in `requirements-optional.txt` — it pins `pillow<11`, so it cannot share an environment with Pillow 13 |
| deep-translator (Google Translate) | 1 old advisory | Only `RAGService.text_generation`, whose sole caller is `scripts/test_golden.py`; the live chat path is offline | Not reachable; no user text is sent to Google |
| Frontend app: jspdf ≤4.2.0 (critical), dompurify, fflate | PDF/HTML injection, DoS | Export uses only `new jsPDF()`, text, `save()` — no `.html()`, `addImage`, `addJS`, AcroForm or new-window output | Not reachable; fix is a major version (4.x) — deferred |
| Frontend app: react-router 6.x | Open redirect, `deserializeErrors` | All navigation targets are constants; `BrowserRouter`, not a data router | Not reachable; patch-level upgrade recommended |
| Frontend: webpack-dev-server, babel, postcss, svgo, ws, body-parser … (≈60) | Many | Build/dev toolchain only; production serves static files from Nginx | Build-only |
| Landing: vite, esbuild | Dev-server issues | Dev server only | Build-only |

### 3e. PDF stack verification (pass 3)

Final PDF set: `pdfminer.six==20251230`, `pdfplumber==0.11.9`, `pypdfium2==4.30.0`,
`Pillow==13.0.0`, `pdf2image==1.17.0`, `pytesseract==0.3.13`; `PyPDF2` removed.
Extraction chain: pdfminer.six → pdfplumber → PDFium → OCR (only if poppler and
tesseract binaries exist; not installed natively, so OCR is **not claimed**).

| Check | Result |
|---|---|
| Clean install of the PDF set into a new venv (Python 3.11.6) | PASS: `pip check` clean; all three extractors return the text of a fixture PDF. This install surfaced the yanked pypdfium2 4.30.1 → pinned 4.30.0 |
| Dev venv after the change | PASS: `pip check` clean; pdfplumber, pdf2image, pytesseract, sentence-transformers, torchvision import with Pillow 13.0.0 |
| Full-manifest resolver dry run | Superseded by §3f: the unbounded `torch>=2.2` that made pip backtrack is now pinned, and the full production set resolves for Linux in seconds with uv |
| Regression tests (`tests/test_release_candidate.py`, 12) | PASS 12/12: valid single- and 120-line multi-page PDFs extract first and last lines; encrypted with user password → no content; encrypted with empty user password → extracted; malformed and image-only → no content; Pillow decoders and `Image.open` never invoked during text extraction (instrumented); empty / non-PDF / malformed / encrypted / >10 MB uploads → rejected with no Document row, no stored file and nothing sent to the vector store; valid PDF upload → indexed with tenant and department; PyPDF2 absent; version floors |
| Upload → index → authorized retrieval → grounded answer → citation (fresh env, real Groq) | PASS 28/28 (`scratchpad/e2e-r4/pdf_acceptance.txt`): finance user gets "USD 271,908" citing only the PDF; 5 bad PDFs rejected with reasons and leave no row/file; encrypted-PDF text not searchable; employee (wrong role) gets no figure, no PDF citation, PDF hidden from list, 403 on content/download; tenant-B admin (wrong tenant) gets no figure, no citation, 404 on content/download; owner admin downloads byte-identical PDF |
| Bangla | Bangla Markdown retrieval covered by the pass-2 E2E (§4). Bangla PDFs / OCR: **NOT VERIFIED** (not claimed) |
| Code-execution payloads | Not executed in the API process (by instruction); the fixed versions are verified by version and advisory data, not by exploit |

A first acceptance run was 27/28: the driver expected raw bytes from the download
endpoint, which returns a JSON envelope with base64 `data` (existing contract).
The driver was corrected and the run repeated on a newly created environment.

### 3f. Production dependency reproducibility (pass 4)

**Problem.** `requirements.txt` left `torch>=2.2` unbounded and pinned only
direct dependencies; the runbook installed it with `pip install -r
requirements.txt`, which re-resolves every transitive version at install time
and, on Linux, pulls PyPI's CUDA torch wheel plus NVIDIA libraries onto a host
with no GPU. The tested version set was therefore not reproducible on the host.

**torch constraint.** `torch==2.7.1`: the only version the application and test
suites ran on (dev venv: `2.7.1+cu118`). Compatibility: sentence-transformers
2.3.1 requires `torch>=1.11.0`; transformers 4.36.0 has no hard torch
requirement; torch 2.7.1 requires `sympy>=1.13.3` and
`typing-extensions>=4.10.0` — the tested set has 1.14.0 and 4.14.0. Under PEP 440,
`==2.7.1` is satisfied by the dev venv's `2.7.1+cu118` build, so the pin does not
replace it (`pip install --dry-run --no-index`: "Requirement already satisfied:
torch==2.7.1 … (2.7.1+cu118)"). No other package was upgraded.

**Tested version set.** Derived from the dev venv the release gate ran on, not
frozen from it: the production closure of `requirements.txt` was walked with
markers evaluated for Linux/CPython 3.11 (129 packages; Windows-only packages
excluded). The dev venv contains stale duplicate dist-info records for five
packages; comparing on-disk files with each RECORD shows the imported versions
are the manifest ones — httpx 0.25.2 (not 0.28.1), requests 2.31.0 (not 2.32.4),
urllib3 2.4.0 (not 2.5.0), certifi 2025.6.15 (not 2025.7.9), typing-extensions
4.14.0 (not 4.14.1). A plain freeze would have locked the wrong versions. (The
stale records are left in place: dev-environment hygiene, not in scope.)

**Lock.** `requirements-linux-py311.lock`, generated with uv 0.11.8:

```
uv pip compile requirements.txt -c <tested versions> --python-version 3.11 \
    --python-platform x86_64-manylinux_2_28 --torch-backend cpu \
    --generate-hashes --emit-index-annotation
```

| Check | Result |
|---|---|
| Resolution for Linux x86_64 / CPython 3.11 | PASS (exit 0): 133 packages, 2,108 sha256 hashes |
| Locked vs tested versions | PASS: all 129 tested packages locked at exactly their tested versions; 0 differences |
| torch | `2.7.1+cpu` from `https://download.pytorch.org/whl/cpu` (the only non-PyPI package); no `nvidia-*` / `triton` packages |
| In the lock but never exercised on the Windows test host | `uvloop 0.23.0` (uvicorn uses it automatically on Linux, so the host runs a different event loop than the tests), `hiredis 3.5.0` (redis extra; not installed in the dev venv), `psycopg2-binary 2.9.9` (PostgreSQL only, out of scope), `async-timeout 5.0.1` (only needed on Python < 3.11.3; harmless) |
| Artifact availability for the target | PASS: `pip download --no-deps --require-hashes -r requirements-linux-py311.lock` for `manylinux_2_28/2_17/2014 x86_64`, cp311 → all 133 artifacts fetched and hash-verified (exit 0, 352 MB, deleted afterwards): 131 wheels incl. `torch-2.7.1+cpu-cp311-cp311-manylinux_2_28_x86_64.whl`, 2 source-only (`langdetect 1.0.9`, `PyPika 0.48.9`, built by pip on the host). This proves the pins exist for the target; it is **not** an install |
| From-scratch install on Linux, `pip check`, import/startup, PDF regressions | **NOT VERIFIED.** No isolated Linux environment is available: WSL `Ubuntu-24.04` fails to start (its `ext4.vhdx` is missing, `Wsl/Service/CreateInstance/MountVhd/HCS/ERROR_PATH_NOT_FOUND`); Docker Desktop is installed but was not used (standing instruction: no Docker; it would also need an image download). No partial or Windows substitute was run |
| Release checks after the change | Not rerun: no installed version changed on the test host (torch already 2.7.1; dev venv `pip check` clean) and no test reads the manifests. Pass-3 results (§3a-2, §3e) stand |

Runbook §4 and §13 now install with
`pip install --require-hashes --no-deps --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-linux-py311.lock`
followed by `pip check`. To run on the host before the §10b gate:

```sh
python3.11 -m venv /tmp/lockcheck && /tmp/lockcheck/bin/pip install --require-hashes --no-deps \
    --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-linux-py311.lock
/tmp/lockcheck/bin/pip check
/tmp/lockcheck/bin/python -c "import torch, sentence_transformers, chromadb, pdfplumber, PIL; \
    from src.backend.api.endpoints import app; print(torch.__version__)"
LLM_PROVIDER=ollama GROQ_API_KEY= DEBUG=false /tmp/lockcheck/bin/pip install pytest==8.4.1 pytest-asyncio==1.3.0 anyio==3.7.1 \
    && /tmp/lockcheck/bin/python -m pytest tests/test_release_candidate.py -k "pdf or PDF or pillow" -o addopts=""
```

The `Dockerfile` still installs `requirements.txt` (not the native deployment
path; not changed here).

### 3d. Signing-key rotation and restore (disposable keys, isolated data)

| Check | Result |
|---|---|
| Production refuses a compromised key (fingerprint), a short key, weak defaults | PASS (subprocess tests; message never contains the key) |
| `rotate_secret_key.py`: key replaced (64 chars), duplicate lines removed, other settings kept, neither key printed | PASS (test) |
| Live service: session captured → rotate → restart → old access cookie 401, old refresh token 401, data reads 401; fresh login and refresh 200 | PASS 5/5 |
| Refresh tokens revoked by rotation | 15 → 0 active |
| `restore.sh`: active refresh tokens in restored DB revoked; env file not restored | 5 → 0; env file byte-identical |

## 4. Core acceptance matrix (final code, fresh isolated environment, real Groq)

Pass 2 re-ran the full scripted journey on a **new** isolated environment
(fresh migration, accounts from `manage_user.py`) on the upgraded HTTP stack:
seed 2/2, upload validation 12/12, chat (EN/BN/mixed, phrase + pronoun
follow-ups, citations, reload) 16/16, wrong-role / cross-tenant /
unauthenticated / CSRF / forged-token denial 32/32, delete lifecycle 6/6, public
demo 10/10, SSE incl. interruption 4/4, auth 7/7 — **89/89**. Browser checks below
are from pass 1; the frontend is unchanged since.

| Area | Result | Evidence |
|---|---|---|
| Landing → `/app` → login | PASS | Browser; nested `/app/chat` refresh served; logged-out deep links redirect to login |
| Login / refresh / logout | PASS | Rotation; replayed old refresh → 401; logout clears cookies, APIs 401; login limiter 429 after 4 failures; only `csrf_token` JS-readable, no token in storage |
| Admin upload via dashboard UI | PASS | 3 docs + 2 finance docs (incl. PDF); single dialog; truthful toasts |
| Upload validation | PASS | empty, fake PDF, `.exe`, >10 MB, invalid department, `../../` filename, duplicate (409) — each with a clear reason; nothing written outside the document dir |
| Authorized retrieval + cited answer | PASS | HELIOTROPE fact with only its source cited; PDF fact; finance-only fact for finance role |
| English / Bangla / mixed | PASS | Bangla answer in Bangla script with correct figure and citation; Unicode preserved on reload |
| Follow-up / reload | PASS | phrase and pronoun follow-ups; 6 messages in order on reload with citations |
| Insufficient evidence | PASS | honest answer, no citations |
| Wrong role | PASS | employee: no finance figure, no finance citation, no fabricated figure, list hides finance docs, content/download 403 |
| Cross-tenant | PASS | tenant B: no tenant-A retrieval/citation; content, download, conversations, export, delete → 404; user list scoped |
| Unauthenticated / CSRF / forged token | PASS | 401s; missing or wrong CSRF 403; cross-site GET stream 403; `alg=none` 401 |
| Prompt-injection document | PASS (mitigated) | no instruction disclosure, no restricted data, no finance citation |
| Document delete lifecycle | PASS | not retrievable/cited after delete; 404; no stale chunks; re-upload OK |
| SSE success / interruption | PASS | `text/event-stream`; first event 0.01 s; ends `complete` → `[DONE]`; disconnect leaves no partial history; session reusable |
| Provider failures | PASS (mocked) | 429/timeout/malformed → `success=false`, not persisted; real-provider failure not induced |
| Public demo | PASS | tenant_demo; upload/delete/user-create/clear 403; demo-corpus answers; per-visitor conversation isolation; fails closed without visitor cookie |
| Database migrations | PASS | §3 |
| Backup / restore | PASS (Windows shell, disposable data) | §3; systemd stop/start path NOT VERIFIED |
| Frontend production builds | PASS | §3 |
| Native deployment configuration | PASS (review) / NOT VERIFIED (runtime) | §6 |
| Host / provider smoke checks | NOT VERIFIED | no Linux host available |
| Mobile (390 px) + Bangla rendering | PASS | wraps correctly; header overlap fixed |

Streaming note: the backend generates the full answer, then streams it in word
chunks (Groq is called non-streaming). Users see status/heartbeat events at once
and answer text after generation (~1.5–4 s locally).

## 5. Changed files

Backend: `src/backend/api/{admin,auth,chat_stream,document_upload}.py`,
`src/backend/database/database.py`, `src/backend/middleware/security.py` (pass 2),
`src/backend/services/{llm_provider,rag_service,vector_store}.py`,
`src/backend/utils/document_processor.py`, `src/config/settings.py`, `requirements.txt` (pass 2: 3 pins).
New: `scripts/manage_user.py`, `scripts/rotate_secret_key.py` (pass 2),
`deploy/production/{backup,restore,verify_host}.sh` (verify_host pass 2),
`tests/test_release_candidate.py`, this report.
Deploy: `deploy/production/{start.sh,finsolve.service,nginx.conf,.env.production.example}`,
`.env.example`, `docs/NATIVE_DEPLOYMENT_RUNBOOK.md` (pass 2: §6a, §10b, §12).
Pass 3: `src/backend/utils/document_processor.py` (PDFium fallback replaces PyPDF2; short-document chunking), `src/backend/api/endpoints.py` (lifespan shutdown reset), `requirements.txt`, `requirements-optional.txt`, `deploy/production/verify_host.sh` and runbook §10b (credential input), pass 4: `requirements.txt` (torch pin), new `requirements-linux-py311.lock`, runbook §4/§13, `tests/{test_release_candidate,test_document_parsing,test_startup_readiness}.py`.
Frontend: `App.js`, `components/{AdminDashboard,DarkChatInterface,PromptComposer}.js`,
`components/ui/MessageBubble.js`.
Tests adjusted: `tests/conftest.py`, `tests/test_{api_endpoints,auth_security,document_upload_auth,sse_auth_cors,stream_contract,wave7_provider_demo}.py`;
pass 2: `tests/test_{enterprise_rag,rag_tenant_isolation,security_hardening_v2,chat_sessions,streaming,security,tenant_isolation}.py`.

## 6. Remaining blockers and caveats

**Blocking for go-live (operator, on the target host):**

0. **Linux install of the production lock — NOT VERIFIED (§3f).** On the host (or
   an equivalent Linux x86_64 / Python 3.11 staging machine), install
   `requirements-linux-py311.lock` into a fresh venv, run `pip check`, the import
   check and the PDF regressions listed in §3f, then proceed with the runbook.
1. **Host verification gate — NOT VERIFIED.** No Linux host was available (the
   local WSL Ubuntu is broken; Docker and new downloads were out of scope). Run
   `deploy/production/verify_host.sh` (runbook §10b); every line must be PASS.
   It covers `nginx -t`, `systemd-analyze verify` + running service, HTTPS
   login/cookies/CSRF/refresh, `/` and `/app` routing with nested reload, SSE
   timing through Nginx, 11 MB/33 MB upload boundaries, loopback-only API,
   persistence across restart, and refusal of invalid production config. The
   script's HTTP checks were dry-run against the local stack (sections 3–5
   passing where Nginx is not involved); its host-only checks have never run.
2. **Fresh signing key** with `scripts/rotate_secret_key.py` (runbook §6a). The
   10 committed keys are refused by production startup.
3. **First admin account** via `scripts/manage_user.py create` (runbook §7a).
4. **Production Groq key/model/quota** confirmed on the host (gate §5 exercises a real answer).

**Application-level items closed in pass 3:**

5. ~~PDF parser code execution risk~~ — fixed with PDF support preserved (§3c, §3e).
6. ~~Order-dependent SSE test~~ — root-caused and fixed (§3a-2).

The host checker no longer takes the admin password on the command line or from
the environment: it prompts without echo, or reads an owner-only (mode 600) file
named by `FINSOLVE_ADMIN_PASSWORD_FILE`, and refuses `FINSOLVE_ADMIN_PASSWORD`
(runbook §10b). Verified locally only for the refusal path and shell syntax; the
prompt and file paths run on the host with the rest of the gate (NOT VERIFIED).

**Not blocking the deployment, required before any public repository push:**
history rewrite and credential review per `docs/security/publication-remediation.md`
(signing keys, `cookies.txt` session JWTs, sample passwords in docs remain in history).

**Non-blocking caveats:**

- C-1 Prompt-injection resistance is mitigated, not guaranteed. Authorization is
  enforced before retrieval, so injected text cannot reach data the user can't read.
- C-2 Synchronous SQLite writes and bcrypt in async handlers briefly stall the event
  loop (one `/health` sample 2.0 s under 7 concurrent requests). Acceptable at
  the intended single-worker scale; revisit before higher load.
- C-3 Two tabs refreshing the same refresh token at once: the second gets 401 and
  must sign in again (strict rotation, no grace window).
- C-4 Refusal answers may still cite near-top documents the user *can* access.
- C-5 Legacy suites outside the relevant set (`tests/unit/*`, `medium_*`,
  `test_audit_proof`, …) still fail on API drift; see §3a for the full-tree numbers.
- C-6 Deferred dependency upgrades, not reachable in current code (§3c): PyJWT,
  react-router patch, jspdf 4.x.
- C-10 The Linux host runs `uvloop` (installed via chromadb → `uvicorn[standard]`)
  while the tests ran on the default asyncio loop; covered only by the host gate.
- C-7 PostgreSQL deletion worker/reconciler tests NOT VERIFIED (out of launch scope).
- C-8 ARM64 — NOT VERIFIED (runbook §16).
- C-9 Streaming is post-generation chunking, not live token streaming.

## 7. Deployment next steps

**Next concrete action:** on an authorized Linux staging (or production) host,
follow `docs/NATIVE_DEPLOYMENT_RUNBOOK.md` §2 → §9a (user/dirs, code + venv with
`requirements-linux-py311.lock` (Python 3.11 x86_64; required by Pillow 13), both builds, env file, **§6a key rotation**,
`start.sh`, §7a first admin, systemd, Nginx + TLS, firewall), then run the
**§10b gate** and attach its output to this report. Only a fully passing gate
moves Host verification to PASS. Owner-supplied values: domain, TLS
certificates, Groq production key and model, tenant id, first admin email.

## 8. Release-commit validation (2026-11-18)

Run from a clean, shallow, LF checkout of the commit that contains this
section (no `.env`, no `venv/`, no `node_modules/` before the run).

| Check | Result |
|---|---|
| Release gate (41 files, `-o addopts=""`, `LLM_PROVIDER=ollama`, no exported `SECRET_KEY`) | 781 collected: 777 passed, 0 failed, 4 skipped |
| Skipped | 3 × `test_enterprise_rag` deletion-worker tests (PostgreSQL not reachable; out of launch scope) and `test_release_candidate::test_host_ocr_extracts_visible_text_from_scanned_pdf` (Poppler and Tesseract not installed on the host) |
| Landing build (`npm ci && npm run build`) | OK (Vite), byte-identical asset hashes to the development build |
| App build (`cp .env.production.example .env.production`, demo-flag guard, `npm ci && npm run build`) | Compiled successfully; demo persona panel present; no Groq key in either bundle |
| Frontend Jest | 16 suites, 88 tests, all passed |
| Browser run on a same-origin edge (isolated data, real Groq) | Demo Admin and Employee; English and Bangla answers with citations; full SSE stream; history after reload; RBAC; read-only demo mutations; two-visitor isolation; Bangla print-PDF |

Changes found by this pass and fixed in the commit:

- The root `conftest.py` now supplies a random per-run `SECRET_KEY` when none is
  exported. In a clean checkout the two `test_auth_security` secret-key tests
  otherwise saw the fail-closed sentinel `MUST_BE_SET_VIA_ENV` (a test-environment
  dependency on a developer `.env`, not a product defect).
- `deploy/production/.env.production.example` could not be sourced by `sh`
  (`start.sh`, `backup.sh`, `restore.sh`, `verify_host.sh` and the §7a recipe use
  `set -a; . file`): `APP_NAME` had unquoted spaces and `ALLOWED_ORIGINS` lost
  its JSON quotes, so settings validation failed with
  `error parsing value for field "allowed_origins"`. Both values are now quoted.
- `deploy/production/verify_host.sh` SSE gate now checks the full stream
  (start, tokens, exactly one `complete`, no `error`, `[DONE]`), not only timing.
- `.gitattributes` no longer routes `*.png` through Git LFS (the four logos were
  130-byte pointers, which `git archive` and a plain clone would have shipped);
  `.gitignore` un-ignores the three `.env.production.example` templates.

Known, not fixed here:

- `scripts/check_publication_readiness.py` reports 8 violations on this tree:
  6 are false positives where the "secret" is a code expression or a
  documentation placeholder (`getpass.getpass(...)`, `settings.groq_api_key`,
  `secrets.token_urlsafe(...)`, `<cryptographically random value>`), and 2 are
  the `.env.production.example` templates, which its path rule treats as local
  environment files. Reviewing each one found no secret value. The checker
  needs a deliberate allow-list decision before the repository is published.
- API timestamps are naive UTC (no `Z`), so non-UTC browsers show message times
  shifted by their offset (visible in history and the PDF export).
- A two-part Bangla question once omitted its second item (retrieval correct;
  an identical re-ask answered both).
- Three sample private-account passwords (they verify against the committed
  hashes in `src/config/roles.py`; production startup refuses those accounts)
  still appear in 11 tracked files: `ADMIN_DASHBOARD_FINAL_STEPS.md`,
  `ADMIN_LOGIN_QUICK_START.md`, `ADMIN_LOGIN_VISUAL_GUIDE.md`,
  `AUTH_LOGIN_FIX_COMMITS.md`, `QUICK_START_AFTER_FIX.md`,
  `RAG_PATH_FIX_SUMMARY.md`, `RUNBOOK_AUTH_REFRESH.md`, `bugs_found.md`,
  `scripts/test_conversation_auth.py`, `test_admin_rbac.py`, `test_auth.py`.
  Scrub them, and rewrite history, before any push.
