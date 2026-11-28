\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH n AS (
 SELECT s.project_id,s.id,s.run_id,s.result,r.worker,r.outcome,r.report,l.state,l.fence,l.attempt_id,l.lease_until,l.attempt_until
 FROM reivro_cloud.task_submissions s JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id)
 JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id)
 WHERE s.id=:'new_submission_id'::uuid
), old AS (
 SELECT s.result,r.outcome,r.report,l.state,l.fence,l.attempt_id FROM reivro_cloud.task_submissions s
 JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id)
 JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id)
 WHERE s.id=:'original_submission_id'::uuid
)
SELECT jsonb_build_object('run_id',n.run_id,'all_checks_pass',
 n.run_id=:'run_id'::uuid AND n.worker=:'worker_id'::uuid AND n.state='retryable' AND n.fence=1
 AND n.attempt_id IS NULL AND n.lease_until IS NULL AND n.attempt_until IS NULL
 AND n.result IS NULL AND n.outcome IS NULL AND n.report IS NULL
 AND old.state='completed' AND old.fence=3 AND old.attempt_id IS NULL
 AND old.result->>'status'='VERIFIED' AND old.outcome='INCONCLUSIVE' AND old.report=old.result
 AND (SELECT count(*) FROM reivro_cloud.events)=28
 AND (SELECT last_value=28 AND is_called FROM reivro_cloud.events_seq_seq)
 AND (SELECT count(*) FROM reivro_cloud.events WHERE kind='lease_failure' AND subject=n.run_id)=1
 AND (SELECT count(*) FROM reivro_cloud.events WHERE kind='task_fail' AND subject=n.id)=1
 AND (SELECT count(*) FROM reivro_cloud.events WHERE kind='task_finish' AND subject=n.id)=0
 AND (SELECT count(*) FROM reivro_cloud.runs WHERE task_submission_id IS NOT NULL)=2
 AND (SELECT count(*) FROM reivro_cloud.execution_leases)=2)
FROM n CROSS JOIN old;
COMMIT;
