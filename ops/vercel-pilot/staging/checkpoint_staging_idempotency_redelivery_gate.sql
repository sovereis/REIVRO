\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH c AS (
 SELECT * FROM reivro_cloud.task_contracts WHERE id=:'new_contract_id'::uuid
), s AS (
 SELECT * FROM reivro_cloud.task_submissions WHERE id=:'new_submission_id'::uuid
), r AS (
 SELECT r.* FROM reivro_cloud.runs r JOIN s ON (r.project_id,r.id)=(s.project_id,s.run_id)
), l AS (
 SELECT l.* FROM reivro_cloud.execution_leases l JOIN r ON (l.project_id,l.run_id)=(r.project_id,r.id)
), ec AS (
 SELECT
  count(*) FILTER(WHERE kind='task_approve_contract' AND subject=:'new_contract_id'::uuid) approvals,
  count(*) FILTER(WHERE kind='task_submit' AND subject=:'new_submission_id'::uuid) submits,
  count(*) FILTER(WHERE kind='task_claim' AND subject=:'new_submission_id'::uuid) claims,
  count(*) FILTER(WHERE kind='lease_claim' AND subject IN (SELECT id FROM r)) lease_claims
 FROM reivro_cloud.events
), checks AS (
 SELECT jsonb_build_object(
  'contract',(SELECT count(*)=1 FROM c WHERE digest=:'new_digest'),
  'submission',CASE WHEN :'expected_events'::int=51 THEN NOT EXISTS(SELECT FROM s) ELSE EXISTS(SELECT FROM s WHERE contract_id=:'new_contract_id'::uuid AND digest=:'new_digest' AND head_sha=:'head_sha') END,
  'run',CASE WHEN :'expected_events'::int<54 THEN NOT EXISTS(SELECT FROM r) ELSE EXISTS(SELECT FROM r) END,
  'lease',CASE WHEN :'expected_events'::int<54 THEN NOT EXISTS(SELECT FROM l) ELSE EXISTS(SELECT FROM l WHERE state='running' AND fence=1 AND attempt_id IS NOT NULL) END,
  'event_shape',(SELECT approvals=1 AND submits=CASE WHEN :'expected_events'::int=51 THEN 0 ELSE 1 END AND claims=:'expected_claim_events'::int AND lease_claims=CASE WHEN :'expected_events'::int<54 THEN 0 ELSE 1 END FROM ec),
  'single_durable_effect',(SELECT count(*) FROM r)<=1 AND (SELECT count(*) FROM l)<=1,
  'journal',(SELECT count(*)=:'expected_events'::int AND max(seq)=:'expected_events'::int FROM reivro_cloud.events),
  'sequence',(SELECT last_value=:'expected_events'::int AND is_called FROM reivro_cloud.events_seq_seq),
  'no_prepared_xacts',(SELECT count(*)=0 FROM pg_prepared_xacts)
 ) value
)
SELECT jsonb_build_object(
 'checks',value,
 'all_checks_pass',NOT EXISTS(SELECT FROM jsonb_each(value)e WHERE e.value IS DISTINCT FROM 'true'::jsonb),
 'run_id',(SELECT id FROM r),'attempt_id',(SELECT attempt_id FROM l),'fence',(SELECT fence FROM l),
 'lease_until',(SELECT lease_until FROM l),'journal',(SELECT count(*) FROM reivro_cloud.events)
) FROM checks;
COMMIT;
