# ADR-0003: Tenant isolation (app checks + Postgres RLS) and session authentication

- **Status:** Accepted
- **Date:** 2026-10-16

## Context
The platform stores highly sensitive personal data for many users (§4.1, §15). A single missed
`WHERE owner = ?` must not leak data. The browser must never receive backend credentials.

## Decision
### Ownership
Every user-owned table has `owner_user_id uuid not null references users(id)`. Case-scoped tables
also have `case_id`, with a composite FK `(case_id, owner_user_id) → candidate_cases(id, owner_user_id)`
so a child row can never point at another user's case.

### Two independent walls
1. **Application layer:** use cases require an `Actor` and load resources with
   `owner_user_id = actor.user_id`. A miss returns `NotFound` (HTTP 404, never 403).
2. **Postgres RLS:** owned tables have `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`
   with policy `owner_user_id = current_setting('app.user_id', true)::uuid`. The API connects
   as role `nexscout_app` (non-owner, no BYPASSRLS). Each request transaction runs
   `SELECT set_config('app.user_id', :uid, true)` (transaction-local, so it is safe with pooling).
   Migrations run as the owner role `nexscout_owner`.
   Workers set `app.user_id` to the run's owner before touching owned rows.
   A narrowly scoped `nexscout_system` role (BYPASSRLS) is used only for queue claiming and lease
   reaping, which read only queue metadata.

### Authentication
- Local accounts: email + argon2id hash (argon2-cffi defaults, upgraded via `check_needs_rehash`).
- Opaque 256-bit random session token in an httpOnly cookie. **Only its SHA-256 hash is stored.**
  Sliding idle expiry (default 12 h) plus absolute expiry (default 14 d). Revoked on logout and
  password change.
- CSRF: double-submit token (cookie `nexscout_csrf`, readable by JS, echoed in `X-CSRF-Token`)
  required on all mutating methods. Also SameSite=Lax.
- Next.js rewrites `/api/*` to FastAPI, so the browser stays same-origin and CORS stays closed.
- Login rate limiting (per IP + per account) and constant-time handling of unknown accounts.

## Alternatives considered
- JWT in localStorage: XSS-exposed and hard to revoke. Rejected.
- Auth-as-a-service (Auth0, Clerk): unsuitable for local and desktop deployment. Can be added as an
  OIDC adapter later.

## Consequences
- Tests must cover both walls: an API IDOR test and a raw-SQL RLS test using the app role.
- Admin and diagnostic tooling needs an explicit, audited path. It never reuses `nexscout_app`.
