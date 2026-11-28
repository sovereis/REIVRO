\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='20s';
WITH t AS (
 SELECT p.id project_id, :'submission_id'::uuid submission_id, :'worker_id'::uuid worker_id
 FROM reivro_cloud.projects p WHERE p.repository_id=:'repository_id'::bigint
), state AS (
 SELECT t.*,s.run_id,l.attempt_id,l.fence,l.state,l.lease_until,l.attempt_until,
        r.delivery,r.worker,r.outcome,r.base_sha,r.head_sha,r.task_submission_id,
        s.policy_set,s.result
 FROM t JOIN reivro_cloud.task_submissions s ON s.project_id=t.project_id AND s.id=t.submission_id
 JOIN reivro_cloud.runs r ON r.project_id=t.project_id AND r.id=s.run_id
 JOIN reivro_cloud.execution_leases l ON l.project_id=t.project_id AND l.run_id=r.id
), checked AS (
 SELECT state.*,
   policy_set='[]'::jsonb AND result IS NULL AS submission_bound,
   task_submission_id=submission_id AND delivery=submission_id AND worker=worker_id AND outcome IS NULL
    AND base_sha='07fc0b907d3aa9659ea7541f80acf6c18586e645'
    AND head_sha='e0d50dd239f8c8c3c39df84187741009f7496d09' AS run_bound,
   state='running' AND fence=1 AND attempt_id IS NOT NULL
    AND lease_until>clock_timestamp() AND attempt_until>lease_until AS lease_bound
 FROM state
)
SELECT jsonb_build_object('run_id',run_id,'attempt_id',attempt_id,'fence',fence,'all_checks_pass',
 submission_bound AND run_bound AND lease_bound
 AND (SELECT count(*) FROM reivro_cloud.runs WHERE task_submission_id IS NOT NULL)=1
 AND (SELECT count(*) FROM reivro_cloud.execution_leases)=1
 AND (SELECT count(*) FROM reivro_cloud.events e WHERE e.project_id=checked.project_id AND e.subject=checked.run_id AND e.actor=checked.worker_id AND e.kind='lease_claim')=1
 AND (SELECT count(*) FROM reivro_cloud.events e WHERE e.project_id=checked.project_id AND e.subject=checked.submission_id AND e.actor=checked.worker_id AND e.kind='task_claim')=1
 AND (SELECT count(*) FROM reivro_cloud.events)=16
 AND (SELECT last_value=16 AND is_called FROM reivro_cloud.events_seq_seq))
FROM checked;
COMMIT;
