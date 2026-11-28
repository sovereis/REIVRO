\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH n AS (SELECT s.id,s.run_id,s.result,r.outcome,r.report,l.state,l.fence,l.attempt_id,l.lease_until,l.attempt_until FROM reivro_cloud.task_submissions s JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id) JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id) WHERE s.id=:'new_submission_id'::uuid),
old AS (SELECT s.id,s.result,r.outcome,r.report,l.state,l.fence,l.attempt_id,l.lease_until,l.attempt_until FROM reivro_cloud.task_submissions s JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id) JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id) WHERE s.id IN (:'first_submission_id'::uuid,:'second_submission_id'::uuid)),
checks AS (SELECT jsonb_build_object(
 'new_task_unique',(SELECT count(*) FROM n)=1,'one_run',(SELECT count(*)=3 FROM reivro_cloud.runs WHERE task_submission_id IS NOT NULL),'one_lease',(SELECT count(*)=3 FROM reivro_cloud.execution_leases),
 'running_fence_1',(SELECT state='running' AND fence=1 FROM n),'one_attempt',(SELECT attempt_id IS NOT NULL AND lease_until>clock_timestamp() AND attempt_until>=lease_until FROM n),
 'no_result',(SELECT result IS NULL AND outcome IS NULL AND report IS NULL FROM n),'one_lease_claim',(SELECT count(*)=1 FROM reivro_cloud.events WHERE kind='lease_claim' AND subject=(SELECT run_id FROM n)),
 'four_task_claim',(SELECT count(*)=4 FROM reivro_cloud.events WHERE kind='task_claim' AND subject=:'new_submission_id'::uuid),'no_other_transitions',(SELECT count(*)=0 FROM reivro_cloud.events WHERE subject IN (:'new_submission_id'::uuid,(SELECT run_id FROM n)) AND kind IN ('task_renew','task_fail','task_finish','lease_failure')),
 'journal_43',(SELECT count(*)=43 AND min(seq)=1 AND max(seq)=43 FROM reivro_cloud.events),'sequence_43_true',(SELECT last_value=43 AND is_called FROM reivro_cloud.events_seq_seq),
 'first_preserved',(SELECT count(*)=1 FROM old WHERE id=:'first_submission_id'::uuid AND state='completed' AND fence=3 AND attempt_id IS NULL AND result->>'status'='VERIFIED' AND outcome='INCONCLUSIVE' AND report=result),
 'second_preserved',(SELECT count(*)=1 FROM old WHERE id=:'second_submission_id'::uuid AND state='terminal' AND fence=3 AND attempt_id IS NULL AND result IS NULL AND outcome='ERROR' AND report IS NULL),
 'no_prepared_xacts',(SELECT count(*)=0 FROM pg_prepared_xacts)) value)
SELECT jsonb_build_object('checks',value,'run_id',(SELECT run_id FROM n),'attempt_id',(SELECT attempt_id FROM n),'all_checks_pass',NOT EXISTS(SELECT FROM jsonb_each(value) e WHERE e.value IS DISTINCT FROM 'true'::jsonb)) FROM checks;
COMMIT;
