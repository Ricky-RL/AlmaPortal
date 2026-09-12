-- Transaction boundaries used by the SQLAlchemy API. These routines own all
-- application writes so the runtime role never needs direct table mutation.

-- PostgreSQL grants EXECUTE on new functions to PUBLIC by default. Change the
-- creator's default before any SECURITY DEFINER routine exists so there is no
-- exposure window between this migration and the explicit grants migration.
alter default privileges in schema public
    revoke execute on functions from public;

create or replace function public._reserve_email_budget(
    p_reservation_key uuid,
    p_reservation_kind text
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $function$
declare
    v_budget_date date := (clock_timestamp() at time zone 'UTC')::date;
    v_credits integer;
    v_existing public.email_budget_reservations%rowtype;
    v_remaining integer;
begin
    if p_reservation_key is null then
        raise exception using
            errcode = '22004',
            message = 'reservation key is required';
    end if;

    if p_reservation_kind = 'new_lead' then
        v_credits := 2;
    elsif p_reservation_kind = 'retry' then
        v_credits := 1;
    else
        raise exception using
            errcode = '22023',
            message = 'unsupported email budget reservation kind';
    end if;

    -- A transaction-scoped lock makes repeated calls with the same request key
    -- idempotent even when they arrive concurrently.
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(p_reservation_key::text, 0)
    );

    select *
      into v_existing
      from public.email_budget_reservations
     where reservation_key = p_reservation_key;

    if found then
        if v_existing.reservation_kind <> p_reservation_kind then
            raise exception using
                errcode = '23505',
                message = 'reservation key is already used for another budget kind';
        end if;

        select case
                   when p_reservation_kind = 'new_lead'
                       then new_lead_credit_limit - new_lead_credits_used
                   else retry_credit_limit - retry_credits_used
               end
          into v_remaining
          from public.daily_email_budgets
         where budget_date = v_existing.budget_date;

        return jsonb_build_object(
            'reservation_key', p_reservation_key,
            'budget_date', v_existing.budget_date,
            'kind', p_reservation_kind,
            'credits', v_existing.credits,
            'remaining_credits', v_remaining,
            'already_reserved', true
        );
    end if;

    insert into public.daily_email_budgets (budget_date)
    values (v_budget_date)
    on conflict (budget_date) do nothing;

    if p_reservation_kind = 'new_lead' then
        update public.daily_email_budgets
           set new_lead_credits_used = new_lead_credits_used + v_credits
         where budget_date = v_budget_date
           and new_lead_credits_used + v_credits <= new_lead_credit_limit
        returning new_lead_credit_limit - new_lead_credits_used
             into v_remaining;
    else
        update public.daily_email_budgets
           set retry_credits_used = retry_credits_used + v_credits
         where budget_date = v_budget_date
           and retry_credits_used + v_credits <= retry_credit_limit
        returning retry_credit_limit - retry_credits_used
             into v_remaining;
    end if;

    if not found then
        raise exception using
            errcode = 'P0001',
            message = format(
                'UTC daily %s email budget is exhausted',
                p_reservation_kind
            );
    end if;

    insert into public.email_budget_reservations (
        reservation_key,
        budget_date,
        reservation_kind,
        credits
    )
    values (
        p_reservation_key,
        v_budget_date,
        p_reservation_kind,
        v_credits
    );

    return jsonb_build_object(
        'reservation_key', p_reservation_key,
        'budget_date', v_budget_date,
        'kind', p_reservation_kind,
        'credits', v_credits,
        'remaining_credits', v_remaining,
        'already_reserved', false
    );
end;
$function$;

create or replace function public.reserve_new_lead_email_budget(
    p_reservation_key uuid
)
returns jsonb
language sql
security definer
set search_path = pg_catalog, public
as $function$
    select public._reserve_email_budget(p_reservation_key, 'new_lead');
$function$;

