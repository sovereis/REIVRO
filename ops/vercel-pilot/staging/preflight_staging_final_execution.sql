\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH t AS (
 SELECT p.id project_id,p.installation_id,p.repository,p.trusted_base,
  s.id submission_id,s.run_id,s.contract_id,s.digest,s.base_sha,s.head_sha,s.verifier,s.policy_set,s.result,
  r.worker,r.outcome,r.report,l.attempt_id,l.fence,l.state,l.lease_until,l.attempt_until,
  (SELECT document FROM reivro_cloud.task_contracts c WHERE (c.project_id,c.id,c.version,c.digest)=(s.project_id,s.contract_id,s.version,s.digest)) contract
 FROM reivro_cloud.projects p JOIN reivro_cloud.task_submissions s ON s.project_id=p.id
 JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id)
 JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id)
 WHERE p.repository_id=:'repository_id'::bigint AND s.id=:'submission_id'::uuid
  AND s.contract_id=:'contract_id'::uuid AND s.digest=:'digest' AND s.base_sha=:'base_sha' AND s.head_sha=:'head_sha'
  AND s.verifier='task-completion-v1' AND s.result IS NULL AND r.outcome IS NULL AND r.report IS NULL
  AND r.task_submission_id=s.id AND l.state='running' AND l.fence=2 AND l.attempt_id IS NOT NULL
  AND l.lease_until<=clock_timestamp() AND l.attempt_until<=clock_timestamp()
  AND (SELECT document FROM reivro_cloud.task_contracts c WHERE (c.project_id,c.id,c.version,c.digest)=(s.project_id,s.contract_id,s.version,s.digest))
      =jsonb_build_object('base_sha',:'base_sha'::text,'criteria',jsonb_build_array(jsonb_build_object('kind','exists','path','guide.md')))
  AND (SELECT count(*) FROM reivro_cloud.runs WHERE task_submission_id IS NOT NULL)=1
  AND (SELECT count(*) FROM reivro_cloud.execution_leases)=1
  AND (SELECT count(*) FROM reivro_cloud.events)=18
  AND (SELECT last_value=18 AND is_called FROM reivro_cloud.events_seq_seq)
)
SELECT jsonb_build_object('installation_id',installation_id,'repository',repository,'base_ref',trusted_base,
 'worker_id',worker,'run_id',run_id,'old_attempt_id',attempt_id,'policy_set',policy_set) FROM t;
COMMIT;
