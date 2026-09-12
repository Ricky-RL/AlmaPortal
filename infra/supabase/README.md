# AlmaPortal Supabase infrastructure

The Supabase CLI migrations in this directory are the only database schema
system for AlmaPortal. Run CLI commands with `infra` as the work directory so
the CLI discovers `infra/supabase/config.toml`.

```sh
supabase --workdir infra start
supabase --workdir infra db reset --local
infra/supabase/scripts/policy_smoke.sh
```

Email and phone signup, outbound mail, analytics, and Edge Runtime are
disabled. Google OAuth is enabled for local reviewer sign-in when
`GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are present. The private
`resumes` bucket accepts PDF, DOC, and DOCX objects up to 10 MiB.

## API transaction flow

1. Generate the lead UUID in the API.
2. Call `reserve_new_lead_email_budget(lead_uuid)`. It atomically and
   idempotently consumes two credits from the UTC day.
3. Generate a separate UUID v4 object key and upload to
   `resumes/leads/{lead_uuid}/{object_uuid}.{pdf|doc|docx}` through the
   server-side Storage API. Pass that exact random path to
   `create_lead_with_deliveries(...)`; the original filename remains separate
   display metadata.
4. `create_lead_with_deliveries(...)` checks the lead-specific random path,
   recent budget reservation, media-type extension, and demo capacity, then
   creates both delivery projections.
5. Generate an attempt UUID and call `claim_email_delivery(...)`. Manual
   claims reserve one retry credit using that attempt UUID, enforce a
   one-minute cooldown, and stop after five manual retries. There is no
   separately callable retry-reservation function.
6. Send mail, then call `complete_email_delivery_attempt(...)` with the claim
   token. The JSON result reports `completed`, `already_completed`, or
   `stale_claim`; stale claims cannot overwrite the current projection.
7. A worker calls `expire_email_delivery_claim(delivery_uuid)` for expired
   processing rows. The attempt becomes `unknown`, the JSON result reports the
   projection state, and no budget is refunded.

An active processing lease rejects a manual claim with SQLSTATE `55P03`. A
manual claim on an expired lease closes the old attempt as `unknown` in the
same transaction and reports `duplicate_confirmation_required` or `cooldown`.
Any `unknown` delivery requires `p_duplicate_risk_confirmed = true` before a
new attempt can be created. Retry budget is consumed only when that new manual
attempt is created.

Claim and completion functions return JSON with stable `status` values plus
delivery, attempt, lease, retry, and provider fields needed by the API.
Expected exception mappings are:

- `22004` for missing required identity values.
- `22023` for invalid object paths, trigger kinds, or outcomes.
- `P0002` for missing leads, deliveries, or attempts.
- `55P03` for an active claim lease.
- `55000` for invalid state, cooldown, or inconsistent claim identity.
- `54000` for the five-retry limit.
- `23505` for a reused request or attempt ID.
- `23514` with a named constraint for invalid persisted field coherence.
- `P0001` for exhausted budget/capacity or a missing submission reservation.

`mark_lead_reached_out(...)` is a one-way, idempotent audit transition.
Delivery attempt identity and completed history cannot be edited or deleted.

## Runtime credential

Migrations create `alma_api` with no password and without inheritance,
superuser, role-creation, database-creation, replication, or RLS-bypass
attributes. Install or rotate its runtime credential out of band:

```sh
python3 -m pip install -r infra/supabase/scripts/requirements.txt
SUPABASE_DB_ADMIN_URL='...' \
  python3 infra/supabase/scripts/bootstrap_api_role.py
```

The password is read from a protected prompt, or from `ALMA_API_PASSWORD`.
Neither script path prints or writes the secret.

## Storage reconciliation and local reset

`storage_reconcile.py` produces a read-only orphan and missing-object report.
Object removal requires a saved plan less than 24 hours old, the exact
confirmation token printed by `--help`, and server-side Storage credentials.
Each object is checked again before deletion and removed through the Storage
API, never by changing Storage tables.

`demo_reset.sh` prints a plan by default and only resets the local Supabase
stack after an explicit confirmation. It rejects database URL environment
variables to avoid targeting a remote database.
