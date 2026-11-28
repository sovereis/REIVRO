\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH t AS (
 SELECT p.*,s.id submission_id,s.run_id,l.attempt_id,l.fence,l.state,l.lease_until,l.attempt_until,
  (SELECT user_id FROM reivro_cloud.memberships WHERE project_id=p.id AND role='worker') worker_id
 FROM reivro_cloud.projects p JOIN reivro_cloud.task_submissions s ON s.project_id=p.id
 JOIN reivro_cloud.execution_leases l ON l.project_id=p.id AND l.run_id=s.run_id
 WHERE p.repository_id=:'repository_id'::bigint AND s.id=:'submission_id'::uuid
  AND s.contract_id=:'contract_id'::uuid AND s.digest=:'digest'::text
  AND s.base_sha=:'base_sha'::text AND s.head_sha=:'head_sha'::text
  AND s.result IS NULL AND l.state='running' AND l.fence=1 AND l.attempt_id IS NOT NULL
  AND l.lease_until<=clock_timestamp()
  AND (SELECT count(*) FROM reivro_cloud.runs WHERE task_submission_id IS NOT NULL)=1
  AND (SELECT count(*) FROM reivro_cloud.execution_leases)=1
  AND (SELECT count(*) FROM reivro_cloud.events)=16
  AND (SELECT last_value=16 AND is_called FROM reivro_cloud.events_seq_seq)
)
SELECT jsonb_build_object('installation_id',installation_id,'repository',repository,'base_ref',trusted_base,
 'worker_id',worker_id,'run_id',run_id,'old_attempt_id',attempt_id,'old_fence',fence) FROM t;
COMMIT;
