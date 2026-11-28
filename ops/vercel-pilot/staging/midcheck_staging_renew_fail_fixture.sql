\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH n AS (
 SELECT s.project_id,s.id,s.run_id,s.result,r.worker,r.outcome,r.report,l.state,l.fence,l.attempt_id,l.lease_until,l.attempt_until
 FROM reivro_cloud.task_submissions s JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id)
 JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id)
 WHERE s.id=:'new_submission_id'::uuid
)
SELECT jsonb_build_object('all_checks_pass',run_id=:'run_id'::uuid AND worker=:'worker_id'::uuid
 AND state='running' AND fence=1 AND attempt_id=:'attempt_id'::uuid AND lease_until>clock_timestamp()
 AND result IS NULL AND outcome IS NULL AND report IS NULL
 AND (SELECT count(*) FROM reivro_cloud.events)=26
 AND (SELECT last_value=26 AND is_called FROM reivro_cloud.events_seq_seq)
 AND (SELECT count(*) FROM reivro_cloud.events WHERE kind='task_renew' AND subject=n.id)=1
 AND (SELECT count(*) FROM reivro_cloud.events WHERE subject=n.id AND kind IN ('task_fail','task_finish'))=0)
FROM n;
COMMIT;
