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
- `SENDGRID_API_KEY`, `SENDGRID_BASE_URL`, `SENDGRID_FROM_EMAIL`
- `ATTORNEY_NOTIFICATION_EMAIL`, `PUBLIC_API_URL`
- `TICKET_SIGNING_SECRET`, at least 32 bytes
- `CORS_ORIGINS`, comma-separated explicit origins
- `TRUSTED_PROXY_CIDRS`, comma-separated documented proxy networks
- `COMMIT_SHA` or Render's `RENDER_GIT_COMMIT`

`WEB_CONCURRENCY` must be `1` because the pre-parse public submission limiter
is process-local.

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

The SendGrid smoke command requires an explicitly supplied, unrelated,
authorized recipient:

```bash
.venv/bin/email-smoke \
  --to unrelated-recipient@example.net \
  --confirm-unrelated-recipient
```
