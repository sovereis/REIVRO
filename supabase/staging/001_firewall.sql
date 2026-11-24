-- Candidate for an isolated staging project. Uses a separate schema from Early Access.
begin;

create schema reivro_cloud;
create schema reivro_checks_api;
revoke all on schema reivro_cloud, reivro_checks_api from public, anon, authenticated, service_role;

create table reivro_cloud.projects (
    id uuid primary key default gen_random_uuid(),
    repository_id bigint not null unique check (repository_id > 0),
    repository text not null unique check (repository ~ '^[a-z0-9-]+/[a-z0-9_.-]+$'),
    installation_id bigint not null check (installation_id > 0),
    trusted_base text not null check (length(trusted_base) between 1 and 200)
);

-- Provision Auth users and memberships out of band. Each principal has one role per project.
create table reivro_cloud.memberships (
    project_id uuid not null references reivro_cloud.projects(id),
    user_id uuid not null references auth.users(id),
    role text not null check (role in ('viewer', 'reviewer', 'worker')),
    primary key (project_id, user_id)
);

create table reivro_cloud.runs (
    project_id uuid not null references reivro_cloud.projects(id),
    id uuid not null default gen_random_uuid(),
    delivery uuid not null,
    worker uuid not null references auth.users(id),
    pr integer not null check (pr > 0),
    base_ref text not null check (length(base_ref) between 1 and 200),
    base_sha text not null check (base_sha ~ '^[0-9a-f]{40}$'),
    head_sha text not null check (head_sha ~ '^[0-9a-f]{40}$'),
    protection_id uuid,
    outcome text check (outcome in ('OBSERVED', 'VIOLATION', 'PASS', 'INCONCLUSIVE', 'ERROR', 'INACTIVE')),
    report jsonb,
    primary key (project_id, id),
    unique (project_id, delivery),
    unique (project_id, pr, base_sha, head_sha)
);

create table reivro_cloud.findings (
    project_id uuid not null,
    id uuid not null default gen_random_uuid(),
    run_id uuid not null,
    evidence jsonb not null,
    decision text check (decision in ('confirm', 'reject')),
    primary key (project_id, id),
    foreign key (project_id, run_id) references reivro_cloud.runs(project_id, id)
);

create table reivro_cloud.protections (
    project_id uuid not null,
    id uuid not null,
    finding_id uuid not null,
    manifest text not null check (octet_length(manifest) between 1 and 8192),
    digest text not null check (digest = encode(sha256(convert_to(manifest, 'UTF8')), 'hex')),
    state text not null check (state in ('proposed', 'approved', 'revoked')),
    primary key (project_id, id),
    foreign key (project_id, finding_id) references reivro_cloud.findings(project_id, id)
);
create unique index one_active_guard on reivro_cloud.protections(project_id) where state = 'approved';
alter table reivro_cloud.runs add foreign key (project_id, protection_id)
    references reivro_cloud.protections(project_id, id);

create table reivro_cloud.events (
    project_id uuid not null references reivro_cloud.projects(id),
    seq bigint generated always as identity,
    actor uuid not null references auth.users(id),
    kind text not null,
    subject uuid not null,
    occurred_at timestamptz not null default clock_timestamp(),
    data jsonb not null,
    primary key (project_id, seq)
);

revoke all on all tables in schema reivro_cloud from public, anon, authenticated, service_role;
revoke all on all sequences in schema reivro_cloud from public, anon, authenticated, service_role;
alter table reivro_cloud.memberships enable row level security;
create policy own_membership on reivro_cloud.memberships for select to authenticated
    using (user_id = (select auth.uid()));

-- Only human members see records. Workers must use the narrow RPC.
do $$
declare
    tbl text;
    key_col text;
