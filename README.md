# AlmaPortal

AlmaPortal is a take-home lead intake and review portal. A visitor can submit a
synthetic lead and resume, and a reviewer can sign in with Google, inspect the
lead, download its private resume through the API, mark it as reached out, and
manually retry an email whose outcome is failed or unknown.

## Assignment outcome

Public repository: [https://github.com/Ricky-RL/AlmaPortal](https://github.com/Ricky-RL/AlmaPortal)

Submission packet:

- Local run: [docs/local-setup.md](docs/local-setup.md)
- Design: [docs/system-design.md](docs/system-design.md)
- Coding-agent usage and prompt excerpts: [docs/agent-usage.md](docs/agent-usage.md)
- Agent vs hand-written attribution: [NOTES.md](NOTES.md)
- Checklist and recording script: [docs/SUBMISSION.md](docs/SUBMISSION.md)

The repository contains:

- A Next.js application for public lead submission and the authenticated
  reviewer workflow.
- A Python 3.12 FastAPI service with domain rules, authorization, upload
  validation, private file streaming, and Resend delivery tracking.
- Supabase migrations for Postgres, row-level security, private Storage,
  transactional delivery claims, and email budget controls. Google
  authentication is configured in Supabase, while FastAPI owns rate limits and
  download tickets.
- Unit and integration tests, CI, and a main-only production deployment
  workflow for Supabase, Render, and Vercel.
- A detailed [system design](docs/system-design.md) covering boundaries,
  contracts, security, concurrency, failure handling, and production gaps.

Hosted deployment placeholders:

- Web application: `<set after the first Vercel production deployment>`
- API: `<set after the first Render production deployment>`
- API version: `<must equal the deployed Git commit SHA>`

These placeholders are intentional. The repository does not claim a hosted
demo or deployment result until one exists.

> **Synthetic data only.** Do not enter real personal information, resumes,
> customer records, secrets, or privileged legal data. The hosted demo permits
> any Google account so evaluators can test immediately without waiting for
> allowlist approval. That reviewer access policy is intentionally unsafe for
> real PII. Production must require a verified organization domain or an
> explicit reviewer allowlist, backed by server-side authorization.

## Architecture summary

```text
Browser
  -> Vercel / Next.js
       -> Supabase Auth (Google OAuth)
       -> Render / FastAPI
            -> Supabase Postgres
            -> private Supabase Storage
            -> Resend
```

The browser submits public lead data to FastAPI. Reviewer operations go through
same-origin Next.js route handlers, which forward the Supabase access token
without storing it in application state. FastAPI validates the JWT and performs
all privileged database and Storage work. Resumes remain in a private bucket.
Short-lived signed download tickets authorize API-streamed downloads, so
the browser never receives a reusable private object URL.

Each lead owns two independent deliveries: a confirmation to the prospect and
a notification to the configured attorney. A Resend HTTP acceptance is
recorded as `provider_accepted`. It does not prove recipient delivery.

See [docs/system-design.md](docs/system-design.md) for the full design.

## Canonical API and storage contract

Public routes:

- `POST /api/v1/leads` accepts `first_name`, `last_name`, `email`,
  `synthetic_data_acknowledged`, one `resume` multipart file, and optional
  `comments`.
- `GET /health/live`, `GET /health/ready`, and `GET /version` support platform
  checks and exact commit verification.

Reviewer routes require a Supabase Google JWT:

- `GET /api/v1/me`
- `POST /api/v1/leads/search`
- `GET /api/v1/leads/summary`
- `GET /api/v1/leads/{lead_id}`
- `PATCH /api/v1/leads/{lead_id}/status`
- `POST /api/v1/leads/{lead_id}/resume-download`
- `POST /api/v1/leads/{lead_id}/deliveries/{delivery_id}/retry`

Lead detail includes both delivery projections and append-only attempt history.
Resumes use random server-generated paths shaped as
`leads/{lead_id}/{uuid-v4}.{pdf|doc|docx}` inside the private `resumes` bucket.
The ticket endpoint returns an absolute URL rooted at `PUBLIC_API_URL`.
Following that short-lived ticket streams the object through FastAPI on Render;
it never exposes a Supabase object URL.

Postgres owns the daily mail budget. A new lead atomically reserves two credits
from the default 80-credit new-lead pool. A manual retry reserves one credit
from the separate default 20-credit retry pool. Failed and unknown deliveries
can be retried manually after the one-minute cooldown, with at most five manual
retries. A reviewer can also trigger an initial attempt that remains `pending`.
An expired `processing` attempt is durably reconciled to `unknown` before the
API asks for duplicate-risk confirmation or permits a retry. Unknown outcomes
require explicit duplicate-risk confirmation.

## Monorepo map

```text
apps/
  api/                    FastAPI application and Python tests
  web/                    Next.js application and browser-facing tests
infra/supabase/
  migrations/             Database, RLS, Storage, and transactional functions
tests/                    Repository-level and hosted smoke tests
docs/
  SUBMISSION.md           Assignment checklist and recording script
  local-setup.md          How to run the stack on loopback
  system-design.md        Architecture and operating decisions
  agent-usage.md          Coding-agent writeup and prompt excerpts
NOTES.md                  Agent-generated vs hand-written attribution
.github/workflows/
  ci.yml                  Pull request and main CI
  deploy.yml              Ordered production deployment
render.yaml               Render Blueprint for the API
Makefile                  Local setup, development, checks, and operations
```

Generated directories, local environment files, Supabase state, Vercel state,
and uploaded resumes must remain untracked.

## Prerequisites

- Git
- Make
- Node.js 22 LTS with Corepack
- pnpm, selected through the repository `packageManager` field
- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started)
- Docker Desktop or another Docker-compatible runtime for local Supabase
- A Google Cloud project for reviewer OAuth
- A Resend account. `onboarding@resend.dev` can send to the account owner.
  Arbitrary recipients need a verified domain.

