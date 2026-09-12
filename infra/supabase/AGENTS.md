# AlmaPortal Supabase module

This directory inherits all guidance from the repository-root `AGENTS.md` and
other higher-level repository instructions. The inherited root branch,
commit, push, and pull-request workflow cannot be weakened or overridden here.
If guidance conflicts, follow the stricter rule.

## Scope

This module owns the Supabase PostgreSQL schema, private resume-bucket
configuration, database access controls, local Supabase configuration, policy
tests, and database operational scripts. Application code must treat these
files as the only schema source.

## Migrations

- Use ordered Supabase CLI SQL migrations in `migrations/` for every schema,
  role, policy, function, trigger, bucket, constraint, and index change.
- Do not introduce Alembic, SQLAlchemy `create_all`, ORM-generated DDL, or
  ad-hoc production schema commands.
- Never edit a migration that has been applied to a shared environment. Add a
  new forward migration.
- Keep transaction-sensitive behavior in small database functions that
  SQLAlchemy can call explicitly. Qualify object names and pin
  `search_path` on security-definer functions.
- Store instants as `timestamptz`. Daily budget dates are calculated in UTC.
- Resume object paths are caller-generated UUID v4 keys under
  `leads/{lead_id}/`; never derive them from the original filename.
- Manual retries use a one-minute cooldown. Unknown outcomes require explicit
  duplicate-risk confirmation, and retry budget is reserved only while the
  manual attempt is created.
- Do not add real people, resumés, credentials, provider IDs, or production
  object paths to migrations or `seed.sql`.

## Policy tests

Run `scripts/policy_smoke.sh` against a reset local database after changing
grants, RLS, storage policies, or security-definer functions. Tests must prove
that `anon` and `authenticated` cannot read or mutate AlmaPortal records or
the private `resumes` bucket. They must also prove that `alma_api` has read
access only to the intended projections and can write only through the
approved functions.

Policy tests run in a transaction and roll back their synthetic records. Keep
them independent of storage objects and external services.

## Operational scripts

- Scripts are admin tools. Default to a read-only plan or dry run.
- Require an explicit confirmation token for destructive actions.
- Read passwords and service keys from protected prompts or environment
  variables. Never print, log, write, or add them to command arguments.
- Refuse production-looking targets when an operation is intended only for
  local development.
- Use the Storage API for object deletion. Never delete rows directly from
  Supabase Storage internal tables.
- Keep runtime database credentials separate from migrations. Migrations
  create `alma_api` without a password; `scripts/bootstrap_api_role.py`
  installs or rotates the secret out of band.
