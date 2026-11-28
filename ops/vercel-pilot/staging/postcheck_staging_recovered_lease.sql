\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH t AS (
 SELECT p.id project_id,s.id submission_id,s.run_id,l.attempt_id,l.fence,l.state,l.lease_until,l.attempt_until,
  :'worker_id'::uuid worker_id,:'old_run_id'::uuid old_run_id,:'old_attempt_id'::uuid old_attempt_id
 FROM reivro_cloud.projects p JOIN reivro_cloud.task_submissions s ON s.project_id=p.id
 JOIN reivro_cloud.execution_leases l ON l.project_id=p.id AND l.run_id=s.run_id
 WHERE p.repository_id=:'repository_id'::bigint AND s.id=:'submission_id'::uuid
)
SELECT jsonb_build_object('run_id',run_id,'attempt_id',attempt_id,'fence',fence,'all_checks_pass',
 run_id=old_run_id AND attempt_id<>old_attempt_id AND state='running' AND fence=2
 AND lease_until>clock_timestamp() AND attempt_until>lease_until
 AND (SELECT count(*) FROM reivro_cloud.runs WHERE task_submission_id IS NOT NULL)=1
 AND (SELECT count(*) FROM reivro_cloud.execution_leases)=1
 AND (SELECT count(*) FROM reivro_cloud.events e WHERE e.project_id=t.project_id AND e.subject=t.run_id AND e.actor=t.worker_id AND e.kind='lease_claim')=2
 AND (SELECT count(*) FROM reivro_cloud.events e WHERE e.project_id=t.project_id AND e.subject=t.submission_id AND e.actor=t.worker_id AND e.kind='task_claim')=2
 AND (SELECT count(*) FROM reivro_cloud.events)=18
 AND (SELECT last_value=18 AND is_called FROM reivro_cloud.events_seq_seq)) FROM t;
COMMIT;