Render, Vercel, and hosted Supabase accounts are only needed for deployment.

## Tool setup

Enable pnpm:

```bash
corepack enable
pnpm --version
```

Install uv on macOS or Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version
```

Install the Supabase CLI with Homebrew:

```bash
brew install supabase/tap/supabase
supabase --version
```

The Supabase CLI can also be run without a global install:

```bash
pnpm dlx supabase --version
```

## Environment setup

Install workspace dependencies and create local environment files:

```bash
make setup
cp .env.example .env
cp apps/web/.env.example apps/web/.env.local
```

The short evaluator path is [docs/local-setup.md](docs/local-setup.md).
Populate the local files from `supabase status` and the provider dashboards.
Keep these distinctions:

- Browser-visible values may include only `NEXT_PUBLIC_API_URL`,
  `NEXT_PUBLIC_SUPABASE_URL`, and the Supabase anon key.
- `API_URL`, `APP_URL`, and `CSRF_SECRET` are server-only Next.js values.
- Database credentials, the Supabase service-role key, Resend key, attorney
  recipient, sender identity, and ticket-signing secret belong only in FastAPI
  or provider secret stores.
- Never expose a service-role key or Resend key through a `NEXT_PUBLIC_*`
  variable.

Start the local Supabase stack and apply all migrations:

```bash
make supabase-start
make supabase-reset
make db-runtime-credentials
```

`make db-runtime-credentials` creates or rotates the least-privilege
`alma_api` database role, generates a local password unless
`ALMA_API_PASSWORD` is supplied, and writes mode-0600 credentials to the
ignored `.env.runtime` file.

Then start the applications in separate terminals. `make dev-api` and
`make dev-web` load `.env` then `.env.runtime` themselves:

```bash
make dev-api

# In another terminal:
make dev-web
```

The local web application uses `http://127.0.0.1:3000`. Get the API port and
local Supabase URLs from `make help` and `supabase status`, rather than copying
hosted credentials into local files.

## Make commands

`make help` is the command index. The repository expects these local entry
points:

- `make setup`: install JavaScript and Python dependencies.
- `make dev-web` and `make dev-api`: run one application.
- `make supabase-start` and `make supabase-stop`: control local Supabase.
- `make supabase-reset`: rebuild the local database from migrations and seed.
- `make db-runtime-credentials`: bootstrap the `alma_api` role and write
  ignored mode-0600 values to `.env.runtime`.
