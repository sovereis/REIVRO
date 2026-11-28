\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH p AS (SELECT * FROM reivro_cloud.projects WHERE repository_id=:'repository_id'::bigint),
old AS (
 SELECT s.id,l.fence,l.state,l.attempt_id,l.lease_until,l.attempt_until,s.result,r.outcome,r.report
 FROM p JOIN reivro_cloud.task_submissions s ON s.project_id=p.id
 JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id)
 JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id)
 WHERE s.id=:'original_submission_id'::uuid
), doc AS (
 SELECT jsonb_build_object('base_sha',:'base_sha'::text,'criteria',jsonb_build_array(jsonb_build_object('kind','exists','path','guide.md'))) document
)
SELECT jsonb_build_object(
 'installation_id',p.installation_id,'repository',p.repository,'base_ref',p.trusted_base,
 'reviewer_id',(SELECT user_id FROM reivro_cloud.memberships WHERE project_id=p.id AND role='reviewer'),
 'agent_id',(SELECT user_id FROM reivro_cloud.memberships WHERE project_id=p.id AND role='agent'),
 'worker_id',(SELECT user_id FROM reivro_cloud.memberships WHERE project_id=p.id AND role='worker'),
 'contract_document',doc.document,'contract_digest',encode(sha256(convert_to(doc.document::text,'UTF8')),'hex'),
 'all_checks_pass',old.fence=3 AND old.state='completed' AND old.attempt_id IS NULL
  AND old.lease_until IS NULL AND old.attempt_until IS NULL AND old.result->>'status'='VERIFIED'
  AND old.outcome='INCONCLUSIVE' AND old.report=old.result
  AND NOT EXISTS(SELECT FROM reivro_cloud.task_contracts WHERE project_id=p.id AND id=:'new_contract_id'::uuid)
  AND NOT EXISTS(SELECT FROM reivro_cloud.task_submissions WHERE project_id=p.id AND id=:'new_submission_id'::uuid)
  AND (SELECT count(*) FROM reivro_cloud.events)=21
  AND (SELECT last_value=21 AND is_called FROM reivro_cloud.events_seq_seq)
  AND (SELECT count(*) FROM pg_prepared_xacts)=0)
FROM p CROSS JOIN old CROSS JOIN doc;
COMMIT;