create or replace function public.get_current_email_budget()
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog, public
as $function$
    select coalesce(
        (
            select jsonb_build_object(
                'budget_date', budget_date,
                'new_lead_credit_limit', new_lead_credit_limit,
                'new_lead_credits_used', new_lead_credits_used,
                'new_lead_credits_remaining',
                    new_lead_credit_limit - new_lead_credits_used,
                'retry_credit_limit', retry_credit_limit,
                'retry_credits_used', retry_credits_used,
                'retry_credits_remaining',
                    retry_credit_limit - retry_credits_used
            )
            from public.daily_email_budgets
            where budget_date =
                (statement_timestamp() at time zone 'UTC')::date
        ),
        jsonb_build_object(
            'budget_date', (statement_timestamp() at time zone 'UTC')::date,
            'new_lead_credit_limit', 80,
            'new_lead_credits_used', 0,
            'new_lead_credits_remaining', 80,
            'retry_credit_limit', 20,
            'retry_credits_used', 0,
            'retry_credits_remaining', 20
        )
    );
$function$;

create or replace function public.get_demo_capacity()
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog, public
as $function$
    select jsonb_build_object(
        'lead_limit', lead_limit,
        'lead_count', lead_count,
        'lead_slots_remaining', lead_limit - lead_count,
        'resume_byte_limit', resume_byte_limit,
        'resume_bytes', resume_bytes,
        'resume_bytes_remaining', resume_byte_limit - resume_bytes
    )
    from public.demo_capacity
    where singleton;
$function$;

create or replace function public.create_lead_with_deliveries(
    p_lead_id uuid,
    p_first_name text,
    p_last_name text,
    p_normalized_email text,
    p_resume_object_path text,
    p_original_filename text,
    p_detected_media_type text,
    p_byte_size bigint,
    p_prospect_recipient text,
    p_attorney_recipient text
)
returns public.leads
language plpgsql
security definer
set search_path = pg_catalog, public
as $function$
declare
    v_now timestamptz := clock_timestamp();
    v_lead public.leads%rowtype;
begin
    if p_lead_id is null then
        raise exception using
            errcode = '22004',
            message = 'lead ID is required before budget reservation and upload';
    end if;

    if p_resume_object_path is null
       or char_length(p_resume_object_path) not between 83 and 84
       or p_resume_object_path !~ (
           '^leads/'
           || p_lead_id::text
           || '/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-'
           || '[89ab][0-9a-f]{3}-[0-9a-f]{12}\.(pdf|doc|docx)$'
       )
    then
        raise exception using
            errcode = '22023',
            message = 'resume object path must be leads/{lead_id}/{uuid-v4}.{pdf|doc|docx}';
    end if;

    if p_detected_media_type is null
       or not (
        (btrim(p_detected_media_type) = 'application/pdf'
            and p_resume_object_path ~ '\.pdf$')
        or (btrim(p_detected_media_type) = 'application/msword'
            and p_resume_object_path ~ '\.doc$')
        or (
            btrim(p_detected_media_type) =
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            and p_resume_object_path ~ '\.docx$'
        )
    ) then
        raise exception using
            errcode = '22023',
            message = 'resume object path extension does not match detected media type';
    end if;

    if not exists (
        select 1
          from public.email_budget_reservations
         where reservation_key = p_lead_id
           and reservation_kind = 'new_lead'
           and created_at >= v_now - interval '1 hour'
    ) then
        raise exception using
            errcode = 'P0001',
            message = 'a recent two-credit new-lead reservation is required';
    end if;

    insert into public.leads (
        id,
        first_name,
        last_name,
        normalized_email,
        resume_object_path,
        original_filename,
        detected_media_type,
        byte_size,
        created_at,
        updated_at
    )
    values (
        p_lead_id,
        btrim(p_first_name),
        btrim(p_last_name),
        lower(btrim(p_normalized_email)),
        btrim(p_resume_object_path),
        btrim(p_original_filename),
        btrim(p_detected_media_type),
        p_byte_size,
        v_now,
        v_now
    )
    returning * into v_lead;

    insert into public.email_deliveries (
        lead_id,
        delivery_kind,
        recipient,
        created_at,
        updated_at
    )
    values
        (
            p_lead_id,
            'prospect',
            lower(btrim(p_prospect_recipient)),
            v_now,
            v_now
        ),
        (
            p_lead_id,
            'attorney',
            lower(btrim(p_attorney_recipient)),
            v_now,
            v_now
        );

    return v_lead;
end;
$function$;

create or replace function public.mark_lead_reached_out(
    p_lead_id uuid,
    p_reviewer_user_id uuid,
    p_reviewer_email text
)
returns public.leads
language plpgsql
security definer
set search_path = pg_catalog, public
as $function$
declare
    v_lead public.leads%rowtype;
    v_now timestamptz := clock_timestamp();
