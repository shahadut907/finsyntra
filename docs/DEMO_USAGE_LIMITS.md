# Public demo usage and abuse protection

All limits apply to **public-demo identities** (Try Demo personas) and are enforced on the backend. Counters live in the database (Neon PostgreSQL in production) and roll over at 00:00 UTC.

| Limit | Default | Setting |
|---|---|---|
| Messages per visitor per day | 10 | `DEMO_VISITOR_DAILY_LIMIT` |
| Messages per client IP per day | 20 | `DEMO_IP_DAILY_LIMIT` |
| Messages per client IP per minute | 3 | `PUBLIC_DEMO_CHAT_RATE_LIMIT_PER_MINUTE` |
| Messages per day, all visitors | 60 | `DEMO_GLOBAL_DAILY_LIMIT` |
| Groq tokens per day (actual `usage.total_tokens`) | 150,000 | `DEMO_DAILY_TOKEN_BUDGET` |
| Active chats per visitor | 1 | fixed |
| Concurrent AI requests, global | 2 | `DEMO_GLOBAL_CONCURRENCY` |

Check `DEMO_DAILY_TOKEN_BUDGET` against the real tokens-per-day quota of the configured Groq model; `DEMO_DAILY_TOKEN_BUDGET_CEILING` caps any runtime change.

## How it holds

- A message is charged to visitor, IP and global counters in **one transaction** using conditional upserts, so concurrent requests cannot exceed a limit and a refusal charges nothing. A generation that fails (model busy/unavailable) is refunded.
- The visitor is the server-issued, httpOnly `vsid` cookie (stored only as an HMAC). Refreshing or reopening the page keeps it. Clearing cookies or using incognito mints a new visitor, but the **IP and global limits still apply**, so this does not reset the allowance.
- The client IP is read from `X-Forwarded-For` counting `TRUSTED_PROXY_HOPS` entries from the right (entries to the left are client-supplied and ignored), then HMAC-hashed.
- Direct API calls need the same authentication, CSRF token and `vsid` cookie as the UI.
- `GET /api/demo/usage` feeds the usage indicator; refusals reach the UI as a friendly message.

Known limit: the API origin on Render is public, and a client talking to it directly (bypassing Vercel) can influence the left-most forwarded entries. The global message and token budgets bound that case.

## Super Admin

A Super Admin is an **authenticated private admin account** whose email is listed in `SUPER_ADMIN_EMAILS` (JSON list). The public-demo "Admin" persona can never qualify, and no IP allowlist or bypass header exists. Authorization is checked on the backend on every request.

A Super Admin is exempt from the visitor, IP and global message limits and from the pause switch, so it keeps working when the public quota is exhausted. It is **not** exempt from the per-minute rate limit, the concurrency slots, or the token budget: its generations draw on a reserved pool (`DEMO_SUPER_ADMIN_TOKEN_RESERVE`, default 30,000 tokens/day) that public visitors cannot spend, and Groq's own quota still applies.

Endpoints (all Super Admin only; mutations need the usual CSRF header):

| Request | Purpose |
|---|---|
| `GET /api/admin/demo-usage` | Usage today, remaining quota, token pools, active requests, effective limits, 7-day history. Aggregates only. |
| `PUT /api/admin/demo-usage/limits` | Change visitor/IP/global limits, token budget, admin reserve. Values are range-checked; `null` restores the default. |
| `PUT /api/admin/demo-usage/access` | `{"enabled": false, "pause_minutes": 30, "message": "..."}` pauses public chat (auto-resumes); `{"enabled": true}` resumes. |
| `POST /api/admin/demo-usage/reset` | `{"scope": "visitors" \| "global_messages" \| "all_messages"}` resets today's message counters. Token usage is never reset, because it mirrors the real upstream quota. |

Runtime changes persist in the database (`demo_runtime_settings`) and are logged as `DEMO_ADMIN_ACTION`.
