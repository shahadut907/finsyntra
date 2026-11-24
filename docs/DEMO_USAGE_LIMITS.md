# Public demo usage and abuse protection

All limits apply to **public-demo identities** (Try Demo personas) and are enforced on the backend. Counters live in the database (Neon PostgreSQL in production) and roll over at 00:00 UTC.

| Limit | Default | Setting |
|---|---|---|
| Messages per visitor per day | 10 | `DEMO_VISITOR_DAILY_LIMIT` |
| Messages per client IP per day | 20 | `DEMO_IP_DAILY_LIMIT` |
| Messages per client IP per minute | 3 | `PUBLIC_DEMO_CHAT_RATE_LIMIT_PER_MINUTE` |
| Messages per day, all visitors | 60 | `DEMO_GLOBAL_DAILY_LIMIT` |
| Groq tokens per day (actual `usage.total_tokens`) | 180,000 (of which 40,000 reserved for the Super Admin) | `DEMO_DAILY_TOKEN_BUDGET`, `DEMO_SUPER_ADMIN_TOKEN_RESERVE` |
| Active chats per visitor | 1 | fixed |
| Concurrent AI requests, global | 2 | `DEMO_GLOBAL_CONCURRENCY` |

Calibrated to the real Groq limits for `openai/gpt-oss-20b` (verified 2026-11-24 from the live API headers and Groq docs: 1,000 requests/day, 8,000 tokens/minute, 200,000 tokens/day): the budget is 90% of the daily quota and `DEMO_DAILY_TOKEN_BUDGET_CEILING` (200,000) caps any runtime change. If the model or Groq plan changes, re-verify.

## How it holds

- A message is charged to visitor, IP and global counters in **one transaction** using conditional upserts, so concurrent requests cannot exceed a limit and a refusal charges nothing. A generation that fails (model busy/unavailable) is refunded.
- The visitor is the server-issued, httpOnly `vsid` cookie (stored only as an HMAC). Refreshing or reopening the page keeps it. Clearing cookies or using incognito mints a new visitor, but the **IP and global limits still apply**, so this does not reset the allowance.
- The client IP is read from `X-Forwarded-For` counting `TRUSTED_PROXY_HOPS` entries from the right (entries to the left are client-supplied and ignored), then HMAC-hashed. Behind Vercel -> Cloudflare -> Render the chain is `client, vercel-egress, cloudflare, internal`, hence `TRUSTED_PROXY_HOPS=2` on Render, plus one when the edge secret is presented.
- Direct API calls need the same authentication, CSRF token and `vsid` cookie as the UI.
- `GET /api/demo/usage` feeds the usage indicator; refusals reach the UI as a friendly message.

Direct-to-Render spoofing is closed. Vercel Routing Middleware (`middleware.js`) adds a shared secret header (`X-Finsyntra-Edge`, from the `EDGE_PROXY_SECRET` environment variable on both Vercel and Render, never in the repository) to every proxied `/api`, `/auth` and `/health` request. Only a request with the correct secret may use the extra Vercel hop; any other request is attributed to the address Render's own proxies saw (`TRUSTED_PROXY_HOPS=2`: Cloudflare and Render's internal proxy), which a client cannot forge. Leading `X-Forwarded-For` entries are never trusted.

## Super Admin

A Super Admin is an **authenticated private admin account** whose email is listed in `SUPER_ADMIN_EMAILS` (JSON list). The public-demo "Admin" persona can never qualify, and no IP allowlist or bypass header exists. Authorization is checked on the backend on every request.

The Super Admin account is created once through `POST /auth/bootstrap-super-admin`, which is 404 unless `SUPER_ADMIN_BOOTSTRAP_TOKEN` is set, needs that token in `X-Bootstrap-Token`, an email already in `SUPER_ADMIN_EMAILS`, and a password of 12-128 characters, and refuses if the account exists. Remove the token afterwards. Sign in with the normal login form; the Admin Dashboard then shows **Usage & Controls** and **AI Chat** (the existing chat page) for that account only.

A Super Admin is exempt from the visitor, IP and global message limits and from the pause switch, so it keeps working when the public quota is exhausted. It is **not** exempt from the per-minute rate limit, the concurrency slots, or the token budget: its generations draw on a reserved pool (`DEMO_SUPER_ADMIN_TOKEN_RESERVE`, default 30,000 tokens/day) that public visitors cannot spend, and Groq's own quota still applies.

Endpoints (all Super Admin only; mutations need the usual CSRF header):

| Request | Purpose |
|---|---|
| `GET /api/admin/demo-usage` | Usage today, remaining quota, token pools, active requests, effective limits, 7-day history. Aggregates only. |
| `PUT /api/admin/demo-usage/limits` | Change visitor/IP/global limits, token budget, admin reserve. Values are range-checked; `null` restores the default. |
| `PUT /api/admin/demo-usage/access` | `{"enabled": false, "pause_minutes": 30, "message": "..."}` pauses public chat (auto-resumes); `{"enabled": true}` resumes. |
| `POST /api/admin/demo-usage/reset` | `{"scope": "visitors" \| "global_messages" \| "all_messages"}` resets today's message counters. Token usage is never reset, because it mirrors the real upstream quota. |

Runtime changes persist in the database (`demo_runtime_settings`) and are logged as `DEMO_ADMIN_ACTION`.
