begin;
set local lock_timeout = '5s';
set local statement_timeout = '30s';
select pg_advisory_xact_lock(1469495108);
do $$
begin
 if to_regclass('reivro_cloud.execution_leases') is null
 or to_regclass('reivro_cloud.task_submissions') is not null
 or (select md5(prosrc) from pg_proc where oid=to_regprocedure('reivro_cloud.dispatch(text,jsonb)'))
    is distinct from '821570bb9304b8e4348996990f804aa2'
 or (select md5(prosrc) from pg_proc where oid=to_regprocedure('reivro_cloud.dispatch_v1(text,jsonb)'))
    is distinct from '7b65dd994ca180ed06312d3c0a7820fe' then
  raise exception 'Expected reviewed 001 plus 002, without 003';
 end if;
end $$;
-- Existing rows remain in the syntax namespace. Task submissions receive a
-- separate execution identity, while sharing the same run and lease machinery.
alter table reivro_cloud.runs add column task_submission_id uuid;
alter table reivro_cloud.runs drop constraint runs_project_id_delivery_key;
alter table reivro_cloud.runs drop constraint runs_project_id_pr_base_sha_head_sha_key;
create unique index syntax_delivery on reivro_cloud.runs(project_id,delivery)
 where task_submission_id is null;
create unique index syntax_revision on reivro_cloud.runs(project_id,pr,base_sha,head_sha)
 where task_submission_id is null;
create unique index task_execution on reivro_cloud.runs(project_id,task_submission_id)
 where task_submission_id is not null;

-- Keep syntax's one_active_guard invariant. Task policies have their own set,
-- inside the same project, execution, audit and human-decision trust boundary.
alter table reivro_cloud.memberships drop constraint memberships_role_check;
alter table reivro_cloud.memberships add check (role in ('agent','viewer','reviewer','worker'));
create table reivro_cloud.task_contracts (
 project_id uuid not null references reivro_cloud.projects(id),
 id uuid not null, version integer not null check(version > 0),
 digest text not null, document jsonb not null,
 primary key(project_id,id,version), unique(project_id,id,version,digest),
 check(digest=encode(sha256(convert_to(document::text,'UTF8')),'hex'))
);
create table reivro_cloud.task_policies (
 project_id uuid not null references reivro_cloud.projects(id),
 id uuid not null, digest text not null, document jsonb not null,
 source uuid not null, state text not null check(state in ('approved','revoked')),
 primary key(project_id,id),
 check(digest=encode(sha256(convert_to(document::text,'UTF8')),'hex'))
);
create table reivro_cloud.task_submissions (
 project_id uuid not null references reivro_cloud.projects(id),
 id uuid not null, actor uuid not null references auth.users(id),
 contract_id uuid not null, version integer not null, digest text not null,
 base_sha text not null check(base_sha ~ '^[0-9a-f]{40}$'),
 head_sha text not null check(head_sha ~ '^[0-9a-f]{40}$'),
 verifier text not null check(verifier='task-completion-v1'),
 run_id uuid, policy_set jsonb, result jsonb, confirmed boolean not null default false,
 parent uuid,
 primary key(project_id,id), unique(project_id,run_id),
 foreign key(project_id,contract_id,version,digest)
 references reivro_cloud.task_contracts(project_id,id,version,digest),
 foreign key(project_id,run_id) references reivro_cloud.runs(project_id,id),
 foreign key(project_id,parent) references reivro_cloud.task_submissions(project_id,id)
);
create unique index one_task_root_submission
 on reivro_cloud.task_submissions(project_id,contract_id,version,actor) where parent is null;
create table reivro_cloud.task_corrections (
 project_id uuid not null, submission uuid not null, used boolean not null default false,
 primary key(project_id,submission),
 foreign key(project_id,submission) references reivro_cloud.task_submissions(project_id,id)
);
alter table reivro_cloud.task_policies add foreign key(project_id,source)
 references reivro_cloud.task_submissions(project_id,id);
