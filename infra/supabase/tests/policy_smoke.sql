\set ON_ERROR_STOP on

begin;

create extension if not exists pgtap with schema extensions;
grant alma_api to postgres;
select extensions.plan(1);

-- A database-only marker proves browser SELECT is filtered by RLS. It is
-- rolled back and never represents a physical Storage object.
insert into storage.objects (bucket_id, name)
values ('resumes', 'policy-smoke/private-marker.pdf');

insert into storage.buckets (id, name, public)
values ('policy-smoke-unrelated', 'policy-smoke-unrelated', false);
insert into storage.objects (bucket_id, name)
values ('policy-smoke-unrelated', 'visible-marker.pdf');
grant usage on schema storage to anon;
grant select on storage.objects to anon;
create policy policy_smoke_unrelated_object_read
on storage.objects
for select
to anon
using (bucket_id = 'policy-smoke-unrelated');

do $test$
declare
    v_attributes record;
begin
    select rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
           rolinherit, rolreplication, rolbypassrls
      into strict v_attributes
      from pg_catalog.pg_roles
     where rolname = 'alma_api';

    if not v_attributes.rolcanlogin
       or v_attributes.rolsuper
       or v_attributes.rolcreatedb
       or v_attributes.rolcreaterole
       or v_attributes.rolinherit
       or v_attributes.rolreplication
       or v_attributes.rolbypassrls
    then
        raise exception 'alma_api role attributes are not least-privilege';
    end if;

    if has_table_privilege('anon', 'public.leads', 'SELECT')
       or has_table_privilege('authenticated', 'public.leads', 'SELECT')
    then
        raise exception 'a browser role has forbidden lead-table privileges';
    end if;

    if not has_table_privilege('alma_api', 'public.leads', 'SELECT')
       or not has_table_privilege(
           'alma_api',
           'public.email_deliveries',
           'SELECT'
       )
       or not has_table_privilege(
           'alma_api',
           'public.email_delivery_attempts',
           'SELECT'
       )
    then
        raise exception 'alma_api is missing an intended read grant';
    end if;

    if has_table_privilege('alma_api', 'public.leads', 'INSERT')
       or has_table_privilege('alma_api', 'public.leads', 'UPDATE')
       or has_table_privilege('alma_api', 'public.leads', 'DELETE')
       or has_table_privilege(
           'alma_api',
           'public.email_deliveries',
           'UPDATE'
       )
       or has_table_privilege(
           'alma_api',
           'public.email_delivery_attempts',
           'UPDATE'
       )
       or has_table_privilege('alma_api', 'storage.objects', 'SELECT')
       or has_table_privilege('alma_api', 'storage.objects', 'INSERT')
    then
        raise exception 'alma_api has a forbidden direct table grant';
    end if;

    if not has_function_privilege(
        'alma_api',
        'public.reserve_new_lead_email_budget(uuid)',
        'EXECUTE'
    ) or not has_function_privilege(
        'alma_api',
        'public.create_lead_with_deliveries(uuid,text,text,text,text,text,text,bigint,text,text)',
        'EXECUTE'
    ) or not has_function_privilege(
        'alma_api',
        'public.claim_email_delivery(uuid,uuid,text,uuid,text,boolean)',
        'EXECUTE'
    ) or has_function_privilege(
        'alma_api',
        'public._reserve_email_budget(uuid,text)',
        'EXECUTE'
    ) then
        raise exception 'alma_api function grants are incorrect';
    end if;

    if to_regprocedure('public.reserve_retry_email_budget(uuid)') is not null then
        raise exception 'retry budget must not be reservable outside manual claim';
    end if;

    if pg_get_function_result(
        'public.claim_email_delivery(uuid,uuid,text,uuid,text,boolean)'::regprocedure
    ) <> 'jsonb'
       or pg_get_function_result(
           'public.complete_email_delivery_attempt(uuid,uuid,text,integer,text,text)'::regprocedure
       ) <> 'jsonb'
       or pg_get_function_result(
           'public.expire_email_delivery_claim(uuid)'::regprocedure
       ) <> 'jsonb'
    then
        raise exception 'API delivery functions must return parseable JSON';
    end if;

    if position(
        'interval ''1 minute''' in pg_get_functiondef(
            'public.claim_email_delivery(uuid,uuid,text,uuid,text,boolean)'::regprocedure
        )
    ) = 0 then
        raise exception 'manual retry cooldown is not exactly one minute';
    end if;

    if has_function_privilege(
        'anon',
        'public.reserve_new_lead_email_budget(uuid)',
        'EXECUTE'
    ) or has_function_privilege(
        'authenticated',
        'public.create_lead_with_deliveries(uuid,text,text,text,text,text,text,bigint,text,text)',
        'EXECUTE'
    ) then
        raise exception 'a browser role can execute an API write function';
    end if;

    if not exists (
        select 1
          from pg_catalog.pg_class
         where oid = 'public.leads'::regclass
           and relrowsecurity
           and relforcerowsecurity
    ) then
        raise exception 'leads RLS is not enabled and forced';
    end if;

    if not exists (
        select 1
          from pg_catalog.pg_policies
         where schemaname = 'storage'
           and tablename = 'objects'
           and policyname = 'alma_resumes_browser_object_deny'
           and permissive = 'RESTRICTIVE'
           and roles @> array['anon', 'authenticated']::name[]
           and qual like '%bucket_id%<>%resumes%'
    ) then
        raise exception 'private resumes restrictive policy is missing';
    end if;
