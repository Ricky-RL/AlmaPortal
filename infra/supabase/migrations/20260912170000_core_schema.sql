-- AlmaPortal's database schema is managed only through ordered Supabase CLI
-- migrations. All application timestamps use timestamptz, which PostgreSQL
-- stores as UTC instants.

create schema if not exists extensions;
create extension if not exists pgcrypto with schema extensions;

create table public.daily_email_budgets (
    budget_date date primary key,
    new_lead_credit_limit integer not null default 80,
    new_lead_credits_used integer not null default 0,
    retry_credit_limit integer not null default 20,
    retry_credits_used integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint daily_email_budgets_new_lead_limit_nonnegative
        check (new_lead_credit_limit >= 0),
    constraint daily_email_budgets_new_lead_used_in_range
        check (
            new_lead_credits_used >= 0
            and new_lead_credits_used <= new_lead_credit_limit
        ),
    constraint daily_email_budgets_retry_limit_nonnegative
        check (retry_credit_limit >= 0),
    constraint daily_email_budgets_retry_used_in_range
        check (
            retry_credits_used >= 0
            and retry_credits_used <= retry_credit_limit
        )
);

create table public.email_budget_reservations (
    reservation_key uuid primary key,
    budget_date date not null
        references public.daily_email_budgets (budget_date)
        on update restrict
        on delete restrict,
    reservation_kind text not null,
    credits integer not null,
    created_at timestamptz not null default now(),
    constraint email_budget_reservations_kind_valid
        check (reservation_kind in ('new_lead', 'retry')),
    constraint email_budget_reservations_credit_shape
        check (
            (reservation_kind = 'new_lead' and credits = 2)
            or (reservation_kind = 'retry' and credits = 1)
        )
);

create table public.demo_capacity (
    singleton boolean primary key default true,
    lead_count integer not null default 0,
    resume_bytes bigint not null default 0,
    lead_limit integer not null default 200,
    resume_byte_limit bigint not null default 524288000,
    updated_at timestamptz not null default now(),
    constraint demo_capacity_single_row check (singleton),
    constraint demo_capacity_lead_count_in_range
        check (lead_count >= 0 and lead_count <= lead_limit),
    constraint demo_capacity_resume_bytes_in_range
        check (resume_bytes >= 0 and resume_bytes <= resume_byte_limit),
    constraint demo_capacity_limits_nonnegative
        check (lead_limit >= 0 and resume_byte_limit >= 0)
);

insert into public.demo_capacity (singleton)
values (true)
on conflict (singleton) do nothing;

