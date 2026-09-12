# Run AlmaPortal locally

This is the local path for the take-home. Hosted Vercel, Render, and production
Supabase are optional and are not required to walk the product.

Use `http://127.0.0.1` everywhere, not `localhost`. Google OAuth, CORS, and
CSRF are bound to that origin.

Synthetic data only. Do not submit real names, resumes, or inboxes you do not
control.

## Prerequisites

- Git, Make, Docker Desktop (or another Docker runtime)
- Node.js 22 LTS with Corepack, which selects pnpm
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started)
- A Google Cloud project for reviewer sign-in
- Optional: a Resend account if you want mail in a real inbox

```bash
corepack enable
pnpm --version
uv --version
brew install supabase/tap/supabase
supabase --version
```

## Install and env files

From the repository root:

```bash
make setup
cp .env.example .env
cp apps/web/.env.example apps/web/.env.local
```

Generate two secrets of at least 32 characters and put them in both env files
where those names already exist:

```bash
openssl rand -base64 32   # CSRF_SECRET
openssl rand -base64 32   # TICKET_SIGNING_SECRET
```

Leave `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`. Browser code may only hold
the public API origin, the Supabase URL, and the anon key. Database passwords,
the service-role key, Resend, and the ticket secret stay out of `NEXT_PUBLIC_*`.

## Local Supabase

```bash
make supabase-start
make supabase-reset
make db-runtime-credentials
supabase status
```

`make db-runtime-credentials` creates the least-privilege `alma_api` role and
writes ignored, mode-0600 values to `.env.runtime`. `make supabase-stop` drops
local data. To recycle Auth after changing Google credentials, use
`supabase stop --workdir infra` then `make supabase-start`.

Copy the local anon key from `supabase status` into
`apps/web/.env.local` as `NEXT_PUBLIC_SUPABASE_ANON_KEY`. The runtime file
already receives the matching server keys.

## Google OAuth

Reviewer login uses Google through local Supabase Auth.

1. In Google Cloud Console, create an External OAuth client of type Web
   application.
2. Authorized JavaScript origin: `http://127.0.0.1:3000`
3. Authorized redirect URI: `http://127.0.0.1:54321/auth/v1/callback`

That callback is GoTrue, not Next.js. Putting
`http://127.0.0.1:3000/auth/callback` in Cloud Console produces Google's
`redirect_uri_mismatch` 400.

4. Put the client ID and secret in `.env` as `GOOGLE_CLIENT_ID` and
   `GOOGLE_CLIENT_SECRET`. Keep
   `GOOGLE_REDIRECT_URI=http://127.0.0.1:54321/auth/v1/callback`.
5. Recreate the Auth container as described above, then sign in at
   `http://127.0.0.1:3000/login`.

If the consent screen is in Testing, add your Google account as a test user.

## Start the apps

`make dev-api` and `make dev-web` load `.env` then `.env.runtime` themselves.

```bash
make dev-api
```

In another terminal:

```bash
make dev-web
```

- Web: `http://127.0.0.1:3000`
- API: `http://127.0.0.1:8000`
- Ready check: `curl -sS http://127.0.0.1:8000/health/ready`

If `/health/ready` is not ready, the API did not load `.env.runtime` or
Supabase is down. Restart `make dev-api` from the repo root after
`make db-runtime-credentials`.

## Walk the product

1. Open `http://127.0.0.1:3000`.
2. Submit a synthetic first name, last name, email, resume (PDF, DOC, or DOCX
   up to 10 MiB), and the synthetic-data acknowledgement.
3. Sign in at `/login` with Google.
4. Open the new lead, download the resume, and mark it `REACHED_OUT`.

Default local mail points at a loopback capture stub
(`RESEND_BASE_URL=http://127.0.0.1:4319`). Lead creation still succeeds. The
stub is not a mailbox.

## Optional: real Resend mail

1. Create a Resend API key. Put it in `.env` as `RESEND_API_KEY`.
2. Set `RESEND_BASE_URL=https://api.resend.com`.
3. For the test sender `onboarding@resend.dev`, both the form email and
   `ATTORNEY_NOTIFICATION_EMAIL` must be the Resend account owner. Other
   inboxes need a verified domain and a From address on that domain.
4. Restart `make dev-api`. A 200 with an `id` means Resend accepted the
   request. It does not prove the inbox displayed the message.

## Checks

```bash
make lint typecheck
make unit
make db-check
make build
```

Playwright is optional and excluded from regular CI:

```bash
make test-e2e
```

Stop local Supabase with `make supabase-stop` when you are done.

The longer operator notes, including hosted deployment, live in the root
[README](../README.md).
