\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH task AS (
 SELECT s.id,s.run_id,s.result,r.worker,r.outcome,r.report,l.state,l.fence,l.attempt_id,l.lease_until,l.attempt_until
 FROM reivro_cloud.task_submissions s
 JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id)
 JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id)
 WHERE s.id=:'submission_id'::uuid
), first_task AS (
 SELECT s.result,r.outcome,r.report,l.state,l.fence,l.attempt_id,l.lease_until,l.attempt_until
 FROM reivro_cloud.task_submissions s
 JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id)
 JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id)
 WHERE s.id=:'original_submission_id'::uuid
), checks AS (
 SELECT jsonb_build_object(
  'task_unique',count(*)=1,
  'run_id',bool_and(run_id=:'run_id'::uuid),
  'worker_id',bool_and(worker=:'worker_id'::uuid),
  'state',bool_and(state=:'expected_state'),
  'fence',bool_and(fence=:'expected_fence'::integer),
  'attempt_shape',bool_and(CASE WHEN :'expected_state'='running' THEN attempt_id IS NOT NULL AND lease_until>clock_timestamp() AND attempt_until>=lease_until ELSE attempt_id IS NULL AND lease_until IS NULL AND attempt_until IS NULL END),
  'result_absent',bool_and(result IS NULL),
  'outcome',bool_and(CASE WHEN :'expected_state'='terminal' THEN outcome='ERROR' ELSE outcome IS NULL END),
  'report_absent',bool_and(report IS NULL),
  'journal',(SELECT count(*)=:'expected_events'::integer AND min(seq)=1 AND max(seq)=:'expected_events'::integer FROM reivro_cloud.events),
  'sequence',(SELECT last_value=:'expected_events'::integer AND is_called FROM reivro_cloud.events_seq_seq),
  'lease_claims',bool_and((SELECT count(*) FROM reivro_cloud.events WHERE subject=task.run_id AND kind='lease_claim')=:'expected_claims'::integer),
  'task_claims',bool_and((SELECT count(*) FROM reivro_cloud.events WHERE subject=task.id AND kind='task_claim')=:'expected_claims'::integer),
  'lease_failures',bool_and((SELECT count(*) FROM reivro_cloud.events WHERE subject=task.run_id AND kind='lease_failure')=:'expected_failures'::integer),
  'task_failures',bool_and((SELECT count(*) FROM reivro_cloud.events WHERE subject=task.id AND kind='task_fail')=:'expected_failures'::integer),
  'renew_unchanged',bool_and((SELECT count(*) FROM reivro_cloud.events WHERE subject=task.id AND kind='task_renew')=1),
  'no_finish',bool_and((SELECT count(*) FROM reivro_cloud.events WHERE subject=task.id AND kind='task_finish')=0),
  'first_run_preserved',(SELECT count(*)=1 AND bool_and(state='completed' AND fence=3 AND attempt_id IS NULL AND lease_until IS NULL AND attempt_until IS NULL AND result->>'status'='VERIFIED' AND outcome='INCONCLUSIVE' AND report=result) FROM first_task),
  'no_prepared_xacts',(SELECT count(*)=0 FROM pg_prepared_xacts)
 ) value
 FROM task
)
SELECT jsonb_build_object('checks',value,'all_checks_pass',
 NOT EXISTS(SELECT FROM jsonb_each(value) e WHERE e.value IS DISTINCT FROM 'true'::jsonb)) FROM checks;
COMMIT;