create table public.leads (
    id uuid primary key default pg_catalog.gen_random_uuid(),
    first_name varchar(100) not null,
    last_name varchar(100) not null,
    normalized_email varchar(320) not null,
    resume_object_path varchar(260) not null,
    original_filename varchar(180) not null,
    detected_media_type varchar(100) not null,
    byte_size bigint not null,
    status varchar(24) not null default 'PENDING',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    reached_out_at timestamptz,
    reached_out_by_user_id uuid,
    reached_out_by_email varchar(320),
    constraint leads_first_name_bounded
        check (
            char_length(first_name) between 1 and 100
            and first_name = btrim(first_name)
            and first_name !~ '[[:cntrl:]]'
        ),
    constraint leads_last_name_bounded
        check (
            char_length(last_name) between 1 and 100
            and last_name = btrim(last_name)
            and last_name !~ '[[:cntrl:]]'
        ),
    constraint leads_email_normalized
        check (
            char_length(normalized_email) between 3 and 320
            and normalized_email = lower(btrim(normalized_email))
            and normalized_email ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'
        ),
    constraint leads_filename_sanitized
        check (
            char_length(original_filename) between 1 and 180
            and original_filename not in ('.', '..')
            and original_filename ~ '^[A-Za-z0-9][A-Za-z0-9._-]*$'
        ),
    constraint leads_object_path_private_and_stable
        check (
            char_length(resume_object_path) between 83 and 84
            and resume_object_path ~ (
                '^leads/'
                || id::text
                || '/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-'
                || '[89ab][0-9a-f]{3}-[0-9a-f]{12}\.(pdf|doc|docx)$'
            )
            and (
                (detected_media_type = 'application/pdf'
                    and resume_object_path ~ '\.pdf$')
                or (detected_media_type = 'application/msword'
                    and resume_object_path ~ '\.doc$')
                or (
                    detected_media_type =
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                    and resume_object_path ~ '\.docx$'
                )
            )
        ),
    constraint leads_media_type_allowed
        check (
            detected_media_type in (
                'application/pdf',
                'application/msword',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
        ),
    constraint leads_byte_size_in_range
        check (byte_size >= 0 and byte_size <= 10485760),
    constraint leads_status_valid
        check (status in ('PENDING', 'REACHED_OUT')),
    constraint leads_reached_out_audit_coherent
        check (
            (
                status = 'PENDING'
                and reached_out_at is null
                and reached_out_by_user_id is null
                and reached_out_by_email is null
            )
            or (
                status = 'REACHED_OUT'
                and reached_out_at is not null
                and reached_out_by_user_id is not null
                and reached_out_by_email is not null
                and reached_out_by_email = lower(btrim(reached_out_by_email))
                and char_length(reached_out_by_email) between 3 and 320
                and reached_out_by_email
                    ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'
            )
        ),
    constraint leads_updated_after_created
        check (updated_at >= created_at),
    constraint leads_reached_out_after_created
        check (reached_out_at is null or reached_out_at >= created_at),
    constraint leads_resume_object_path_unique unique (resume_object_path)
);

comment on column public.leads.resume_object_path is
    'Caller-generated leads/{lead_id}/{uuid-v4}.{pdf|doc|docx} object name in the private resumes bucket.';
comment on column public.leads.normalized_email is
    'Lowercase, trimmed search form. Duplicate lead emails are intentionally allowed.';

create table public.email_deliveries (
    id uuid primary key default pg_catalog.gen_random_uuid(),
    lead_id uuid not null
        references public.leads (id)
        on update restrict
        on delete restrict,
    delivery_kind varchar(16) not null,
    state varchar(24) not null default 'pending',
    active_attempt_id uuid,
    active_claim_token uuid,
    claimed_at timestamptz,
    claim_expires_at timestamptz,
    retry_count smallint not null default 0,
    last_attempt_at timestamptz,
    recipient varchar(320) not null,
    provider_message_id varchar(255),
    last_error varchar(1000),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint email_deliveries_kind_valid
        check (delivery_kind in ('prospect', 'attorney')),
    constraint email_deliveries_state_valid
        check (
            state in (
                'pending',
                'processing',
                'provider_accepted',
                'failed',
                'unknown'
            )
        ),
    constraint email_deliveries_retry_count_in_range
        check (retry_count between 0 and 5),
    constraint email_deliveries_recipient_normalized
        check (
            char_length(recipient) between 3 and 320
            and recipient = lower(btrim(recipient))
            and recipient ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'
        ),
    constraint email_deliveries_provider_id_sanitized
        check (
            provider_message_id is null
            or (
                char_length(provider_message_id) between 1 and 255
                and provider_message_id !~ '[[:cntrl:]]'
            )
        ),
    constraint email_deliveries_error_sanitized
        check (
            last_error is null
            or (
                char_length(last_error) between 1 and 1000
                and last_error !~ '[[:cntrl:]]'
            )
        ),
    constraint email_deliveries_claim_window_valid
        check (
            claim_expires_at is null
            or (
                claimed_at is not null
                and claim_expires_at > claimed_at
            )
        ),
    constraint email_deliveries_projection_coherent
        check (
            (
                state = 'pending'
                and active_attempt_id is null
                and active_claim_token is null
                and claimed_at is null
                and claim_expires_at is null
                and last_attempt_at is null
                and provider_message_id is null
                and last_error is null
            )
            or (
                state = 'processing'
                and active_attempt_id is not null
                and active_claim_token is not null
                and claimed_at is not null
                and claim_expires_at is not null
                and last_attempt_at = claimed_at
                and provider_message_id is null
                and last_error is null
            )
            or (
                state = 'provider_accepted'
                and active_attempt_id is null
                and active_claim_token is null
                and claimed_at is null
                and claim_expires_at is null
                and last_attempt_at is not null
                and provider_message_id is not null
                and last_error is null
            )
            or (
                state in ('failed', 'unknown')
                and active_attempt_id is null
                and active_claim_token is null
                and claimed_at is null
                and claim_expires_at is null
                and last_attempt_at is not null
                and provider_message_id is null
                and last_error is not null
            )
        ),
    constraint email_deliveries_updated_after_created
        check (updated_at >= created_at),
    constraint email_deliveries_one_per_lead_kind
        unique (lead_id, delivery_kind)
);

create table public.email_delivery_attempts (
    id uuid primary key default pg_catalog.gen_random_uuid(),
    delivery_id uuid not null
        references public.email_deliveries (id)
        on update restrict
        on delete restrict,
    claim_token uuid not null,
    attempt_number smallint not null,
    trigger_kind varchar(16) not null,
    reviewer_user_id uuid,
    reviewer_email varchar(320),
    started_at timestamptz not null,
    ended_at timestamptz,
    http_status smallint,
    provider_message_id varchar(255),
    outcome varchar(24),
    sanitized_error varchar(1000),
    created_at timestamptz not null default now(),
    constraint email_delivery_attempts_claim_token_unique
        unique (claim_token),
    constraint email_delivery_attempts_number_valid
        check (attempt_number between 1 and 6),
    constraint email_delivery_attempts_trigger_valid
        check (trigger_kind in ('initial', 'manual')),
    constraint email_delivery_attempts_trigger_number_coherent
        check (
            (trigger_kind = 'initial' and attempt_number = 1)
            or (trigger_kind = 'manual' and attempt_number between 2 and 6)
        ),
    constraint email_delivery_attempts_reviewer_coherent
        check (
            (reviewer_user_id is null and reviewer_email is null)
            or (
                reviewer_user_id is not null
                and reviewer_email is not null
                and reviewer_email = lower(btrim(reviewer_email))
                and char_length(reviewer_email) between 3 and 320
                and reviewer_email
                    ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'
            )
        ),
    constraint email_delivery_attempts_outcome_valid
        check (
            outcome is null
            or outcome in ('provider_accepted', 'failed', 'unknown')
        ),
    constraint email_delivery_attempts_http_status_valid
        check (http_status is null or http_status between 100 and 599),
    constraint email_delivery_attempts_provider_id_sanitized
        check (
            provider_message_id is null
            or (
                char_length(provider_message_id) between 1 and 255
                and provider_message_id !~ '[[:cntrl:]]'
            )
        ),
    constraint email_delivery_attempts_error_sanitized
        check (
            sanitized_error is null
            or (
                char_length(sanitized_error) between 1 and 1000
                and sanitized_error !~ '[[:cntrl:]]'
            )
        ),
    constraint email_delivery_attempts_completion_coherent
        check (
            (
                ended_at is null
                and http_status is null
                and provider_message_id is null
                and outcome is null
                and sanitized_error is null
            )
            or (
                ended_at is not null
                and ended_at >= started_at
                and (
                    (
                        outcome = 'provider_accepted'
                        and http_status between 200 and 299
                        and provider_message_id is not null
                        and sanitized_error is null
                    )
                    or (
                        outcome in ('failed', 'unknown')
                        and provider_message_id is null
                        and sanitized_error is not null
                    )
                )
            )
        ),
    constraint email_delivery_attempts_created_not_after_start
        check (created_at <= started_at),
    constraint email_delivery_attempts_delivery_number_unique
        unique (delivery_id, attempt_number),
    constraint email_delivery_attempts_identity_for_active_fk
        unique (id, delivery_id, claim_token)
);

alter table public.email_deliveries
    add constraint email_deliveries_active_attempt_identity_fk
    foreign key (active_attempt_id, id, active_claim_token)
    references public.email_delivery_attempts (id, delivery_id, claim_token)
    on update restrict
    on delete restrict
    deferrable initially immediate;

create index leads_created_cursor_idx
    on public.leads (created_at, id);
create index leads_status_created_cursor_idx
    on public.leads (status, created_at, id);
create index leads_email_search_idx
    on public.leads (normalized_email, created_at desc);

create index email_deliveries_created_cursor_idx
    on public.email_deliveries (created_at, id);
create index email_deliveries_state_attempt_idx
    on public.email_deliveries (state, last_attempt_at, id);
create index email_deliveries_lead_idx
    on public.email_deliveries (lead_id, id);
create index email_deliveries_expired_claim_idx
    on public.email_deliveries (claim_expires_at, id)
    where state = 'processing';

create index email_delivery_attempts_created_cursor_idx
    on public.email_delivery_attempts (created_at, id);
create index email_delivery_attempts_delivery_started_idx
    on public.email_delivery_attempts (delivery_id, started_at desc, id);
create index email_delivery_attempts_outcome_started_idx
    on public.email_delivery_attempts (outcome, started_at, id)
    where outcome is not null;
create unique index email_delivery_attempts_one_initial_idx
    on public.email_delivery_attempts (delivery_id)
    where trigger_kind = 'initial';

create or replace function public.set_row_updated_at()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $function$
begin
    new.updated_at := greatest(clock_timestamp(), old.updated_at);
    return new;
end;
$function$;

create trigger daily_email_budgets_set_updated_at
before update on public.daily_email_budgets
for each row execute function public.set_row_updated_at();

create trigger demo_capacity_set_updated_at
before update on public.demo_capacity
for each row execute function public.set_row_updated_at();

create trigger leads_set_updated_at
before update on public.leads
for each row execute function public.set_row_updated_at();

create trigger email_deliveries_set_updated_at
before update on public.email_deliveries
for each row execute function public.set_row_updated_at();

create or replace function public.guard_lead_status_transition()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $function$
begin
    if (
        new.id,
        new.first_name,
        new.last_name,
        new.normalized_email,
        new.resume_object_path,
        new.original_filename,
        new.detected_media_type,
        new.byte_size,
        new.created_at
    ) is distinct from (
        old.id,
        old.first_name,
        old.last_name,
        old.normalized_email,
        old.resume_object_path,
        old.original_filename,
        old.detected_media_type,
        old.byte_size,
        old.created_at
    )
    then
        raise exception using
            errcode = '55000',
            message = 'lead submission identity and resume metadata are immutable';
    end if;

    if old.status = 'REACHED_OUT'
       and (
           new.status,
           new.reached_out_at,
           new.reached_out_by_user_id,
           new.reached_out_by_email
       ) is distinct from (
           old.status,
           old.reached_out_at,
           old.reached_out_by_user_id,
           old.reached_out_by_email
       )
    then
        raise exception using
            errcode = '23514',
            message = 'REACHED_OUT status and audit fields are immutable';
    end if;

    if old.status is distinct from new.status
       and not (old.status = 'PENDING' and new.status = 'REACHED_OUT')
    then
        raise exception using
            errcode = '23514',
            message = 'lead status may transition only from PENDING to REACHED_OUT';
    end if;

    return new;
end;
$function$;

create trigger leads_guard_status_transition
before update on public.leads
for each row execute function public.guard_lead_status_transition();

create or replace function public.reserve_demo_capacity_for_lead()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $function$
begin
    update public.demo_capacity
       set lead_count = lead_count + 1,
           resume_bytes = resume_bytes + new.byte_size
     where singleton
       and lead_count + 1 <= lead_limit
       and resume_bytes + new.byte_size <= resume_byte_limit;

    if not found then
        raise exception using
            errcode = 'P0001',
            message = 'demo lead or resume-byte capacity exhausted';
    end if;

    return new;
end;
$function$;

create trigger leads_reserve_demo_capacity
before insert on public.leads
for each row execute function public.reserve_demo_capacity_for_lead();

create or replace function public.release_demo_capacity_for_lead()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $function$
begin
    update public.demo_capacity
       set lead_count = lead_count - 1,
           resume_bytes = resume_bytes - old.byte_size
     where singleton;
    return old;
end;
$function$;

create trigger leads_release_demo_capacity
after delete on public.leads
for each row execute function public.release_demo_capacity_for_lead();

create or replace function public.guard_email_attempt_history()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $function$
begin
    if tg_op in ('DELETE', 'TRUNCATE') then
        raise exception using
            errcode = '55000',
            message = 'email delivery attempt history cannot be deleted or truncated';
    end if;

    if (
        new.id,
        new.delivery_id,
        new.claim_token,
        new.attempt_number,
        new.trigger_kind,
        new.reviewer_user_id,
        new.reviewer_email,
        new.started_at,
        new.created_at
    ) is distinct from (
        old.id,
        old.delivery_id,
        old.claim_token,
        old.attempt_number,
        old.trigger_kind,
        old.reviewer_user_id,
        old.reviewer_email,
        old.started_at,
        old.created_at
    )
    then
        raise exception using
            errcode = '55000',
            message = 'email delivery attempt claim identity is immutable';
    end if;

    if old.ended_at is not null and new is distinct from old then
        raise exception using
            errcode = '55000',
            message = 'completed email delivery attempts are immutable';
    end if;

    return new;
end;
$function$;

create trigger email_delivery_attempts_guard_update
before update on public.email_delivery_attempts
for each row execute function public.guard_email_attempt_history();

create trigger email_delivery_attempts_prevent_delete
before delete on public.email_delivery_attempts
for each row execute function public.guard_email_attempt_history();

create trigger email_delivery_attempts_prevent_truncate
before truncate on public.email_delivery_attempts
for each statement execute function public.guard_email_attempt_history();

comment on table public.email_delivery_attempts is
    'Append-only claim history. A guarded function permits one completion update.';