- `make lint`: run ESLint and Ruff.
- `make typecheck`: run TypeScript and strict mypy checks.
- `make test`: run the normal unit test suites.
- `make test-e2e`: run the optional Playwright artifact manually.
- `make test-integration`: run database checks and the optional browser
  journeys.
- `make ci`: run the repository's broad local check, including optional
  Playwright coverage.
- `make db-check`: verify database connectivity and expected migrations.
- `make storage-audit`: produce a read-only orphan and missing-resume report.
- `make demo-reset`: print a local-only reset plan. Apply it only with
  `DEMO_RESET_CONFIRM=RESET-LOCAL-DEMO`.
- `make build`: build the web app and compile-check the API.
- `make email-smoke`: send one explicitly requested real email to
  `EMAIL_SMOKE_RECIPIENT`. Do not put this target in normal CI or hosted smoke
  tests.

## Tests

The named GitHub `CI` workflow requires backend and web unit tests, lint and
type checks, Supabase policy and migration checks, and both application builds.
Run its required groups locally with:

```bash
make lint typecheck
make unit
make db-check
make build
```

Run stacks directly when diagnosing a failure:

```bash
pnpm --dir apps/web lint
pnpm --dir apps/web typecheck
pnpm --dir apps/web test

(cd apps/api && uv run ruff check .)
(cd apps/api && uv run mypy src)
(cd apps/api && uv run pytest)

make db-check
```

Database integration checks require local Supabase and are never pointed at
production. Playwright exists only as an optional manual artifact. It is
excluded from regular CI per user direction, so browser installation and
journeys are not release gates. No test result is claimed in this README. The
named `CI` workflow is the source of truth for its release commit.

Operational commands remain guarded:

```bash
make storage-audit
make demo-reset
DEMO_RESET_CONFIRM=RESET-LOCAL-DEMO make demo-reset
EMAIL_SMOKE_RECIPIENT=<authorized-unrelated-address> make email-smoke
```

`storage-audit` is read-only unless the reconciliation script is separately
given a reviewed plan and its explicit purge confirmation. A purge excludes
objects created within the 15-minute grace period. Before apply, quiesce lead
submissions and other resume writes, generate and review a fresh plan, keep the
system quiesced, and provide the script's exact confirmation token. Each object
is checked again before deletion. Apply requires both
`--confirm PURGE-ORPHAN-RESUMES` and
`--confirm-submissions-quiesced SUBMISSIONS-QUIESCED`. `demo-reset` rejects
remote database variables and defaults to a dry run. The email smoke recipient
must be unrelated to configured application addresses and authorized to
receive the test.

## Google OAuth setup

Local reviewer sign-in uses Google through local Supabase Auth. A 400 before
Google's account picker usually means the Google provider is off or the
redirect URI in Cloud Console is not the GoTrue callback.

### Google Cloud Console

