# AlmaPortal Agent Guide

## Purpose and architecture

AlmaPortal is a secure lead intake and review portal. Visitors submit synthetic lead details and a resume, while Google-authenticated reviewers inspect leads, download private resumes through the API, update lead status, and retry uncertain email delivery. The browser application handles user interaction, the Python API owns privileged operations and external integrations, and Supabase provides authentication, PostgreSQL data, row-level authorization, and private object storage.

The repository is a pnpm and uv monorepo:

- `apps/web`: TypeScript web application. It must use publishable browser credentials only.
- `apps/api`: Python 3.12 API. It owns secret-bearing operations, email delivery, protected download tickets, and other server-side integrations.
- `infra/supabase`: local Supabase configuration, migrations, policies, storage setup, and database tests.
- `tests/e2e`: Playwright journeys across the web, API, and local Supabase stack.
- `docs`: product, architecture, operations, and decision records.

Use the root `Makefile` as the stable command interface. Keep implementation-specific commands inside their owning module when possible.

## Git governance

These rules apply to people and agents:

1. Create a feature branch before making edits. Never commit on `main`.
2. Commit coherent, green slices frequently.
3. Run affected checks before each commit and the full suite before handoff.
4. Never push unless the current user message explicitly says `push`.
5. After approval, open a pull request that follows the repository template.
6. Run an independent review of the complete branch changes.
7. Address valid findings in new commits. Do not rewrite reviewed history to hide fixes.
8. Require review approval and green CI. Squash merge only after both are satisfied.

Child `AGENTS.md` files inherit every rule here. They may add stricter module guidance, but they cannot weaken or override this governance or the security rules below.

## Security and data handling

- Real secrets and personally identifiable information must never enter git, fixtures, screenshots, logs, or CI output.
- Browser code must never receive Supabase secret keys, database credentials, SendGrid keys, deployment tokens, or download-ticket signing secrets.
- Keep privileged access in `apps/api`. Enforce authorization again in PostgreSQL policies.
- Use `.env.example` only as a name and shape reference. Use local, ignored environment files for actual values.
- Use synthetic data for development, tests, demos, and bug reports.

## Verification

Run focused checks while working. Before handoff, start local Supabase, reset migrations from zero, and run the API and web servers in separate terminals. Then run:

```sh
make ci
```

The full check covers linting, type checking, Python and web unit tests, database policy tests, Playwright journeys, and builds. Stop local services with `make supabase-stop`.
