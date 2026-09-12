# AlmaPortal API

Python 3.12 FastAPI service for the Lead Management context.

## Run locally

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/alma-api
```

Runtime configuration is supplied through environment variables:

- `DATABASE_URL`
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET`
- `SUPABASE_JWT_ISSUER`, `SUPABASE_JWKS_URL`, `JWT_ALGORITHMS`
- `SUPABASE_JWT_SECRET` only for local Supabase CLI HS256 tokens
- `RESEND_API_KEY`, `RESEND_BASE_URL`, `RESEND_FROM_EMAIL`
- `ATTORNEY_NOTIFICATION_EMAIL`, `PUBLIC_API_URL`
- `TICKET_SIGNING_SECRET`, at least 32 bytes
- `CORS_ORIGINS`, comma-separated explicit origins
- `TRUSTED_PROXY_CIDRS`, comma-separated documented proxy networks
- `TRUSTED_CLIENT_IP_HEADER`, optional and limited to `CF-Connecting-IP`
- `PUBLIC_RATE_LIMIT_MAX_KEYS`, defaults to `10000`
- `COMMIT_SHA` or Render's `RENDER_GIT_COMMIT`

`WEB_CONCURRENCY` must be `1` because the pre-parse public submission limiter
is process-local.

Production JWT verification accepts asymmetric algorithms only. A local
Supabase CLI instance can use `JWT_ALGORITHMS=HS256` with
`SUPABASE_JWT_SECRET` set to its JWT secret. This mode requires a secret of at
least 32 bytes, a loopback `SUPABASE_URL`, and a non-production environment.
It never calls JWKS, but applies the same issuer, audience, expiry, role,
non-anonymous, email, and signed Google provider checks as asymmetric tokens.

In production, `SUPABASE_URL` must be a credential-free HTTPS origin. The
issuer and JWKS URL must be its exact Auth children, and Resend must use
`https://api.resend.com`. Remote PostgreSQL URLs must set `sslmode` to
`require`, `verify-ca`, or `verify-full`.

By default, rate limiting uses the socket peer and ignores
`X-Forwarded-For`. Set `TRUSTED_CLIENT_IP_HEADER=CF-Connecting-IP` only with
the documented proxy networks in `TRUSTED_PROXY_CIDRS`. Malformed or repeated
trusted client-IP headers are rejected.

## Database contract

The API maps canonical read models for `leads`, `email_deliveries`, and
`email_delivery_attempts`. Every write calls a Supabase migration function, so
the runtime database role needs only `SELECT` and `EXECUTE`. Supabase owns the
80-credit new-lead budget, 20-credit retry budget, and demo capacity. The API
never runs migrations or `create_all`.

## Checks

```bash
.venv/bin/pytest
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
```

Local Supabase verification is opt-in:

```bash
ALMA_RUN_SUPABASE_INTEGRATION=1 \
TEST_DATABASE_URL=postgresql://... \
.venv/bin/pytest -m integration
```

The Resend smoke command requires an explicitly supplied, unrelated,
authorized recipient:

```bash
.venv/bin/email-smoke \
  --to unrelated-recipient@example.net \
  --confirm-unrelated-recipient
```