begin
    foreach tbl in array array['projects','runs','findings','protections','events'] loop
        key_col := case when tbl = 'projects' then 'id' else 'project_id' end;
        execute format('alter table reivro_cloud.%I enable row level security', tbl);
        execute format('create policy member_read on reivro_cloud.%I for select to authenticated
            using (%I in (select m.project_id from reivro_cloud.memberships m
                where m.user_id = (select auth.uid()) and m.role in (''viewer'', ''reviewer'')))',
            tbl, key_col);
    end loop;
end $$;

-- Privileged implementation lives outside the proposed exposed API schema.
-- Membership rows are locked before the project row. Admin provisioning must
-- use the same lock order when editing both. The project row serializes all mutations.
create function reivro_cloud.dispatch(action text, request jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    who uuid := auth.uid();
    project reivro_cloud.projects%rowtype;
    guard reivro_cloud.protections%rowtype;
    run reivro_cloud.runs%rowtype;
    found_evidence reivro_cloud.findings%rowtype;
    rid bigint;
    subject uuid;
    response jsonb;
    report jsonb;
    result text;
    detail jsonb := '{}'::jsonb;
    row_item jsonb;
    reason text;
begin
    if who is null or coalesce(octet_length(request::text), 0) not between 2 and 524288
        or jsonb_typeof(request) is distinct from 'object'
        or action is null or action not in ('claim', 'finish', 'confirm', 'reject', 'propose', 'approve', 'revoke')
    then
        raise insufficient_privilege using message = 'Denied firewall operation';
    end if;
    rid := (request->>'repository_id')::bigint;
    select p.* into project from reivro_cloud.projects p
        join reivro_cloud.memberships m on m.project_id = p.id
        where p.repository_id = rid and m.user_id = who
          and m.role = case when action in ('claim','finish') then 'worker' else 'reviewer' end
          and (action not in ('claim','finish') or p.installation_id = (request->>'installation_id')::bigint)
        for share of m;
    if not found then
        raise insufficient_privilege using message = 'Denied firewall operation';
    end if;
    select p.* into project from reivro_cloud.projects p
        where p.id = project.id and p.repository_id = rid
          and (action not in ('claim','finish') or p.installation_id = (request->>'installation_id')::bigint)
        for update;
    if not found then
        raise insufficient_privilege using message = 'Project scope changed';
    end if;

    if action = 'claim' then
        if request->>'base_ref' is distinct from project.trusted_base
            or request->>'repository' is distinct from project.repository then
            raise insufficient_privilege using message = 'Denied repository or base';
        end if;
        select * into guard from reivro_cloud.protections
            where project_id = project.id and state = 'approved';
        insert into reivro_cloud.runs(project_id, delivery, worker, pr, base_ref, base_sha, head_sha, protection_id)
        values (project.id, (request->>'delivery')::uuid, who, (request->>'pr')::integer,
                project.trusted_base, request->>'base_sha', request->>'head_sha', guard.id)
        on conflict do nothing returning * into run;
        if not found then
            return jsonb_build_object('duplicate', true);
        end if;
        subject := run.id;
        response := jsonb_build_object('run_id', run.id, 'protection_id', guard.id,
                                       'artifact_digest', guard.digest);
        detail := jsonb_build_object('pr', run.pr, 'base_sha', run.base_sha, 'head_sha', run.head_sha,
                                    'delivery', run.delivery);
    elsif action = 'finish' then
        subject := (request->>'run_id')::uuid;
        select * into run from reivro_cloud.runs where project_id = project.id
            and id = subject and worker = who and outcome is null;
        if not found then
            raise insufficient_privilege using message = 'Denied or completed run';
        end if;
        report := request->'report';
        result := report->>'status';
        if result is null or result not in ('REGRESSION_DETECTED','PASS','INCONCLUSIVE','ERROR')
            or report->>'rule' is distinct from 'python-syntax-regression'
            or report->>'verifier_version' is distinct from 'verify-v2' then
            raise invalid_parameter_value using message = 'Invalid verification report';
        end if;
        if result in ('REGRESSION_DETECTED','PASS') and (
            report->>'head_sha' is distinct from run.head_sha or report->>'base_sha' is distinct from run.base_sha
            or lower(report->>'repository') is distinct from project.repository
            or report->>'pr' is distinct from run.pr::text
            or jsonb_typeof(report->'files') is distinct from 'array'
        ) then
            raise invalid_parameter_value using message = 'Report identity does not match claim';
        end if;
        if result = 'REGRESSION_DETECTED' and run.base_ref = project.trusted_base then
            if not exists (select from jsonb_array_elements(report->'files') e
                           where e->>'status' = 'REGRESSION_DETECTED') then
                raise invalid_parameter_value using message = 'Confirmed evidence is missing';
            end if;
            for row_item in select e from jsonb_array_elements(report->'files') e
                            where e->>'status' = 'REGRESSION_DETECTED' loop
                if row_item->>'rule' is distinct from 'python-syntax-regression'
                    or coalesce(row_item->>'file','') !~ '[.]py$'
                    or coalesce(row_item->>'line','') !~ '^[1-9][0-9]*$'
                    or nullif(row_item->>'diagnostic','') is null
                    or nullif(row_item->>'exception','') is null
                    or nullif(row_item->>'excerpt','') is null
                    or not coalesce(starts_with(lower(row_item->>'head_file_url'),
                        'https://github.com/' || project.repository || '/blob/' || run.head_sha || '/'), false)
                    or not coalesce(starts_with(lower(row_item->>'base_file_url'),
                        'https://github.com/' || project.repository || '/blob/' || run.base_sha || '/'), false)
                    or nullif(report->>'compiler','') is null then
                    raise invalid_parameter_value using message = 'Incomplete finding evidence';
                end if;
                insert into reivro_cloud.findings(project_id, run_id, evidence)
                    values (project.id, run.id, row_item);
            end loop;
        elsif result = 'PASS' and (jsonb_array_length(report->'files') = 0 or exists (
            select from jsonb_array_elements(report->'files') e where e->>'status' is distinct from 'PASS'
        )) then
            raise invalid_parameter_value using message = 'Inconsistent PASS';
        end if;
        select * into guard from reivro_cloud.protections
            where project_id = project.id and id = run.protection_id;
        if run.base_ref is distinct from project.trusted_base then
            result := 'INACTIVE';
        elsif run.protection_id is not null and (guard.state is distinct from 'approved'
            or run.head_sha = (guard.manifest::jsonb)->>'source_head_sha') then
            result := 'INACTIVE';
        elsif result in ('REGRESSION_DETECTED','PASS') then
            if run.protection_id is null then
                result := 'OBSERVED';
            elsif request->>'artifact_digest' is distinct from guard.digest then
                result := 'INCONCLUSIVE';
            elsif result = 'REGRESSION_DETECTED' then
                result := 'VIOLATION';
            end if;
        end if;
        update reivro_cloud.runs set outcome = result, report = report_json.payload
            from (select request->'report' as payload) report_json
            where project_id = project.id and id = run.id;
        detail := jsonb_build_object('outcome', result, 'protection_id', run.protection_id);
        response := jsonb_build_object('run_id', run.id, 'outcome', result);

    else
        subject := (request->>'subject')::uuid;
        reason := btrim(coalesce(request->>'reason', ''));
        if length(reason) not between 1 and 1000 then
            raise invalid_parameter_value using message = 'A review reason is required';
        end if;
        detail := jsonb_build_object('reason', reason);
        if action in ('confirm','reject') then
            update reivro_cloud.findings set decision = action where project_id = project.id
                and id = subject and decision is null returning * into found_evidence;
            if not found then raise insufficient_privilege using message = 'Denied finding decision'; end if;
            select * into run from reivro_cloud.runs
                where project_id = project.id and id = found_evidence.run_id;
            detail := detail || jsonb_build_object('run_id', run.id, 'finding_digest',
                encode(sha256(convert_to(jsonb_build_object(
                    'evidence', found_evidence.evidence, 'base_sha', run.base_sha,
                    'head_sha', run.head_sha, 'pr', run.pr, 'repository_id', rid,
                    'verifier_version', run.report->>'verifier_version'
                )::text, 'UTF8')), 'hex'));
        elsif action = 'propose' then
            select * into found_evidence from reivro_cloud.findings where project_id = project.id
                and id = subject and decision = 'confirm';
            if not found then raise insufficient_privilege using message = 'Confirmed finding required'; end if;
            subject := gen_random_uuid();
            select * into run from reivro_cloud.runs where project_id = project.id and id = found_evidence.run_id;
            select jsonb_build_object(
                'schema', 1, 'rule', 'python-syntax-regression', 'verifier_version', 'verify-v2',
                'repository_id', rid, 'protection_id', subject, 'scope', 'existing-python',
                'finding_id', found_evidence.id, 'source_base_sha', run.base_sha,
                'source_head_sha', run.head_sha
            )::text into guard.manifest;
            insert into reivro_cloud.protections(project_id,id,finding_id,manifest,digest,state)
                values (project.id, subject, found_evidence.id, guard.manifest,
                        encode(sha256(convert_to(guard.manifest, 'UTF8')), 'hex'), 'proposed')
                returning * into guard;
            detail := detail || jsonb_build_object('finding_id', found_evidence.id, 'digest', guard.digest);
            response := jsonb_build_object('protection_id', guard.id, 'manifest', guard.manifest, 'digest', guard.digest);
        else
            update reivro_cloud.protections
                set state = case action when 'approve' then 'approved' else 'revoked' end
                where project_id = project.id and id = subject and digest = request->>'digest'
                  and state = case action when 'approve' then 'proposed' else 'approved' end
                returning * into guard;
            if not found then raise insufficient_privilege using message = 'Denied protection decision'; end if;
            detail := detail || jsonb_build_object('digest', guard.digest);
        end if;
    end if;
    insert into reivro_cloud.events(project_id, actor, kind, subject, data)
        values (project.id, who, action, subject, detail);
    return coalesce(response, jsonb_build_object('subject', subject, 'action', action));
end
$$;
revoke all on function reivro_cloud.dispatch(text,jsonb) from public, anon, authenticated, service_role;

create function reivro_checks_api.dispatch(action text, request jsonb)
returns jsonb language sql security invoker set search_path = '' as $$
    select reivro_cloud.dispatch(action, request)
$$;
revoke all on function reivro_checks_api.dispatch(text,jsonb) from public, anon, authenticated, service_role;
grant usage on schema reivro_cloud, reivro_checks_api to authenticated;
grant select on all tables in schema reivro_cloud to authenticated;
grant execute on function reivro_cloud.dispatch(text,jsonb),
    reivro_checks_api.dispatch(text,jsonb) to authenticated;

-- Human evidence lookup is a security-invoker query evaluated under RLS.
create function reivro_checks_api.read_run(p_repository_id bigint, p_run_id uuid)
returns jsonb language sql stable security invoker set search_path = '' as $$
    select jsonb_build_object(
        'run', to_jsonb(r) - 'worker' - 'delivery',
        'findings', coalesce((
            select jsonb_agg(jsonb_build_object('id', f.id, 'evidence', f.evidence, 'decision', f.decision)
                             order by f.id)
              from reivro_cloud.findings f where f.project_id = r.project_id and f.run_id = r.id
        ), '[]'::jsonb)
    )
    from reivro_cloud.runs r
    join reivro_cloud.projects p on p.id = r.project_id
    where p.repository_id = p_repository_id and r.id = p_run_id
$$;
revoke all on function reivro_checks_api.read_run(bigint,uuid) from public, anon, authenticated, service_role;
grant execute on function reivro_checks_api.read_run(bigint,uuid) to authenticated;

commit;