-- Private control tables have no direct client grants, including SELECT.
alter table reivro_cloud.task_contracts enable row level security;
alter table reivro_cloud.task_submissions enable row level security;
alter table reivro_cloud.task_policies enable row level security;
alter table reivro_cloud.task_corrections enable row level security;
revoke all on reivro_cloud.task_contracts,reivro_cloud.task_submissions,
 reivro_cloud.task_policies,reivro_cloud.task_corrections from public,anon,authenticated,service_role;

alter table reivro_cloud.runs add foreign key(project_id,task_submission_id)
 references reivro_cloud.task_submissions(project_id,id);

create function reivro_cloud.execution_dispatch(action text, request jsonb, submission_id uuid)
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
    if submission_id is not null and action not in ('claim_durable','renew_durable','fail_durable') then
        raise insufficient_privilege using message = 'Denied task execution action';
    end if;
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
            and r.task_submission_id is not distinct from submission_id
            and r.delivery = delivery_id and (r.pr, r.base_sha, r.head_sha) is distinct from
                ((request->>'pr')::integer, request->>'base_sha', request->>'head_sha')) then
            raise invalid_parameter_value using message = 'Delivery revision conflict';
        end if;
        select r.* into run from reivro_cloud.runs r where r.project_id = project.id
            and r.task_submission_id is not distinct from submission_id
            and (submission_id is not null or (r.pr, r.base_sha, r.head_sha) =
                ((request->>'pr')::integer, request->>'base_sha', request->>'head_sha'));
        if found and (run.pr, run.base_sha, run.head_sha) is distinct from
            ((request->>'pr')::integer, request->>'base_sha', request->>'head_sha') then
            raise invalid_parameter_value using message = 'Execution revision conflict';
        end if;
        if not found then
            if submission_id is null then
                stored := reivro_cloud.dispatch_v1('claim', request);
            else
                insert into reivro_cloud.runs(project_id,delivery,worker,pr,base_ref,base_sha,head_sha,task_submission_id)
                values(project.id,submission_id,actor_id,(request->>'pr')::integer,
                       project.trusted_base,request->>'base_sha',request->>'head_sha',submission_id)
                returning jsonb_build_object('run_id',id) into stored;
            end if;
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
            and r.task_submission_id is not distinct from submission_id
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

revoke all on function reivro_cloud.execution_dispatch(text,jsonb,uuid)
 from public,anon,authenticated,service_role;
create or replace function reivro_cloud.dispatch(action text, request jsonb)
returns jsonb language sql security definer set search_path='' as $$
 select reivro_cloud.execution_dispatch(action,request,null)
$$;