end;
$test$;

create or replace function pg_temp.assert_denied(
    p_role name,
    p_statement text
)
returns void
language plpgsql
as $function$
declare
    v_denied boolean := false;
begin
    execute format('set local role %I', p_role);
    begin
        execute p_statement;
    exception
        when insufficient_privilege then
            v_denied := true;
    end;
    reset role;

    if not v_denied then
        raise exception '% unexpectedly executed: %', p_role, p_statement;
    end if;
end;
$function$;

create or replace function pg_temp.assert_no_visible_rows(
    p_role name,
    p_statement text
)
returns void
language plpgsql
as $function$
declare
    v_visible boolean := false;
    v_denied boolean := false;
begin
    execute format('set local role %I', p_role);
    begin
        execute p_statement into v_visible;
    exception
        when insufficient_privilege then
            v_denied := true;
    end;
    reset role;

    if not v_denied and coalesce(v_visible, false) then
        raise exception '% saw a private row with: %', p_role, p_statement;
    end if;
end;
$function$;

create or replace function pg_temp.assert_visible_rows(
    p_role name,
    p_statement text
)
returns void
language plpgsql
as $function$
declare
    v_visible boolean := false;
begin
    execute format('set local role %I', p_role);
    execute p_statement into v_visible;
    reset role;

    if not coalesce(v_visible, false) then
        raise exception '% could not see an unrelated allowed row with: %',
            p_role,
            p_statement;
    end if;
end;
$function$;

select pg_temp.assert_denied('anon', 'select * from public.leads');
select pg_temp.assert_denied(
    'authenticated',
    'select * from public.email_deliveries'
);
select pg_temp.assert_no_visible_rows(
    'anon',
    'select exists (select 1 from storage.objects where bucket_id = ''resumes'')'
);
select pg_temp.assert_no_visible_rows(
    'authenticated',
    'select exists (select 1 from storage.buckets where id = ''resumes'')'
);
select pg_temp.assert_visible_rows(
    'anon',
    'select exists (select 1 from storage.objects where bucket_id = ''policy-smoke-unrelated'')'
);
select pg_temp.assert_denied(
    'authenticated',
    'insert into storage.objects (bucket_id, name) values (''resumes'', ''forbidden.pdf'')'
);
select pg_temp.assert_denied(
    'alma_api',
    'update public.leads set status = ''REACHED_OUT'''
);
select pg_temp.assert_denied(
    'alma_api',
    'delete from public.email_delivery_attempts'
);

