-- Optional lead comments. Empty or whitespace-only values persist as null.
-- Newlines and tabs are allowed; other control characters are rejected.

alter table public.leads
    add column comments varchar(2000);

alter table public.leads
    add constraint leads_comments_bounded
        check (
            comments is null
            or (
                char_length(comments) between 1 and 2000
                and comments = btrim(comments)
                and comments !~ E'[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F\\x7F]'
            )
        );

comment on column public.leads.comments is
    'Optional submitter notes. Null when omitted or blank. Immutable after insert.';

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
        new.comments,
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
        old.comments,
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

drop function if exists public.create_lead_with_deliveries(
    uuid, text, text, text, text, text, text, bigint, text, text
);

create function public.create_lead_with_deliveries(
    p_lead_id uuid,
    p_first_name text,
    p_last_name text,
    p_normalized_email text,
    p_resume_object_path text,
    p_original_filename text,
    p_detected_media_type text,
    p_byte_size bigint,
    p_prospect_recipient text,
    p_attorney_recipient text,
    p_comments text default null
)
returns public.leads
language plpgsql
security definer
set search_path = pg_catalog, public
as $function$
declare
    v_now timestamptz := clock_timestamp();
    v_lead public.leads%rowtype;
    v_comments text := nullif(btrim(coalesce(p_comments, '')), '');
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
        comments,
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
        v_comments,
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

revoke all on function public.create_lead_with_deliveries(
    uuid, text, text, text, text, text, text, bigint, text, text, text
) from public, anon, authenticated, alma_api;

grant execute on function public.create_lead_with_deliveries(
    uuid, text, text, text, text, text, text, bigint, text, text, text
) to alma_api;

comment on function public.create_lead_with_deliveries(
    uuid, text, text, text, text, text, text, bigint, text, text, text
) is
    'Creates a lead and both delivery projections. Optional p_comments is stored as null when blank.';