create function reivro_cloud.task_dispatch(action text, request jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 who uuid := auth.uid(); role_name text; project reivro_cloud.projects%rowtype;
 item reivro_cloud.task_submissions%rowtype; contract reivro_cloud.task_contracts%rowtype;
 lease reivro_cloud.execution_leases%rowtype;
 subject uuid := (request->>'id')::uuid; response jsonb; snapshot jsonb;
 doc jsonb; dig text; verdict text; parent_item reivro_cloud.task_submissions%rowtype;
begin
 if who is null or auth.jwt()->>'is_anonymous'='true' or subject is null
 or jsonb_typeof(request) is distinct from 'object' or octet_length(request::text)>65536 then
  raise insufficient_privilege using message='Denied task operation'; end if;
 select m.role into role_name from reivro_cloud.memberships m join reivro_cloud.projects p on p.id=m.project_id
 where p.repository_id=(request->>'repository_id')::bigint and m.user_id=who for share of m;
 if role_name is null or action is null or
 not ((role_name='reviewer' and action in ('approve_contract','confirm','approve_policy','revoke_policy','authorize_correction','read'))
 or (role_name='agent' and action in ('submit','read'))
 or (role_name='worker' and action in ('claim','renew','fail','finish','read'))
 or (role_name='viewer' and action='read')) then
  raise insufficient_privilege using message='Denied task role'; end if;
 select * into strict project from reivro_cloud.projects where repository_id=(request->>'repository_id')::bigint for update;
 select * into item from reivro_cloud.task_submissions where project_id=project.id and id=subject;
 if role_name='agent' and item.id is not null and item.actor<>who then
  raise insufficient_privilege using message='Denied submission owner'; end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',id,'digest',digest,'document',document) order by id),'[]'::jsonb)
 into snapshot from reivro_cloud.task_policies where project_id=project.id and state='approved';
 if action='read' then
  if item.id is null then raise insufficient_privilege; end if;
  return to_jsonb(item)-'actor';
 elsif action='approve_contract' then
  doc:=request->'document'; dig:=encode(sha256(convert_to(doc::text,'UTF8')),'hex');
  if jsonb_typeof(doc) is distinct from 'object' or doc->>'base_sha' !~ '^[0-9a-f]{40}$'
   or doc->>'base_sha' is null or jsonb_typeof(doc->'criteria') is distinct from 'array'
   or jsonb_array_length(doc->'criteria') not between 1 and 32
   or request->>'digest' is distinct from dig then raise invalid_parameter_value using message='Invalid contract'; end if;
  insert into reivro_cloud.task_contracts values(project.id,subject,(request->>'version')::integer,dig,doc);
  response:=jsonb_build_object('digest',dig);
 elsif action='submit' then
  select * into strict contract from reivro_cloud.task_contracts where project_id=project.id
   and id=(request->>'contract_id')::uuid and version=(request->>'version')::integer
   and digest=request->>'digest';
  if item.id is not null then
   if (item.actor,item.contract_id,item.version,item.digest,item.head_sha,item.parent) is distinct from
    (who,contract.id,contract.version,contract.digest,request->>'head_sha',(request->>'parent')::uuid) then
    raise invalid_parameter_value using message='Submission replay conflict'; end if;
   return jsonb_build_object('state','duplicate','id',subject);
  end if;
  if request->>'parent' is not null then
   select * into strict parent_item from reivro_cloud.task_submissions where project_id=project.id and id=(request->>'parent')::uuid;
   if parent_item.actor<>who or parent_item.contract_id<>contract.id or parent_item.version<>contract.version
    or parent_item.head_sha=request->>'head_sha' then raise insufficient_privilege; end if;
   update reivro_cloud.task_corrections set used=true where project_id=project.id and submission=parent_item.id and not used;
   if not found then raise insufficient_privilege using message='Correction not authorized'; end if;
  end if;
  insert into reivro_cloud.task_submissions(project_id,id,actor,contract_id,version,digest,base_sha,head_sha,verifier,parent)
   values(project.id,subject,who,contract.id,contract.version,contract.digest,contract.document->>'base_sha',
    request->>'head_sha','task-completion-v1',(request->>'parent')::uuid);
 elsif action in ('claim','renew','fail','finish') then
  if item.id is null then raise insufficient_privilege; end if;
  if action='claim' then
   if request->>'base_sha' is distinct from item.base_sha or request->>'head_sha' is distinct from item.head_sha
    or request->>'digest' is distinct from item.digest or request->>'verifier' is distinct from item.verifier then
    raise invalid_parameter_value using message='Execution identity mismatch'; end if;
   response:=reivro_cloud.execution_dispatch('claim_durable',request,subject);
   if item.run_id is not null and item.run_id<>(response->>'run_id')::uuid then raise insufficient_privilege; end if;
   if response->>'state'='running' then
    update reivro_cloud.task_submissions set run_id=(response->>'run_id')::uuid,policy_set=snapshot
     where project_id=project.id and id=subject;
    response:=response||jsonb_build_object('digest',item.digest,'base_sha',item.base_sha,
     'head_sha',item.head_sha,'verifier',item.verifier,'policy_set',snapshot,'contract',
     (select document from reivro_cloud.task_contracts where project_id=project.id
      and id=item.contract_id and version=item.version));
   end if;
  else
   if item.run_id is distinct from (request->>'run_id')::uuid then raise insufficient_privilege; end if;
   if action in ('renew','fail') then
    response:=reivro_cloud.execution_dispatch(case action when 'renew' then 'renew_durable' else 'fail_durable' end,request,subject);
   else
    -- Reuse the existing ownership check and lease renewal; all changes roll back on failure.
    perform reivro_cloud.execution_dispatch('renew_durable',request,subject);
    select * into strict lease from reivro_cloud.execution_leases where project_id=project.id and run_id=item.run_id;
    doc:=request->'result'; verdict:=doc->>'status';
    if verdict is null or verdict not in ('VERIFIED','INCOMPLETE','POLICY_VIOLATION','INCONCLUSIVE','ERROR')
     or doc->>'head_sha' is distinct from item.head_sha or doc->>'base_sha' is distinct from item.base_sha
     or doc->>'digest' is distinct from item.digest or doc->>'verifier' is distinct from item.verifier
     or jsonb_typeof(doc->'evidence') is distinct from 'object'
     or coalesce(doc->'evidence'->>'digest','') !~ '^[0-9a-f]{64}$'
     or doc->'policy_set' is distinct from item.policy_set then
      raise invalid_parameter_value using message='Invalid authoritative result'; end if;
    if snapshot is distinct from item.policy_set then
     doc:=jsonb_build_object('status','INCONCLUSIVE','reason','policy_set_changed'); verdict:='INCONCLUSIVE';
    end if;
    if lease.lease_until<=clock_timestamp() then raise insufficient_privilege using message='Lease expired'; end if;
    update reivro_cloud.task_submissions set result=doc where project_id=project.id and id=subject;
    update reivro_cloud.runs set outcome=case when verdict='ERROR' then 'ERROR' else 'INCONCLUSIVE' end,report=doc
     where project_id=project.id and id=item.run_id;
    update reivro_cloud.execution_leases set state=case when verdict='ERROR' then 'terminal' else 'completed' end,
     attempt_id=null,lease_until=null,attempt_until=null where project_id=project.id and run_id=item.run_id;
    response:=jsonb_build_object('state',case when verdict='ERROR' then 'terminal' else 'completed' end,'result',doc);
   end if;
  end if;
 elsif action='confirm' then
  if item.result->>'status' not in ('INCOMPLETE','POLICY_VIOLATION') or item.result is null then raise insufficient_privilege; end if;
  update reivro_cloud.task_submissions set confirmed=true where project_id=project.id and id=subject;
 elsif action='approve_policy' then
  select * into strict item from reivro_cloud.task_submissions where project_id=project.id and id=(request->>'source')::uuid;
  if not item.confirmed then raise insufficient_privilege; end if;
  doc:=request->'document'; dig:=encode(sha256(convert_to(doc::text,'UTF8')),'hex');
  if jsonb_typeof(doc) is distinct from 'object' or doc->>'kind' is null
   or doc->>'kind' not in ('exists','blob_sha256','protected_path','allowed_paths')
   or request->>'digest' is distinct from dig then raise invalid_parameter_value; end if;
  insert into reivro_cloud.task_policies values(project.id,subject,dig,doc,item.id,'approved');
 elsif action='revoke_policy' then
  update reivro_cloud.task_policies set state='revoked' where project_id=project.id and id=subject and state='approved';
  if not found then raise insufficient_privilege; end if;
 elsif action='authorize_correction' then
  if item.result->>'status' not in ('INCOMPLETE','POLICY_VIOLATION') or item.result is null then raise insufficient_privilege; end if;
  if (select count(*) from reivro_cloud.task_corrections c join reivro_cloud.task_submissions s
   on (s.project_id,s.id)=(c.project_id,c.submission) where s.project_id=project.id and s.contract_id=item.contract_id)>=2 then
   raise insufficient_privilege using message='Correction budget exhausted'; end if;
  insert into reivro_cloud.task_corrections values(project.id,subject,false);
 end if;
 insert into reivro_cloud.events(project_id,actor,kind,subject,data)
 values(project.id,who,'task_'||action,subject,jsonb_build_object('version',1));
 return coalesce(response,'{}'::jsonb)||jsonb_build_object('id',subject);
end $$;
revoke all on function reivro_cloud.task_dispatch(text,jsonb) from public,anon,authenticated,service_role;
grant execute on function reivro_cloud.task_dispatch(text,jsonb) to authenticated;
create function reivro_checks_api.task_dispatch(action text,request jsonb)
returns jsonb language sql security invoker set search_path='' as $$select reivro_cloud.task_dispatch(action,request)$$;
revoke all on function reivro_checks_api.task_dispatch(text,jsonb) from public,anon,authenticated,service_role;
grant execute on function reivro_checks_api.task_dispatch(text,jsonb) to authenticated;
commit;
