\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH old AS (
 SELECT s.id,s.result,r.outcome,r.report,l.state,l.fence,l.attempt_id
 FROM reivro_cloud.task_submissions s
 JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id)
 JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id)
 WHERE s.id IN (:'first_submission_id'::uuid,:'second_submission_id'::uuid,
  :'third_submission_id'::uuid,:'fourth_submission_id'::uuid)
), n AS (
 SELECT s.id,s.contract_id,s.digest,s.head_sha,s.run_id,s.result,r.outcome,r.report,
  l.state,l.fence,l.attempt_id
 FROM reivro_cloud.task_submissions s
 JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id)
 JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id)
 WHERE s.id=:'new_submission_id'::uuid
), ec AS (
 SELECT
  count(*) FILTER(WHERE kind='task_approve_contract' AND subject=:'new_contract_id'::uuid) approvals,
  count(*) FILTER(WHERE kind='task_submit' AND subject=:'new_submission_id'::uuid) submits,
  count(*) FILTER(WHERE kind='task_claim' AND subject=:'new_submission_id'::uuid) claims,
  count(*) FILTER(WHERE kind='lease_claim' AND subject IN (SELECT run_id FROM n)) lease_claims,
  count(*) FILTER(WHERE subject IN (:'new_submission_id'::uuid,(SELECT run_id FROM n)) AND kind IN ('task_renew','task_fail','task_finish','lease_failure','lease_complete')) forbidden
 FROM reivro_cloud.events
), checks AS (
 SELECT jsonb_build_object(
  'one_contract',(SELECT count(*)=1 FROM reivro_cloud.task_contracts WHERE id=:'new_contract_id'::uuid AND digest=:'new_digest'),
  'one_submission',(SELECT count(*)=1 FROM n WHERE contract_id=:'new_contract_id'::uuid AND digest=:'new_digest' AND head_sha=:'head_sha'),
  'one_run_lease_attempt',(SELECT count(*)=1 FROM n WHERE state='running' AND fence=1 AND attempt_id IS NOT NULL AND result IS NULL AND outcome IS NULL AND report IS NULL),
  'audit_shape',(SELECT approvals=1 AND submits=1 AND claims=2 AND lease_claims=1 AND forbidden=0 FROM ec),
  'journal_55',(SELECT count(*)=55 AND min(seq)=1 AND max(seq)=55 FROM reivro_cloud.events),
  'sequence_55_true',(SELECT last_value=55 AND is_called FROM reivro_cloud.events_seq_seq),
  'first_preserved',(SELECT count(*)=1 FROM old WHERE id=:'first_submission_id'::uuid AND state='completed' AND fence=3 AND attempt_id IS NULL AND result->>'status'='VERIFIED' AND outcome='INCONCLUSIVE' AND report=result),
  'second_preserved',(SELECT count(*)=1 FROM old WHERE id=:'second_submission_id'::uuid AND state='terminal' AND fence=3 AND attempt_id IS NULL AND result IS NULL AND outcome='ERROR' AND report IS NULL),
  'third_preserved',(SELECT count(*)=1 FROM old WHERE id=:'third_submission_id'::uuid AND state='running' AND fence=1 AND attempt_id IS NOT NULL AND result IS NULL AND outcome IS NULL AND report IS NULL),
  'fourth_preserved',(SELECT count(*)=1 FROM old WHERE id=:'fourth_submission_id'::uuid AND state='retryable' AND fence=1 AND attempt_id IS NULL AND result IS NULL AND outcome IS NULL AND report IS NULL),
  'inventory',(SELECT count(*)=5 FROM reivro_cloud.task_contracts) AND (SELECT count(*)=5 FROM reivro_cloud.task_submissions) AND (SELECT count(*)=5 FROM reivro_cloud.runs WHERE task_submission_id IS NOT NULL) AND (SELECT count(*)=5 FROM reivro_cloud.execution_leases),
  'no_prepared_xacts',(SELECT count(*)=0 FROM pg_prepared_xacts)
 ) value
)
SELECT jsonb_build_object(
 'checks',value,
 'all_checks_pass',NOT EXISTS(SELECT FROM jsonb_each(value)e WHERE e.value IS DISTINCT FROM 'true'::jsonb),
 'journal',(SELECT count(*) FROM reivro_cloud.events),'run_id',(SELECT run_id FROM n),
 'attempt_id',(SELECT attempt_id FROM n),'fence',(SELECT fence FROM n),'state',(SELECT state FROM n)
) FROM checks;
COMMIT;
