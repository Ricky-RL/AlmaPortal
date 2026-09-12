# AlmaPortal API agent rules

This file inherits every rule from the repository root `AGENTS.md`. If this file
and the root file differ, the stricter rule applies.

## Scope

- API work stays under `apps/api/**`.
- Use Python 3.12 and keep the package under `src/alma_api`.
- Keep domain and application code independent of FastAPI, SQLAlchemy, and
  external provider SDK types.
- Supabase migrations own the database schema. Do not call `create_all` or add
  application-managed migrations here.
- Never persist secrets, tokens, email recipients, or private object URLs.

## Required repository workflow

The root branch policy, frequent-commit policy, push-approval policy, pull
request workflow, CI requirements, and squash-merge workflow all apply here and
cannot be weakened or bypassed by nested instructions. In particular, a push
always requires explicit approval in the same user message.