do $test$
declare
    v_lead_id uuid := pg_catalog.gen_random_uuid();
    v_resume_key uuid := pg_catalog.gen_random_uuid();
    v_initial_attempt_id uuid := pg_catalog.gen_random_uuid();
    v_expired_manual_id uuid := pg_catalog.gen_random_uuid();
    v_historical_attempt_id uuid := pg_catalog.gen_random_uuid();
    v_manual_attempt_id uuid := pg_catalog.gen_random_uuid();
    v_reviewer_id uuid := pg_catalog.gen_random_uuid();
    v_prospect_delivery_id uuid;
    v_attorney_delivery_id uuid;
    v_initial_claim_token uuid;
    v_manual_claim_token uuid;
    v_result jsonb;
    v_retry_before integer;
    v_retry_after integer;
    v_attempt_count integer;
    v_status text;
    v_outcome text;
    v_historical_at timestamptz := clock_timestamp() - interval '2 minutes';
begin
    set local role alma_api;

    perform public.reserve_new_lead_email_budget(v_lead_id);
    begin
        perform public.create_lead_with_deliveries(
            v_lead_id,
            'Synthetic',
            'PolicyTest',
            'synthetic.policy@example.invalid',
            format('leads/%s/candidate-original-name.pdf', v_lead_id),
            'candidate-original-name.pdf',
            'application/pdf',
            1024,
            'synthetic.policy@example.invalid',
            'attorney.policy@example.invalid'
        );
        raise exception 'filename-derived object path unexpectedly passed';
    exception
        when invalid_parameter_value then
            if sqlerrm <>
                'resume object path must be leads/{lead_id}/{uuid-v4}.{pdf|doc|docx}'
            then
                raise exception 'unexpected object-path message: %', sqlerrm;
            end if;
    end;

    perform public.create_lead_with_deliveries(
        v_lead_id,
        'Synthetic',
        'PolicyTest',
        'synthetic.policy@example.invalid',
        format('leads/%s/%s.pdf', v_lead_id, v_resume_key),
        'candidate-original-name.pdf',
        'application/pdf',
        1024,
        'synthetic.policy@example.invalid',
        'attorney.policy@example.invalid'
    );

    select id
      into strict v_prospect_delivery_id
      from public.email_deliveries
     where lead_id = v_lead_id
       and delivery_kind = 'prospect';

    select id
      into strict v_attorney_delivery_id
      from public.email_deliveries
     where lead_id = v_lead_id
       and delivery_kind = 'attorney';

    v_result := public.claim_email_delivery(
        v_prospect_delivery_id,
        v_initial_attempt_id,
        'initial',
        null,
        null,
        false
    );
    if v_result ->> 'status' <> 'claimed' then
        raise exception 'initial claim did not return claimed JSON';
    end if;
    v_initial_claim_token := (v_result ->> 'claim_token')::uuid;

    begin
        perform public.claim_email_delivery(
            v_prospect_delivery_id,
            v_expired_manual_id,
            'manual',
            v_reviewer_id,
            'reviewer.policy@example.invalid',
            true
        );
        raise exception 'active lease unexpectedly allowed a manual claim';
    exception
        when lock_not_available then
            if sqlerrm <> 'email delivery claim lease is still active' then
                raise exception 'unexpected active-lease message: %', sqlerrm;
            end if;
    end;

    reset role;
    update public.email_deliveries
       set claimed_at = clock_timestamp() - interval '10 minutes',
           claim_expires_at = clock_timestamp() - interval '5 minutes',
           last_attempt_at = clock_timestamp() - interval '10 minutes'
     where id = v_prospect_delivery_id;
    set local role alma_api;

    v_result := public.claim_email_delivery(
        v_prospect_delivery_id,
        v_expired_manual_id,
        'manual',
        v_reviewer_id,
        'reviewer.policy@example.invalid',
        false
    );
    if v_result ->> 'status' <> 'duplicate_confirmation_required'
       or v_result ->> 'duplicate_risk_reason' <> 'expired_claim'
    then
        raise exception 'expired claim was not recovered before confirmation';
    end if;

    select state
      into strict v_status
      from public.email_deliveries
     where id = v_prospect_delivery_id;
    select outcome
      into strict v_outcome
      from public.email_delivery_attempts
     where id = v_initial_attempt_id;
    if v_status <> 'unknown' or v_outcome <> 'unknown' then
        raise exception 'expired claim recovery was not atomic';
    end if;

    begin
        perform public.claim_email_delivery(
            v_prospect_delivery_id,
            v_expired_manual_id,
            'manual',
            v_reviewer_id,
            'reviewer.policy@example.invalid',
            true
        );
        raise exception 'one-minute cooldown unexpectedly allowed a retry';
    exception
        when object_not_in_prerequisite_state then
            if sqlerrm <> 'manual retry cooldown has not elapsed' then
                raise exception 'unexpected cooldown message: %', sqlerrm;
            end if;
    end;

    reset role;
    insert into public.email_delivery_attempts (
        id,
        delivery_id,
        claim_token,
        attempt_number,
        trigger_kind,
        started_at,
        ended_at,
        outcome,
        sanitized_error,
        created_at
    )
    values (
        v_historical_attempt_id,
        v_attorney_delivery_id,
        pg_catalog.gen_random_uuid(),
        1,
        'initial',
        v_historical_at,
        v_historical_at,
        'unknown',
        'synthetic historical unknown outcome',
        v_historical_at
    );
    update public.email_deliveries
       set state = 'unknown',
           last_attempt_at = v_historical_at,
           last_error = 'synthetic historical unknown outcome'
     where id = v_attorney_delivery_id;
    set local role alma_api;

    v_retry_before :=
        (public.get_current_email_budget() ->> 'retry_credits_used')::integer;

    v_result := public.claim_email_delivery(
        v_attorney_delivery_id,
        v_manual_attempt_id,
        'manual',
        v_reviewer_id,
        'reviewer.policy@example.invalid',
        false
    );
    if v_result ->> 'status' <> 'duplicate_confirmation_required' then
        raise exception 'unknown delivery did not require confirmation';
    end if;

    v_result := public.claim_email_delivery(
        v_attorney_delivery_id,
        v_manual_attempt_id,
        'manual',
        v_reviewer_id,
        'reviewer.policy@example.invalid',
        true
    );
    if v_result ->> 'status' <> 'claimed'
       or (v_result ->> 'retry_count')::integer <> 1
    then
        raise exception 'confirmed manual retry was not claimed';
    end if;
    v_manual_claim_token := (v_result ->> 'claim_token')::uuid;

    v_result := public.claim_email_delivery(
        v_attorney_delivery_id,
        v_manual_attempt_id,
        'manual',
        v_reviewer_id,
        'reviewer.policy@example.invalid',
        true
    );
    if v_result ->> 'status' <> 'existing_attempt' then
        raise exception 'manual claim request key was not idempotent';
    end if;

    v_retry_after :=
        (public.get_current_email_budget() ->> 'retry_credits_used')::integer;
    select count(*)
      into strict v_attempt_count
      from public.email_delivery_attempts
     where delivery_id = v_attorney_delivery_id
       and trigger_kind = 'manual';
    if v_retry_after <> v_retry_before + 1 or v_attempt_count <> 1 then
        raise exception 'manual claim did not reserve exactly one retry credit';
    end if;

    v_result := public.complete_email_delivery_attempt(
        v_manual_attempt_id,
        v_manual_claim_token,
        'provider_accepted',
        202,
        'synthetic-provider-id',
        null
    );
    if v_result ->> 'status' <> 'completed'
       or v_result ->> 'delivery_state' <> 'provider_accepted'
    then
        raise exception 'active attempt was not completed';
    end if;

    v_result := public.complete_email_delivery_attempt(
        v_manual_attempt_id,
        v_manual_claim_token,
        'provider_accepted',
        202,
        'synthetic-provider-id',
        null
    );
    if v_result ->> 'status' <> 'already_completed' then
        raise exception 'completed attempt was not idempotent';
    end if;

    perform public.mark_lead_reached_out(
        v_lead_id,
        v_reviewer_id,
        'reviewer.policy@example.invalid'
    );
    perform public.mark_lead_reached_out(
        v_lead_id,
        v_reviewer_id,
        'reviewer.policy@example.invalid'
    );

    select status
      into strict v_status
      from public.leads
     where id = v_lead_id;
    if v_status <> 'REACHED_OUT' then
        raise exception 'lead transition did not persist through the API function';
    end if;

    reset role;
end;
$test$;

select extensions.pass('AlmaPortal database policies and workflows passed');
select * from extensions.finish();

rollback;

\echo 'AlmaPortal policy smoke tests passed.'
