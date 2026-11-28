\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH t AS (
 SELECT s.id submission_id,s.run_id,s.result,r.outcome,r.report,l.state,l.fence,l.attempt_id,l.lease_until,l.attempt_until
 FROM reivro_cloud.task_submissions s JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id)
 JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id)
 WHERE s.id=:'submission_id'::uuid
)
SELECT jsonb_build_object('run_id',run_id,'fence',fence,'result_status',result->>'status','run_outcome',outcome,
 'evidence_digest',result->'evidence'->>'digest','all_checks_pass',
 run_id=:'run_id'::uuid AND state='completed' AND fence=3 AND attempt_id IS NULL AND lease_until IS NULL AND attempt_until IS NULL
 AND result->>'status'='VERIFIED' AND result->>'base_sha'=:'base_sha' AND result->>'head_sha'=:'head_sha'
 AND result->>'digest'=:'digest' AND result->>'verifier'='task-completion-v1'
 AND result->'evidence'->>'digest'=:'evidence_digest' AND result->'policy_set'=:'policy_set'::jsonb
 AND outcome='INCONCLUSIVE' AND report=result
 AND (SELECT count(*) FROM reivro_cloud.events)=21
 AND (SELECT last_value=21 AND is_called FROM reivro_cloud.events_seq_seq)
 AND (SELECT count(*) FROM reivro_cloud.events WHERE kind='lease_claim')=3
 AND (SELECT count(*) FROM reivro_cloud.events WHERE kind='task_claim')=3
 AND (SELECT count(*) FROM reivro_cloud.events WHERE kind='task_finish' AND subject=t.submission_id)=1
 AND (SELECT count(*) FROM pg_prepared_xacts)=0) FROM t;
COMMIT;
