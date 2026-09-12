-- Private resume storage, the SQLAlchemy login role, explicit grants, and RLS.
-- The browser-facing anon/authenticated roles intentionally receive no data
-- policy for AlmaPortal records or resume objects.

do $block$
begin
    if not exists (
        select 1
          from pg_catalog.pg_roles
         where rolname = 'alma_api'
    ) then
        create role alma_api
            login
            nosuperuser
            nocreatedb
            nocreaterole
            noinherit
            noreplication
            nobypassrls;
    end if;
end;
$block$;

do $block$
begin
    execute format(
        'grant connect on database %I to alma_api',
        current_database()
    );
end;
$block$;

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'resumes',
    'resumes',
    false,
    10485760,
    array[
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ]::text[]
)
on conflict (id) do update
set name = excluded.name,
    public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

alter table public.leads enable row level security;
alter table public.leads force row level security;
alter table public.email_deliveries enable row level security;
alter table public.email_deliveries force row level security;
alter table public.email_delivery_attempts enable row level security;
alter table public.email_delivery_attempts force row level security;
alter table public.daily_email_budgets enable row level security;
alter table public.daily_email_budgets force row level security;
alter table public.email_budget_reservations enable row level security;
alter table public.email_budget_reservations force row level security;
alter table public.demo_capacity enable row level security;
alter table public.demo_capacity force row level security;

create policy alma_api_read_leads
on public.leads
for select
to alma_api
using (true);

create policy alma_api_read_email_deliveries
on public.email_deliveries
for select
to alma_api
using (true);

create policy alma_api_read_email_delivery_attempts
on public.email_delivery_attempts
for select
to alma_api
using (true);

create policy browser_deny_leads
on public.leads
as restrictive
for all
to anon, authenticated
using (false)
with check (false);

create policy browser_deny_email_deliveries
on public.email_deliveries
as restrictive
for all
to anon, authenticated
using (false)
with check (false);

create policy browser_deny_email_delivery_attempts
on public.email_delivery_attempts
as restrictive
for all
to anon, authenticated
using (false)
with check (false);

create policy browser_deny_daily_email_budgets
on public.daily_email_budgets
as restrictive
for all
to anon, authenticated
using (false)
with check (false);

create policy browser_deny_email_budget_reservations
on public.email_budget_reservations
as restrictive
for all
to anon, authenticated
using (false)
with check (false);

create policy browser_deny_demo_capacity
on public.demo_capacity
as restrictive
for all
to anon, authenticated
using (false)
with check (false);

-- Restrictive storage policies keep this bucket private even if a later,
-- permissive policy is added for another bucket.
create policy alma_resumes_browser_object_deny
on storage.objects
as restrictive
for all
to anon, authenticated
using (bucket_id <> 'resumes')
with check (bucket_id <> 'resumes');

create policy alma_resumes_browser_bucket_deny
on storage.buckets
as restrictive
for all
to anon, authenticated
using (id <> 'resumes')
with check (id <> 'resumes');

revoke all on table public.leads
    from public, anon, authenticated, alma_api;
revoke all on table public.email_deliveries
    from public, anon, authenticated, alma_api;
revoke all on table public.email_delivery_attempts
    from public, anon, authenticated, alma_api;
revoke all on table public.daily_email_budgets
    from public, anon, authenticated, alma_api;
revoke all on table public.email_budget_reservations
    from public, anon, authenticated, alma_api;
revoke all on table public.demo_capacity
    from public, anon, authenticated, alma_api;

revoke all on table storage.objects
    from alma_api;
revoke all on table storage.buckets
    from alma_api;

grant usage on schema public to alma_api;
grant select on table public.leads to alma_api;
grant select on table public.email_deliveries to alma_api;
grant select on table public.email_delivery_attempts to alma_api;

revoke all on function public.set_row_updated_at()
    from public, anon, authenticated, alma_api;
revoke all on function public.guard_lead_status_transition()
    from public, anon, authenticated, alma_api;
revoke all on function public.reserve_demo_capacity_for_lead()
    from public, anon, authenticated, alma_api;
revoke all on function public.release_demo_capacity_for_lead()
    from public, anon, authenticated, alma_api;
revoke all on function public.guard_email_attempt_history()
    from public, anon, authenticated, alma_api;
revoke all on function public._reserve_email_budget(uuid, text)
    from public, anon, authenticated, alma_api;

revoke all on function public.reserve_new_lead_email_budget(uuid)
    from public, anon, authenticated, alma_api;
revoke all on function public.get_current_email_budget()
    from public, anon, authenticated, alma_api;
revoke all on function public.get_demo_capacity()
    from public, anon, authenticated, alma_api;
revoke all on function public.create_lead_with_deliveries(
    uuid, text, text, text, text, text, text, bigint, text, text
) from public, anon, authenticated, alma_api;
revoke all on function public.mark_lead_reached_out(uuid, uuid, text)
    from public, anon, authenticated, alma_api;
revoke all on function public.claim_email_delivery(
    uuid, uuid, text, uuid, text, boolean
) from public, anon, authenticated, alma_api;
revoke all on function public.complete_email_delivery_attempt(
    uuid, uuid, text, integer, text, text
) from public, anon, authenticated, alma_api;
revoke all on function public.expire_email_delivery_claim(uuid)
    from public, anon, authenticated, alma_api;

grant execute on function public.reserve_new_lead_email_budget(uuid)
    to alma_api;
grant execute on function public.get_current_email_budget()
    to alma_api;
grant execute on function public.get_demo_capacity()
    to alma_api;
grant execute on function public.create_lead_with_deliveries(
    uuid, text, text, text, text, text, text, bigint, text, text
) to alma_api;
grant execute on function public.mark_lead_reached_out(uuid, uuid, text)
    to alma_api;
grant execute on function public.claim_email_delivery(
    uuid, uuid, text, uuid, text, boolean
) to alma_api;
grant execute on function public.complete_email_delivery_attempt(
    uuid, uuid, text, integer, text, text
) to alma_api;
grant execute on function public.expire_email_delivery_claim(uuid)
    to alma_api;

alter default privileges in schema public
    revoke all on tables from public, anon, authenticated, alma_api;
alter default privileges in schema public
    revoke execute on functions from public, anon, authenticated, alma_api;

comment on role alma_api is
    'Passwordless-at-migration SQLAlchemy runtime role; bootstrap credentials out of band.';
