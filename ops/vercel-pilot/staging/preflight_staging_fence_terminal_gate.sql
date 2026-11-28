\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH project AS (
 SELECT * FROM reivro_cloud.projects WHERE repository_id=:'repository_id'::bigint
), current_task AS (
 SELECT s.project_id,s.id,s.contract_id,s.run_id,s.digest,s.base_sha,s.head_sha,s.result,
        r.worker,r.pr,r.delivery,r.outcome,r.report,
        l.state,l.fence,l.attempt_id,l.lease_until,l.attempt_until
 FROM project p JOIN reivro_cloud.task_submissions s ON s.project_id=p.id
 JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id)
 JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id)
 WHERE s.id=:'submission_id'::uuid
), first_task AS (
 SELECT s.id,s.result,r.outcome,r.report,l.state,l.fence,l.attempt_id,l.lease_until,l.attempt_until
 FROM project p JOIN reivro_cloud.task_submissions s ON s.project_id=p.id
 JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id)
 JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id)
 WHERE s.id=:'original_submission_id'::uuid
), checks AS (
 SELECT jsonb_build_object(
  'project_unique',(SELECT count(*) FROM project)=1,
  'receipt_contract',(SELECT count(*)=1 FROM reivro_cloud.task_contracts c JOIN project p ON p.id=c.project_id WHERE c.id=:'contract_id'::uuid),
  'receipt_submission',count(*)=1 AND bool_and(id=:'submission_id'::uuid AND contract_id=:'contract_id'::uuid AND run_id=:'run_id'::uuid),
  'execution_identity',bool_and(digest=:'digest' AND base_sha=:'base_sha' AND head_sha=:'head_sha'),
  'worker_membership',bool_and(EXISTS(SELECT FROM reivro_cloud.memberships m WHERE m.project_id=current_task.project_id AND m.user_id=current_task.worker AND m.role='worker')),
  'retryable_state',bool_and(state='retryable'),
  'fence_1',bool_and(fence=1),
  'attempt_cleared',bool_and(attempt_id IS NULL),
  'lease_until_cleared',bool_and(lease_until IS NULL),
  'attempt_until_cleared',bool_and(attempt_until IS NULL),
  'no_task_result',bool_and(result IS NULL),
  'no_run_outcome',bool_and(outcome IS NULL),
  'no_run_report',bool_and(report IS NULL),
  'first_run_preserved',(SELECT count(*)=1 AND bool_and(state='completed' AND fence=3 AND attempt_id IS NULL AND lease_until IS NULL AND attempt_until IS NULL AND result->>'status'='VERIFIED' AND outcome='INCONCLUSIVE' AND report=result) FROM first_task),
  'journal_28',(SELECT count(*)=28 AND min(seq)=1 AND max(seq)=28 FROM reivro_cloud.events),
  'sequence_28_true',(SELECT last_value=28 AND is_called FROM reivro_cloud.events_seq_seq),
  'current_event_cardinality',bool_and(
    (SELECT count(*) FROM reivro_cloud.events WHERE subject=current_task.run_id AND kind='lease_claim')=1 AND
    (SELECT count(*) FROM reivro_cloud.events WHERE subject=current_task.run_id AND kind='lease_failure')=1 AND
    (SELECT count(*) FROM reivro_cloud.events WHERE subject=current_task.id AND kind='task_claim')=1 AND
    (SELECT count(*) FROM reivro_cloud.events WHERE subject=current_task.id AND kind='task_renew')=1 AND
    (SELECT count(*) FROM reivro_cloud.events WHERE subject=current_task.id AND kind='task_fail')=1 AND
    (SELECT count(*) FROM reivro_cloud.events WHERE subject=current_task.id AND kind='task_finish')=0),
  'two_task_runs',(SELECT count(*)=2 FROM reivro_cloud.runs WHERE task_submission_id IS NOT NULL),
  'two_leases',(SELECT count(*)=2 FROM reivro_cloud.execution_leases),
  'no_prepared_xacts',(SELECT count(*)=0 FROM pg_prepared_xacts),
  'lease_constraints_valid',(SELECT count(*)=8 AND bool_and(convalidated) FROM pg_constraint WHERE conrelid='reivro_cloud.execution_leases'::regclass),
  'api_wrapper_md5',(SELECT md5(prosrc)='3458700a52910337fea6aca7f57d8f03' AND NOT prosecdef AND proconfig=ARRAY['search_path=""'] FROM pg_proc WHERE oid='reivro_checks_api.task_dispatch(text,jsonb)'::regprocedure),
  'task_dispatch_md5',(SELECT md5(prosrc)='3c56d88c40c4a66f564fa4d51fca0930' AND prosecdef AND proconfig=ARRAY['search_path=""'] FROM pg_proc WHERE oid='reivro_cloud.task_dispatch(text,jsonb)'::regprocedure),
  'execution_dispatch_md5',(SELECT md5(prosrc)='e76a6ec5da5b3a2d9122cbd20e52f9d8' AND prosecdef AND proconfig=ARRAY['search_path=""'] FROM pg_proc WHERE oid='reivro_cloud.execution_dispatch(text,jsonb,uuid)'::regprocedure)
 ) value,
 (array_agg(worker))[1]::text worker_id
 FROM current_task
)
SELECT jsonb_build_object('checks',value,'worker_id',worker_id,
 'installation_id',(SELECT installation_id FROM project),
 'repository',(SELECT repository FROM project),
 'base_ref',(SELECT trusted_base FROM project),
 'pr',(SELECT pr FROM current_task),
 'delivery',(SELECT delivery FROM current_task),
 'digest',(SELECT digest FROM current_task),
 'base_sha',(SELECT base_sha FROM current_task),
 'head_sha',(SELECT head_sha FROM current_task),
 'all_checks_pass',
 NOT EXISTS(SELECT FROM jsonb_each(value) e WHERE e.value IS DISTINCT FROM 'true'::jsonb))
FROM checks;
COMMIT;
