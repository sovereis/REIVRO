\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH protected AS (
 SELECT 'projects' k,to_jsonb(x) r FROM reivro_cloud.projects x UNION ALL
 SELECT 'memberships',to_jsonb(x) FROM reivro_cloud.memberships x UNION ALL
 SELECT 'runs',to_jsonb(x) FROM reivro_cloud.runs x UNION ALL
 SELECT 'leases',to_jsonb(x) FROM reivro_cloud.execution_leases x UNION ALL
 SELECT 'events',to_jsonb(x) FROM reivro_cloud.events x UNION ALL
 SELECT 'contracts',to_jsonb(x) FROM reivro_cloud.task_contracts x UNION ALL
 SELECT 'submissions',to_jsonb(x) FROM reivro_cloud.task_submissions x UNION ALL
 SELECT 'policies',to_jsonb(x) FROM reivro_cloud.task_policies x UNION ALL
 SELECT 'corrections',to_jsonb(x) FROM reivro_cloud.task_corrections x UNION ALL
 SELECT 'findings',to_jsonb(x) FROM reivro_cloud.findings x UNION ALL
 SELECT 'protections',to_jsonb(x) FROM reivro_cloud.protections x
), stable_users AS (
 SELECT id,email,instance_id,aud,role,raw_app_meta_data,raw_user_meta_data,is_sso_user,is_anonymous,deleted_at,banned_until
 FROM auth.users
), target AS (
 SELECT * FROM stable_users WHERE id='0dae2b29-adaa-48b6-9a96-e9ac646b2a7a'::uuid AND email='agent-a@reivro.invalid'
)
SELECT jsonb_build_object(
 'users_count',(SELECT count(*) FROM auth.users),
 'memberships_count',(SELECT count(*) FROM reivro_cloud.memberships),
 'journal_count',(SELECT count(*) FROM reivro_cloud.events),
 'journal_sequence',(SELECT last_value FROM reivro_cloud.events_seq_seq),
 'sequence_called',(SELECT is_called FROM reivro_cloud.events_seq_seq),
 'target_exists',(SELECT count(*)=1 FROM target),
 'target_agent_membership',(SELECT count(*)=1 FROM reivro_cloud.memberships WHERE user_id='0dae2b29-adaa-48b6-9a96-e9ac646b2a7a'::uuid AND role='agent'),
 'other_users_hash',(SELECT encode(sha256(convert_to(coalesce(string_agg(to_jsonb(u)::text,'' ORDER BY id),''),'UTF8')),'hex') FROM stable_users u WHERE id<>'0dae2b29-adaa-48b6-9a96-e9ac646b2a7a'::uuid),
 'target_stable_hash',(SELECT encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') FROM target t),
 'protected_hash',(SELECT encode(sha256(convert_to(coalesce(string_agg(k||':'||r::text,'' ORDER BY k,r::text),''),'UTF8')),'hex') FROM protected),
 'all_checks_pass',(SELECT count(*) FROM auth.users)=6
  AND (SELECT count(*) FROM reivro_cloud.memberships)=5
  AND (SELECT count(*) FROM reivro_cloud.events)=21
  AND (SELECT last_value=21 AND is_called FROM reivro_cloud.events_seq_seq)
  AND (SELECT count(*)=1 FROM target)
  AND (SELECT count(*)=1 FROM reivro_cloud.memberships WHERE user_id='0dae2b29-adaa-48b6-9a96-e9ac646b2a7a'::uuid AND role='agent')
  AND (SELECT count(*) FROM pg_prepared_xacts)=0);
COMMIT;