1. Open [Google Cloud Console](https://console.cloud.google.com/) and select or
   create a project.
2. Open [Google Auth Platform](https://console.cloud.google.com/auth/overview).
   If it asks you to configure the consent screen first, choose External
   audience, set an app name such as AlmaPortal, and use your Google account as
   the support email. Add the `openid`, `.../auth/userinfo.email`, and
   `.../auth/userinfo.profile` scopes.
3. If the app stays in Testing, add your Google account under Test users.
   Publishing the app is only required when people outside that list must sign
   in.
4. Create a client: Clients, Create client, application type Web application.
5. Authorized JavaScript origin, local:
   - `http://127.0.0.1:3000`

6. Authorized redirect URIs, local. This must be the Supabase Auth callback,
   not the Next.js route:
   - `http://127.0.0.1:54321/auth/v1/callback`

   Do not put `http://127.0.0.1:3000/auth/callback` here. That mismatch is the
   usual Google 400 (`redirect_uri_mismatch`).

7. Create the client and copy the client ID and client secret.

### Local Supabase

1. Copy `.env.example` to ignored `.env` if you have not already.
2. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and keep
   `GOOGLE_REDIRECT_URI=http://127.0.0.1:54321/auth/v1/callback`.
3. Recreate the local Auth container so it picks up the provider settings.
   Use a normal CLI stop, not `make supabase-stop`, because that Make target
   drops local data:

   ```bash
   supabase stop --workdir infra
   make supabase-start
   ```

4. Sign in at `http://127.0.0.1:3000/login`. Use that host consistently with
   the origin you added in Cloud Console.

The browser never receives the Google client secret. Local GoTrue holds it.

### Hosted project

1. Add the Vercel origin as an authorized JavaScript origin.
2. Add `https://<supabase-project-ref>.supabase.co/auth/v1/callback` as an
   authorized redirect URI. Use the callback shown on the Supabase Google
   provider page if it differs.
3. In the Supabase Dashboard, enable Google and store the same client ID and
   client secret.
4. Set Site URL to the deployed Vercel origin. Add
   `http://127.0.0.1:3000/auth/callback` and the deployed
   `https://<vercel-host>/auth/callback` path to the allowed redirect URLs.
5. Put only the Supabase URL and anon key in the web environment.

For the hosted assessment, do not add a Google domain restriction or reviewer
allowlist. This open Google authentication is a deliberate reviewer-access
workaround, not a production authorization design. It removes scheduling and
allowlist friction for evaluators. A production release must enforce domain or
allowlist membership in FastAPI on every reviewer endpoint, regardless of what
the UI shows.

## Supabase setup

For local development:

```bash
make supabase-start
make supabase-reset
make db-runtime-credentials
supabase status
```

For a hosted project:

```bash
supabase login
supabase link --workdir infra --project-ref <project-ref>
supabase db push --workdir infra
```

After migration, confirm that:

- Google Auth is configured.
- The resume bucket is private.
- Row-level security is enabled on exposed tables.
- Browser clients have no direct private-resume read policy.
- FastAPI has the hosted database URL, Supabase URL, service-role key, expected
  JWT audience, and exact Vercel origin.
- `GET /health/ready` succeeds as `alma_api` only after checking the runtime
  database identity, required schema functions and grants, and database access.
- Backup and point-in-time recovery settings match the chosen Supabase plan.

The custom `alma_api` database role has only the required read and function
execution grants. The Supabase service-role key is used for private Storage and
stays on Render. FastAPI must perform object-level authorization before every
lead or Storage request.

Local Supabase CLI sessions use genuine Supabase HS256 access tokens and the
local JWT secret from `supabase status`. That verifier is accepted only with a
loopback Supabase URL outside production. Hosted Supabase must use its exact
HTTPS issuer and JWKS URLs with an explicit asymmetric algorithm allowlist.

## Resend setup

1. Create a Resend account and copy an API key with send permission.
2. For mail to your own inbox only, set `RESEND_FROM_EMAIL` to
   `onboarding@resend.dev`. That test sender cannot reach arbitrary addresses.
3. To notify other inboxes, add and verify a domain, then set
   `RESEND_FROM_EMAIL` to an address on that domain.
4. Configure the API key, From address, and attorney recipient as Render
   secrets. Production `RESEND_BASE_URL` stays `https://api.resend.com`.
5. Review the Postgres-owned 80-credit new-lead pool and 20-credit retry pool
   against the current Resend plan limit.
6. Run
   `EMAIL_SMOKE_RECIPIENT=<authorized-unrelated-address> make email-smoke` once,
   then inspect the Resend emails dashboard.

If you are still on the test sender, the smoke recipient and any submitted
lead email must be the Resend account address. A `200` response with an `id`
means Resend accepted the request. It does not mean the recipient inbox
accepted or displayed the message. Production needs event webhooks for
delivered, bounced, complained, and failed outcomes.

The provider allowance and the application budget must both permit a send.

## Production deployment

Provision providers in this order:

1. Create and configure hosted Supabase, Google OAuth, and Resend.
2. Create the Render service from `render.yaml`, connect the repository, and
   keep automatic deploys disabled so GitHub Actions controls ordering.
3. Create a Vercel project with `apps/web` as its project root and configure its
   production environment variables.
4. Create a GitHub `production` environment. Add required reviewers if desired.
5. Add the required GitHub Actions secrets and variables.
6. Merge to `main`. A successful completion of the named `CI` workflow triggers
   deployment. There is no manual deployment path that can bypass CI.

GitHub environment secrets:

- `SUPABASE_ACCESS_TOKEN`
- `SUPABASE_DB_PASSWORD`
- `RENDER_API_KEY`
- `VERCEL_TOKEN`

GitHub environment variables:

- `SUPABASE_PROJECT_REF`
- `RENDER_SERVICE_ID`
- `PUBLIC_API_URL`, set to the real Render service origin
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

Repository IDs are configuration, not values this repository can safely guess.
The deployment workflow requires them through variables. Provider credentials
remain encrypted secrets.

The workflow derives one `RELEASE_SHA` from
`github.event.workflow_run.head_sha`, checks out that commit, applies
migrations, asks Render to deploy that exact commit, and retains and polls the
returned Render deployment ID. It requires `GET /version` to equal
`RELEASE_SHA`, so an older healthy service cannot pass. Only then does it build
and deploy Vercel from the same checkout. Hosted smoke tests use health,
version, and web page reads. They do not submit a lead or send email, so
rerunning a deployment cannot create repeated real mail.

Render's free web service sleeps when idle. The first request after inactivity
can be slow enough to look like a timeout. This assessment intentionally has no
automatic email retry loop because a sleeping free Render instance cannot run
a dependable worker or scheduler, and adding paid always-on compute only for a
take-home would add avoidable cost. Failed and unknown attempts are retried
manually after the reviewer sees the state and confirms duplicate-send risk.

Vercel must hold the web environment values, including the deployed API origin,
Supabase URL, anon key, app origin, and a strong CSRF secret. Render must hold
the database, Supabase, Storage, Resend, recipient, CORS, rate-limit, and
upload-limit settings declared by `render.yaml` and the API environment
example. Set Render's required `PUBLIC_API_URL` to its exact public HTTPS
origin. Production `RESEND_BASE_URL` remains
`https://api.resend.com`; only isolated local tests point it at a stub.
Set `SUPABASE_URL`, `SUPABASE_JWT_ISSUER`, and `SUPABASE_JWKS_URL` to the exact
hosted HTTPS values. Use a direct `alma_api` Postgres connection that requires
TLS, such as `sslmode=require`, and verify the hosted CA policy rather than
disabling certificate checks.

The current API trusts forwarded addresses only when the direct peer is in
`TRUSTED_PROXY_CIDRS`, then resolves a validated `X-Forwarded-For` chain.
Render operators must set that required value to the documented Render proxy
CIDRs before relying on per-client limits. If Cloudflare is placed in front,
normalize its `CF-Connecting-IP` value at the trusted edge into that chain and
never accept the header directly from an untrusted peer. Until the final proxy
path and CIDRs are confirmed in production, treat source throttling as an
operational prerequisite, not a completed control.

## Production gaps and assessment compromises

- Hosted reviewer access accepts any Google account. Add server-side domain or
  allowlist authorization before storing real data.
- Resend's `onboarding@resend.dev` sender can reach the account owner. Verify a
  domain with SPF, DKIM, and DMARC before sending to arbitrary inboxes.
- Provider acceptance is not final delivery. Add signed Resend event
  webhooks, suppression handling, and delivery reconciliation.
- Free Render cold starts can delay submissions and downloads. Use always-on
  compute plus a queue and worker before introducing automatic retries.
- Resume validation cannot replace malware scanning. Add quarantine, scanning,
  and delayed release for production uploads.
- Apply formal retention, user deletion, audit access, backup expiry, and legal
  hold policies before real PII.
- Add centralized metrics, alerting, traces, a dead-letter workflow, and
  provider runbooks.
- Add staging with separate Supabase, Resend, Render, Vercel, OAuth, and
  secrets. Never test destructive migrations or real mail against production.