begin
    if p_reviewer_user_id is null or nullif(btrim(p_reviewer_email), '') is null then
        raise exception using
            errcode = '22004',
            message = 'reviewer ID and email are required';
    end if;

    select *
      into v_lead
      from public.leads
     where id = p_lead_id
     for update;

    if not found then
        raise exception using
            errcode = 'P0002',
            message = 'lead not found';
    end if;

    if v_lead.status = 'REACHED_OUT' then
        return v_lead;
    end if;

    update public.leads
       set status = 'REACHED_OUT',
           reached_out_at = v_now,
           reached_out_by_user_id = p_reviewer_user_id,
           reached_out_by_email = lower(btrim(p_reviewer_email))
     where id = p_lead_id
    returning * into v_lead;

    return v_lead;
end;
$function$;

create or replace function public.claim_email_delivery(
    p_delivery_id uuid,
    p_attempt_id uuid,
    p_trigger_kind text,
    p_reviewer_user_id uuid default null,
    p_reviewer_email text default null,
    p_duplicate_risk_confirmed boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $function$
declare
    v_delivery public.email_deliveries%rowtype;
    v_attempt public.email_delivery_attempts%rowtype;
    v_previous_ended_at timestamptz;
    v_now timestamptz := clock_timestamp();
    v_claim_token uuid := pg_catalog.gen_random_uuid();
    v_attempt_number smallint;
    v_retry_available_at timestamptz;
    v_expired_attempt_id uuid;
    v_recovered_expired_claim boolean := false;
    v_expiration_error constant text :=
        'claim expired before a confirmed provider outcome';
begin
    if p_delivery_id is null or p_attempt_id is null then
        raise exception using
            errcode = '22004',
            message = 'delivery ID and caller-generated attempt ID are required';
    end if;

    if p_trigger_kind is null
       or p_trigger_kind not in ('initial', 'manual')
    then
        raise exception using
            errcode = '22023',
            message = 'trigger kind must be initial or manual';
    end if;

    select *
      into v_delivery
      from public.email_deliveries
     where id = p_delivery_id
     for update;

    if not found then
        raise exception using
            errcode = 'P0002',
            message = 'email delivery not found';
    end if;

    select *
      into v_attempt
      from public.email_delivery_attempts
     where id = p_attempt_id;

    if found then
        if v_attempt.delivery_id <> p_delivery_id
           or v_attempt.trigger_kind <> p_trigger_kind
        then
            raise exception using
                errcode = '23505',
                message = 'attempt ID is already used for another claim';
        end if;
        return jsonb_build_object(
            'status', 'existing_attempt',
            'delivery_id', v_delivery.id,
            'delivery_kind', v_delivery.delivery_kind,
            'delivery_state', v_delivery.state,
            'recipient', v_delivery.recipient,
            'attempt_id', v_attempt.id,
            'claim_token', v_attempt.claim_token,
            'attempt_number', v_attempt.attempt_number,
            'trigger_kind', v_attempt.trigger_kind,
            'started_at', v_attempt.started_at,
            'claim_expires_at', v_delivery.claim_expires_at,
            'retry_count', v_delivery.retry_count,
            'outcome', v_attempt.outcome
        );
    end if;

    if p_trigger_kind = 'initial'
       and (p_reviewer_user_id is not null or p_reviewer_email is not null)
    then
        raise exception using
            errcode = '22023',
            message = 'initial attempts cannot include reviewer attribution';
    end if;

    if p_trigger_kind = 'manual'
       and (p_reviewer_user_id is null or p_reviewer_email is null)
    then
        raise exception using
            errcode = '22004',
            message = 'manual attempts require reviewer ID and email';
    end if;

    if p_trigger_kind = 'initial' then
        if v_delivery.state <> 'pending'
           or v_delivery.retry_count <> 0
           or exists (
               select 1
                 from public.email_delivery_attempts
                where delivery_id = p_delivery_id
           )
        then
            raise exception using
                errcode = '55000',
                message = 'initial delivery claim is no longer available';
        end if;
        v_attempt_number := 1;
    elsif p_trigger_kind = 'manual' then
        if v_delivery.state = 'processing' then
            if v_delivery.claim_expires_at > v_now then
                raise exception using
                    errcode = '55P03',
                    message = 'email delivery claim lease is still active';
            end if;

            v_expired_attempt_id := v_delivery.active_attempt_id;

            update public.email_delivery_attempts
               set ended_at = v_now,
                   outcome = 'unknown',
                   sanitized_error = v_expiration_error
             where id = v_delivery.active_attempt_id
               and claim_token = v_delivery.active_claim_token
               and ended_at is null;

            if not found then
                raise exception using
                    errcode = '55000',
                    message = 'expired email delivery claim identity is inconsistent';
            end if;

            update public.email_deliveries
               set state = 'unknown',
                   active_attempt_id = null,
                   active_claim_token = null,
                   claimed_at = null,
                   claim_expires_at = null,
                   provider_message_id = null,
                   last_error = v_expiration_error
             where id = p_delivery_id
            returning * into v_delivery;

            v_recovered_expired_claim := true;
        end if;

        if v_delivery.state not in ('failed', 'unknown') then
            raise exception using
                errcode = '55000',
                message = 'manual retry requires a failed or unknown delivery';
        end if;

        if v_delivery.state = 'unknown'
           and p_duplicate_risk_confirmed is not true
        then
            return jsonb_build_object(
                'status', 'duplicate_confirmation_required',
                'delivery_id', v_delivery.id,
                'delivery_kind', v_delivery.delivery_kind,
                'delivery_state', v_delivery.state,
                'recipient', v_delivery.recipient,
                'expired_attempt_id', v_expired_attempt_id,
                'retry_count', v_delivery.retry_count,
                'duplicate_risk', true,
                'duplicate_risk_reason', case
                    when v_recovered_expired_claim then 'expired_claim'
                    else 'unknown_outcome'
                end
            );
        end if;

        if v_delivery.retry_count >= 5 then
            if v_recovered_expired_claim then
                return jsonb_build_object(
                    'status', 'retry_limit_exhausted',
                    'delivery_id', v_delivery.id,
                    'delivery_kind', v_delivery.delivery_kind,
                    'delivery_state', v_delivery.state,
                    'expired_attempt_id', v_expired_attempt_id,
                    'retry_count', v_delivery.retry_count
                );
            end if;

            raise exception using
                errcode = '54000',
                message = 'manual retry limit of five is exhausted';
        end if;

        select ended_at
          into v_previous_ended_at
          from public.email_delivery_attempts
         where delivery_id = p_delivery_id
         order by attempt_number desc
         limit 1;

        v_retry_available_at := greatest(
            v_delivery.last_attempt_at,
            coalesce(v_previous_ended_at, v_delivery.last_attempt_at)
        ) + interval '1 minute';

        if v_now < v_retry_available_at then
            if v_recovered_expired_claim then
                return jsonb_build_object(
                    'status', 'cooldown',
                    'delivery_id', v_delivery.id,
                    'delivery_kind', v_delivery.delivery_kind,
                    'delivery_state', v_delivery.state,
                    'expired_attempt_id', v_expired_attempt_id,
                    'retry_count', v_delivery.retry_count,
                    'retry_available_at', v_retry_available_at,
                    'duplicate_risk', true
                );
            end if;

            raise exception using
                errcode = '55000',
                message = 'manual retry cooldown has not elapsed';
        end if;

        perform public._reserve_email_budget(p_attempt_id, 'retry');
        v_attempt_number := (v_delivery.retry_count + 2)::smallint;
    end if;

    insert into public.email_delivery_attempts (
        id,
        delivery_id,
        claim_token,
        attempt_number,
        trigger_kind,
        reviewer_user_id,
        reviewer_email,
        started_at,
        created_at
    )
    values (
        p_attempt_id,
        p_delivery_id,
        v_claim_token,
        v_attempt_number,
        p_trigger_kind,
        p_reviewer_user_id,
        case
            when p_reviewer_email is null then null
            else lower(btrim(p_reviewer_email))
        end,
        v_now,
        v_now
    )
    returning * into v_attempt;

    update public.email_deliveries
       set state = 'processing',
           active_attempt_id = p_attempt_id,
           active_claim_token = v_claim_token,
           claimed_at = v_now,
           claim_expires_at = v_now + interval '5 minutes',
           retry_count = case
               when p_trigger_kind = 'manual' then retry_count + 1
               else retry_count
           end,
           last_attempt_at = v_now,
           provider_message_id = null,
           last_error = null
     where id = p_delivery_id
    returning * into v_delivery;

    return jsonb_build_object(
        'status', 'claimed',
        'delivery_id', v_delivery.id,
        'delivery_kind', v_delivery.delivery_kind,
        'delivery_state', v_delivery.state,
        'recipient', v_delivery.recipient,
        'attempt_id', v_attempt.id,
        'claim_token', v_attempt.claim_token,
        'attempt_number', v_attempt.attempt_number,
        'trigger_kind', v_attempt.trigger_kind,
        'started_at', v_attempt.started_at,
        'claim_expires_at', v_delivery.claim_expires_at,
        'retry_count', v_delivery.retry_count,
        'duplicate_risk_confirmed',
            coalesce(p_duplicate_risk_confirmed, false)
    );
end;
$function$;

create or replace function public.complete_email_delivery_attempt(
    p_attempt_id uuid,
    p_claim_token uuid,
    p_outcome text,
    p_http_status integer default null,
    p_provider_message_id text default null,
    p_sanitized_error text default null
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $function$
declare
    v_delivery_id uuid;
    v_delivery public.email_deliveries%rowtype;
    v_attempt public.email_delivery_attempts%rowtype;
    v_now timestamptz := clock_timestamp();
begin
    if p_attempt_id is null or p_claim_token is null then
        raise exception using
            errcode = '22004',
            message = 'attempt ID and claim token are required';
    end if;

    select delivery_id
      into v_delivery_id
      from public.email_delivery_attempts
     where id = p_attempt_id;

    if not found then
        raise exception using
            errcode = 'P0002',
            message = 'email delivery attempt not found';
    end if;

    select *
      into v_delivery
      from public.email_deliveries
     where id = v_delivery_id
     for update;

    select *
      into v_attempt
      from public.email_delivery_attempts
     where id = p_attempt_id
     for update;

    if v_attempt.claim_token <> p_claim_token then
        return jsonb_build_object(
            'status', 'stale_claim',
            'delivery_id', v_delivery.id,
            'delivery_state', v_delivery.state,
            'attempt_id', v_attempt.id,
            'active_attempt_id', v_delivery.active_attempt_id
        );
    end if;

    if v_attempt.ended_at is not null then
        return jsonb_build_object(
            'status', 'already_completed',
            'delivery_id', v_delivery.id,
            'delivery_state', v_delivery.state,
            'attempt_id', v_attempt.id,
            'attempt_outcome', v_attempt.outcome,
            'ended_at', v_attempt.ended_at,
            'provider_message_id', v_attempt.provider_message_id,
            'sanitized_error', v_attempt.sanitized_error
        );
    end if;

    if v_delivery.state <> 'processing'
       or v_delivery.active_attempt_id <> p_attempt_id
       or v_delivery.active_claim_token <> p_claim_token
    then
        return jsonb_build_object(
            'status', 'stale_claim',
            'delivery_id', v_delivery.id,
            'delivery_state', v_delivery.state,
            'attempt_id', v_attempt.id,
            'active_attempt_id', v_delivery.active_attempt_id
        );
    end if;

    if p_outcome is null
       or p_outcome not in ('provider_accepted', 'failed', 'unknown')
    then
        raise exception using
            errcode = '22023',
            message = 'unsupported email attempt outcome';
    end if;

    update public.email_delivery_attempts
       set ended_at = v_now,
           http_status = p_http_status,
           provider_message_id = nullif(btrim(p_provider_message_id), ''),
           outcome = p_outcome,
           sanitized_error = nullif(btrim(p_sanitized_error), '')
     where id = p_attempt_id
    returning * into v_attempt;

    update public.email_deliveries
       set state = p_outcome,
           active_attempt_id = null,
           active_claim_token = null,
           claimed_at = null,
           claim_expires_at = null,
           provider_message_id = case
               when p_outcome = 'provider_accepted'
                   then nullif(btrim(p_provider_message_id), '')
               else null
           end,
           last_error = case
               when p_outcome in ('failed', 'unknown')
                   then nullif(btrim(p_sanitized_error), '')
               else null
           end
     where id = v_delivery_id
    returning * into v_delivery;

    return jsonb_build_object(
        'status', 'completed',
        'delivery_id', v_delivery.id,
        'delivery_kind', v_delivery.delivery_kind,
        'delivery_state', v_delivery.state,
        'attempt_id', v_attempt.id,
        'attempt_outcome', v_attempt.outcome,
        'ended_at', v_attempt.ended_at,
        'http_status', v_attempt.http_status,
        'provider_message_id', v_attempt.provider_message_id,
        'sanitized_error', v_attempt.sanitized_error
    );
end;
$function$;

create or replace function public.expire_email_delivery_claim(
    p_delivery_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $function$
declare
    v_delivery public.email_deliveries%rowtype;
    v_now timestamptz := clock_timestamp();
    v_expired_attempt_id uuid;
    v_expiration_error constant text :=
        'claim expired before a confirmed provider outcome';
begin
    select *
      into v_delivery
      from public.email_deliveries
     where id = p_delivery_id
     for update;

    if not found then
        raise exception using
            errcode = 'P0002',
            message = 'email delivery not found';
    end if;

    if v_delivery.state <> 'processing' then
        return jsonb_build_object(
            'status', 'not_processing',
            'delivery_id', v_delivery.id,
            'delivery_state', v_delivery.state,
            'retry_count', v_delivery.retry_count
        );
    end if;

    if v_delivery.claim_expires_at > v_now then
        return jsonb_build_object(
            'status', 'active_lease',
            'delivery_id', v_delivery.id,
            'delivery_state', v_delivery.state,
            'active_attempt_id', v_delivery.active_attempt_id,
            'claim_expires_at', v_delivery.claim_expires_at,
            'retry_count', v_delivery.retry_count
        );
    end if;

    v_expired_attempt_id := v_delivery.active_attempt_id;

    update public.email_delivery_attempts
       set ended_at = v_now,
           outcome = 'unknown',
           sanitized_error = v_expiration_error
     where id = v_delivery.active_attempt_id
       and claim_token = v_delivery.active_claim_token
       and ended_at is null;

    if not found then
        raise exception using
            errcode = '55000',
            message = 'expired email delivery claim identity is inconsistent';
    end if;

    update public.email_deliveries
       set state = 'unknown',
           active_attempt_id = null,
           active_claim_token = null,
           claimed_at = null,
           claim_expires_at = null,
           provider_message_id = null,
           last_error = v_expiration_error
     where id = p_delivery_id
    returning * into v_delivery;

    return jsonb_build_object(
        'status', 'expired_to_unknown',
        'delivery_id', v_delivery.id,
        'delivery_kind', v_delivery.delivery_kind,
        'delivery_state', v_delivery.state,
        'expired_attempt_id', v_expired_attempt_id,
        'retry_count', v_delivery.retry_count,
        'duplicate_risk', true,
        'last_error', v_delivery.last_error
    );
end;
$function$;

comment on function public.reserve_new_lead_email_budget(uuid) is
    'Idempotently consumes two UTC daily lead-message credits before upload. P0001 means exhausted; 22004 means the key is missing.';
comment on function public._reserve_email_budget(uuid, text) is
    'Internal reservation primitive. Retry credits are consumed only by claim_email_delivery in the manual claim transaction.';
comment on function public.create_lead_with_deliveries(
    uuid, text, text, text, text, text, text, bigint, text, text
) is
    'Creates a lead and both delivery projections. 22023 identifies an invalid random object path; P0001 identifies a missing/expired reservation.';
comment on function public.claim_email_delivery(
    uuid, uuid, text, uuid, text, boolean
) is
    'Returns claimed, existing_attempt, duplicate_confirmation_required, cooldown, or retry_limit_exhausted JSON. 22004/22023 identify invalid required/initial reviewer attribution; 55P03 means active lease; 55000 means invalid state/cooldown; 54000 means retry cap; P0002 means missing delivery; 23505 means reused attempt ID.';
comment on function public.complete_email_delivery_attempt(
    uuid, uuid, text, integer, text, text
) is
    'Returns completed, already_completed, or stale_claim JSON. 22004 means missing identity; 22023 means invalid outcome; P0002 means missing attempt.';
comment on function public.expire_email_delivery_claim(uuid) is
    'Separate-transaction recovery boundary returning durable expired_to_unknown, active_lease, or not_processing JSON. Later unknown claims require duplicate-risk confirmation and cooldown. P0002 means missing delivery; 55000 means inconsistent active claim identity.';
