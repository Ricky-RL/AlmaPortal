# AlmaPortal browser tests

This is the Playwright workspace package for AlmaPortal. It assumes the web app, API, local Supabase stack, and storage bucket are already running. Locally it starts a SendGrid-compatible capture server by default. CI starts that server separately and sets `E2E_START_SENDGRID_STUB=false`.

## Run locally

1. Install from the repository root with `pnpm install`. The root `pnpm-lock.yaml` is the only workspace lockfile.
2. Start and reset local Supabase, then run `make db-runtime-credentials`. Source `.env.runtime` so the E2E process receives the local anon and service-role keys.
3. Copy `.env.example` to `.env` for E2E-specific values. Start the API with `SENDGRID_BASE_URL=http://127.0.0.1:4319`, then start the web app.
4. From this directory run:

   ```sh
   pnpm browsers:install
   pnpm test
   ```

Use `pnpm test:list` for Playwright discovery and `pnpm typecheck` for TypeScript validation. Desktop specs run in desktop Chromium. Specs tagged `@mobile` run against a Pixel 7 viewport.

## Authentication and isolation

The setup helper uses the local service-role key to create or update `dashboard@alma-e2e.invalid`. Its server-controlled `app_metadata` contains `provider: "google"` and `providers: ["google"]`. The helper signs in through local GoTrue and uses the same `@supabase/ssr` version and cookie adapter contract as `apps/web`. It verifies the serialized session through GoTrue before adding the emitted chunked cookies to the browser context.

There is no app route, header, or runtime authentication bypass. Remote Supabase hosts are rejected unless an operator explicitly opts into an isolated disposable environment.

All prospects use the reserved `alma-e2e.invalid` domain, synthetic names, and a generated one-page PDF. Tests run with one worker and use deterministic, test-scoped identifiers. Delivery-attempt history is append-only, so CI resets migrations before credentials and applications are started. For local runs, use `make demo-reset DEMO_RESET_CONFIRM=RESET-LOCAL-DEMO` before starting the API and web app. The E2E process does not reset a database underneath running services.

## Current integration contract

Paths and multipart names are configurable in `.env`. Defaults assume:

- the public form is `/`, sign-in is `/login`, and the dashboard is `/leads`
- successful public submission renders the inline `Submission received` heading; `E2E_SUCCESS_PATH` remains available for an explicitly configured routed variant
- the submission endpoint is `POST /api/v1/leads`
- multipart fields are `first_name`, `last_name`, `email`, `synthetic_data_acknowledged`, `resume`, and optional `comments`
- Supabase tables are `leads` and `email_deliveries`
- lead columns include `id`, `normalized_email`, `status`, and `resume_object_path`
- delivery columns include `lead_id`, `delivery_kind`, `state`, `active_claim_token`, and `retry_count`
- the storage bucket is `resumes`
- lead states are `PENDING` and `REACHED_OUT`
- browser delivery states include `PENDING`, `PROVIDER_ACCEPTED`, `FAILED`, and `UNKNOWN`

The page objects prefer accessible roles and labels. The expected UI contract is:

- labeled first name, last name, email, optional comments, resume, and acknowledgement form controls
- a visible success heading, status, or message
- `main` and navigation landmarks plus a single level-one heading
- a labeled search input and status filter
- a lead link or clickable row containing its synthetic name or email
- accessible controls for next-page navigation, CV download, marking reached out, notification retry, and retry confirmation

The SendGrid stub accepts `POST /v3/mail/send`, always returns `202`, and captures requests in memory. Before any test runs, setup verifies that `SENDGRID_BASE_URL` exactly matches the loopback stub origin and resets captured messages. This configuration check prevents repeated tests from contacting real email delivery without adding an application bypass.
