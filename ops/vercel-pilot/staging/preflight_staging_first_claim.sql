\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='20s';
WITH t AS (
 SELECT p.*, :'contract_id'::uuid contract_id, :'submission_id'::uuid submission_id,
  :'agent_id'::uuid agent_id, :'digest'::text digest, :'base_sha'::text base_sha, :'head_sha'::text head_sha
 FROM reivro_cloud.projects p WHERE p.repository_id=:'repository_id'::bigint
), ok AS (
 SELECT t.* FROM t
 WHERE EXISTS(SELECT 1 FROM reivro_cloud.task_contracts c WHERE c.project_id=t.id AND c.id=t.contract_id AND c.version=1 AND c.digest=t.digest AND c.document->>'base_sha'=t.base_sha)
 AND EXISTS(SELECT 1 FROM reivro_cloud.task_submissions s WHERE s.project_id=t.id AND s.id=t.submission_id AND s.actor=t.agent_id AND s.contract_id=t.contract_id AND s.digest=t.digest AND s.base_sha=t.base_sha AND s.head_sha=t.head_sha AND s.verifier='task-completion-v1' AND s.run_id IS NULL AND s.result IS NULL)
 AND (SELECT count(*) FROM reivro_cloud.task_contracts)=1 AND (SELECT count(*) FROM reivro_cloud.task_submissions)=1
 AND NOT EXISTS(SELECT 1 FROM reivro_cloud.runs WHERE task_submission_id IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM reivro_cloud.execution_leases)
 AND (SELECT count(*) FROM reivro_cloud.events)=14
 AND (SELECT last_value=14 AND is_called FROM reivro_cloud.events_seq_seq)
)
SELECT jsonb_build_object('installation_id',installation_id,'repository',repository,'base_ref',trusted_base,
 'worker_id',(SELECT user_id FROM reivro_cloud.memberships WHERE project_id=ok.id AND role='worker')) FROM ok;
COMMIT;
