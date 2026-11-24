# FinSyntra active security route inventory (Wave 5)

Generated from the registered FastAPI application on 2026-08-29. `Shared auth`
means `src.backend.api.auth_deps`; SSE calls it inside the handler because both
GET and POST share the same request adapter. Cookie-authenticated mutations are
also subject to origin and double-submit CSRF validation in middleware.

| Route | Method | Auth Required | Role Requirement | Tenant Scope | Mutation? |
|---|---|---|---|---|---|
| `/` | GET | No | PUBLIC | None | No |
| `/health` | GET | No | PUBLIC shallow health | None | No |
| `/health/deep` | GET | Yes | Admin/C-level | Current tenant diagnostics | No |
| `/api/chat` | POST | Yes, shared auth | Authenticated | Server-resolved tenant -> RAG/session | Yes |
| `/api/chat/conversations/{session_id}` | GET | Yes, shared auth | Authenticated | Tenant + user-owned session | No |
| `/api/chat/stream` | GET, POST | Yes, shared auth inside handler | Authenticated | Server-resolved tenant -> RAG/session | POST/stream |
| `/api/chat/stream/health` | GET | No | PUBLIC minimal stream health | None | No |
| `/api/conversations` | GET | Yes, shared auth alias | Authenticated | Tenant + user | No |
| `/api/conversations` | POST | Yes, shared auth alias | Authenticated | Tenant + user | Yes |
| `/api/conversations/{conversation_id}` | GET | Yes, shared auth alias | Authenticated | Tenant + user-owned session | No |
| `/api/conversations/{conversation_id}/export` | GET | Yes, shared auth alias | Authenticated | Tenant + user-owned session | No |
| `/api/conversations/export` | GET | No | PUBLIC validation-only 422 | No data lookup | No |
| `/api/knowledge/stats` | GET | Yes, shared auth | Authenticated | Current tenant | No |
| `/api/documents/upload` | POST | Yes, shared auth | Authenticated + department RBAC | Current tenant | Yes |
| `/api/documents/refresh` | POST | Yes, shared auth | Admin/C-level | Current tenant cache/stats | Yes |
| `/api/documents/status` | GET | Yes, shared auth | Authenticated | Current tenant | No |
| `/api/documents/clear` | DELETE | Yes, shared auth | Admin/C-level | Current tenant vectors only | Yes |
| `/api/documents/list` | GET | Yes, shared auth | Authenticated | Current tenant metadata only | No |
| `/api/admin/overview` | GET | Yes, shared auth | Admin/C-level | Current tenant | No |
| `/api/admin/recent-activity` | GET | Yes, shared auth | Admin/C-level | Session-joined current tenant | No |
| `/api/admin/health` | GET | Yes, shared auth | Admin/C-level | Current admin | No |
| `/api/admin/users` | GET | Yes, shared auth | Admin/C-level | Current tenant | No |
| `/api/admin/users` | POST | Yes, shared auth | Admin/C-level | Creates in current tenant | Yes |
| `/api/admin/users/{user_id}` | PUT, DELETE | Yes, shared auth | Admin/C-level | Target must be in current tenant | Yes |
| `/api/admin/users/{user_id}/toggle-status` | PATCH | Yes, shared auth | Admin/C-level | Target must be in current tenant | Yes |
| `/api/admin/documents` | GET | Yes, shared auth | Admin/C-level | Current tenant | No |
| `/api/admin/documents/{doc_id}/content` | GET | Yes, shared auth | Admin/C-level | Current tenant-owned record + exact path | No |
| `/api/admin/documents/{doc_id}/download` | GET | Yes, shared auth | Admin/C-level | Current tenant-owned record + exact path | No |
| `/api/admin/documents/{doc_id}` | DELETE | Yes, shared auth | Admin/C-level | Current tenant-owned record + exact path | Yes |
| `/api/admin/analytics` | GET | Yes, shared auth | Admin/C-level | Current admin/runtime metrics | No |
| `/api/admin/organizations` | GET | Yes, shared auth | Admin/C-level | Current tenant only | No |
| `/api/admin/audit-logs` | GET | Yes, shared auth | Admin/C-level | Empty until tenant-owned audit model exists | No |
| `/api/admin/upload-department-data` | POST | Yes, shared auth | Admin/C-level | Delegates to tenant-owned upload pipeline | Yes |
| `/api/admin/validate-session` | GET | Yes, shared auth | Admin/C-level | Current admin | No |
| `/auth/login` | POST | No | PUBLIC credential exchange | Server user record | Yes |
| `/auth/me` | GET | Yes, shared auth | Authenticated | Server user record | No |
| `/auth/refresh` | POST | Refresh cookie + CSRF | Active user | Server user + refresh JTI | Yes |
| `/auth/logout` | POST | Refresh cookie when present + CSRF | Credential holder | Current refresh JTI | Yes |

FastAPI's `/docs`, `/redoc`, and `/openapi.json` remain framework documentation
routes in development. Production documentation exposure should be decided in
deployment configuration, not by weakening application authorization.
