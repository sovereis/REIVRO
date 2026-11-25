begin;

-- Keep the original run, evidence constraints and visibility. Ownership metadata
-- is private even to users who can read the run through the existing RPC.
create table reivro_cloud.execution_leases (
    project_id uuid not null,
    run_id uuid not null,
    state text not null default 'pending'
        check (state in ('pending', 'running', 'completed', 'retryable', 'terminal')),
    fence integer not null default 0 check (fence between 0 and 3),
    attempt_id uuid,
    lease_until timestamptz,
    attempt_until timestamptz,
    primary key (project_id, run_id),
    foreign key (project_id, run_id) references reivro_cloud.runs(project_id, id),
    check ((state = 'running') = (attempt_id is not null)),
    check ((state = 'running') = (lease_until is not null)),
    check ((state = 'running') = (attempt_until is not null)),
    check (lease_until <= attempt_until)
);
alter table reivro_cloud.execution_leases enable row level security;
revoke all on reivro_cloud.execution_leases from public, anon, authenticated, service_role;

alter function reivro_cloud.dispatch(text,jsonb) rename to dispatch_v1;
revoke all on function reivro_cloud.dispatch_v1(text,jsonb) from public, anon, authenticated, service_role;

create function reivro_cloud.dispatch(action text, request jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    actor_id uuid := auth.uid();
    project reivro_cloud.projects%rowtype;
    run reivro_cloud.runs%rowtype;
    lease reivro_cloud.execution_leases%rowtype;
    stored jsonb;
    phase text;
    delivery_id uuid;
    clock_now timestamptz;
    event_kind text;
begin
    if action is null or action not in (
        'reserve_durable','claim_durable','renew_durable','finish_durable','fail_durable','finish'
    ) then
        return reivro_cloud.dispatch_v1(action, request);
    end if;
    if actor_id is null or auth.jwt()->>'is_anonymous' = 'true'
        or coalesce(octet_length(request::text), 0) not between 2 and 524288
        or jsonb_typeof(request) is distinct from 'object' then
        raise insufficient_privilege using message = 'Denied execution operation';
    end if;
    -- Same lock order as v1, including review and revocation operations.
    select p.* into project from reivro_cloud.projects p
        join reivro_cloud.memberships m on m.project_id = p.id
        where p.repository_id = (request->>'repository_id')::bigint
          and p.installation_id = (request->>'installation_id')::bigint
          and m.user_id = actor_id and m.role = 'worker'
        for share of m;
    if not found then
        raise insufficient_privilege using message = 'Denied execution operation';
    end if;
    select p.* into project from reivro_cloud.projects p
        where p.id = project.id and p.repository_id = (request->>'repository_id')::bigint
          and p.installation_id = (request->>'installation_id')::bigint
        for update;
    if not found then
        raise insufficient_privilege using message = 'Denied execution scope';
    end if;
    clock_now := clock_timestamp();

    if action in ('reserve_durable','claim_durable') then
        if request->>'repository' is distinct from project.repository
            or request->>'base_ref' is distinct from project.trusted_base then
            raise insufficient_privilege using message = 'Denied execution repository or base';
        end if;
        delivery_id := (request->>'delivery')::uuid;
        if delivery_id is null or coalesce(request->>'base_sha', '') !~ '^[0-9a-f]{40}$'
            or coalesce(request->>'head_sha', '') !~ '^[0-9a-f]{40}$'
            or coalesce((request->>'pr')::integer, 0) <= 0 then
            raise invalid_parameter_value using message = 'Invalid execution revision';
        end if;
        if exists (select from reivro_cloud.runs r where r.project_id = project.id
            and r.delivery = delivery_id and (r.pr, r.base_sha, r.head_sha) is distinct from
                ((request->>'pr')::integer, request->>'base_sha', request->>'head_sha')) then
            raise invalid_parameter_value using message = 'Delivery revision conflict';
        end if;
        select r.* into run from reivro_cloud.runs r where r.project_id = project.id
            and (r.pr, r.base_sha, r.head_sha) =
                ((request->>'pr')::integer, request->>'base_sha', request->>'head_sha');
        if not found then
            stored := reivro_cloud.dispatch_v1('claim', request);
            select r.* into strict run from reivro_cloud.runs r
                where r.project_id = project.id and r.id = (stored->>'run_id')::uuid;
        end if;
        if run.outcome is not null then
            phase := case when run.outcome = 'ERROR' then 'terminal' else 'completed' end;
            return jsonb_build_object('state', phase, 'run_id', run.id, 'outcome', run.outcome);
        end if;
        insert into reivro_cloud.execution_leases(project_id, run_id) values (project.id, run.id)
            on conflict do nothing;
        select l.* into strict lease from reivro_cloud.execution_leases l
            where l.project_id = project.id and l.run_id = run.id;
        if action = 'reserve_durable' then
            return jsonb_build_object('state', lease.state, 'run_id', run.id);
        end if;
        if lease.state = 'running' and lease.lease_until > clock_now then
            return jsonb_build_object('state', 'busy', 'run_id', run.id);
        end if;
        if lease.fence < 3 then
            update reivro_cloud.runs set worker = actor_id
                where project_id = project.id and id = run.id;
            update reivro_cloud.execution_leases set state = 'running', fence = fence + 1,
                attempt_id = gen_random_uuid(), lease_until = clock_now + interval '60 seconds',
                attempt_until = clock_now + interval '120 seconds'
                where project_id = project.id and run_id = run.id returning * into lease;
            insert into reivro_cloud.events(project_id, actor, kind, subject, data)
                values (project.id, actor_id, 'lease_claim', run.id,
                        jsonb_build_object('fence', lease.fence));
            return jsonb_build_object('state', 'running', 'run_id', run.id,
                'attempt_id', lease.attempt_id, 'fence', lease.fence,
                'protection_id', run.protection_id, 'artifact_digest',
                (select p.digest from reivro_cloud.protections p
                 where p.project_id = project.id and p.id = run.protection_id));
        end if;
        event_kind := 'lease_exhausted';
    else
        select r.* into run from reivro_cloud.runs r where r.project_id = project.id
            and r.id = (request->>'run_id')::uuid and r.worker = actor_id and r.outcome is null;
        if not found then
            raise insufficient_privilege using message = 'Denied or completed execution';
        end if;
        select l.* into lease from reivro_cloud.execution_leases l
            where l.project_id = project.id and l.run_id = run.id;
        if action = 'finish' and not found then
            return reivro_cloud.dispatch_v1(action, request);
        end if;
        if not found or action = 'finish' or lease.state <> 'running'
            or lease.lease_until <= clock_now
            or lease.attempt_id is distinct from (request->>'attempt_id')::uuid
            or lease.fence is distinct from (request->>'fence')::integer then
            raise insufficient_privilege using message = 'Execution lease lost';
        end if;

        if action = 'renew_durable' then
            update reivro_cloud.execution_leases
                set lease_until = greatest(lease_until, least(attempt_until, clock_now + interval '60 seconds'))
                where project_id = project.id and run_id = run.id;
            return jsonb_build_object('state', 'running', 'run_id', run.id);
        end if;
        if action = 'finish_durable' then
            if request->'report'->>'status' = 'ERROR' then
                raise invalid_parameter_value using message = 'Execution errors require failure transition';
            end if;
            stored := reivro_cloud.dispatch_v1('finish', request);
            if lease.lease_until <= clock_timestamp() then
                raise insufficient_privilege using message = 'Execution lease lost during finish';
            end if;
            phase := 'completed';
            event_kind := 'lease_complete';
        else
            phase := case when lease.fence < 3 then 'retryable' else 'terminal' end;
            event_kind := 'lease_failure';
        end if;
    end if;

    if phase is null or phase = 'terminal' then
        phase := 'terminal';
        stored := jsonb_build_object('outcome', 'ERROR');
        update reivro_cloud.runs set outcome = 'ERROR' where project_id = project.id and id = run.id;
    end if;
    update reivro_cloud.execution_leases set state = phase, attempt_id = null,
        lease_until = null, attempt_until = null where project_id = project.id and run_id = run.id;
    insert into reivro_cloud.events(project_id, actor, kind, subject, data)
        values (project.id, actor_id, event_kind, run.id,
                jsonb_build_object('state', phase, 'fence', lease.fence));
    return coalesce(stored, '{}'::jsonb) || jsonb_build_object('state', phase, 'run_id', run.id);
end
$$;

revoke all on function reivro_cloud.dispatch(text,jsonb) from public, anon, authenticated, service_role;
grant execute on function reivro_cloud.dispatch(text,jsonb) to authenticated;

create or replace function reivro_checks_api.dispatch(action text, request jsonb)
returns jsonb language sql security invoker set search_path = '' as $$
    select reivro_cloud.dispatch(action, request)
$$;

commit;
