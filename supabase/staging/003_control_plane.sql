begin;
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
   response:=reivro_cloud.dispatch('claim_durable',request);
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
    response:=reivro_cloud.dispatch(case action when 'renew' then 'renew_durable' else 'fail_durable' end,request);
   else
    -- Reuse the existing ownership check and lease renewal; all changes roll back on failure.
    perform reivro_cloud.dispatch('renew_durable',request);
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
