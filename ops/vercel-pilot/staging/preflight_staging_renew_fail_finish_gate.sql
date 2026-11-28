\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH p AS (SELECT * FROM reivro_cloud.projects WHERE repository_id=:'repository_id'::bigint),
f AS (SELECT s.id,s.result,r.outcome,r.report,l.state,l.fence,l.attempt_id FROM p JOIN reivro_cloud.task_submissions s ON s.project_id=p.id JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id) JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id) WHERE s.id IN (:'first_submission_id'::uuid,:'second_submission_id'::uuid,:'third_submission_id'::uuid)),
doc AS (SELECT jsonb_build_object('base_sha',:'base_sha'::text,'criteria',jsonb_build_array(jsonb_build_object('kind','exists','path','guide.md'))) document),
checks AS (SELECT jsonb_build_object(
 'project_unique',(SELECT count(*) FROM p)=1,
 'first_preserved',(SELECT count(*)=1 FROM f WHERE id=:'first_submission_id'::uuid AND state='completed' AND fence=3 AND attempt_id IS NULL AND result->>'status'='VERIFIED' AND outcome='INCONCLUSIVE' AND report=result),
 'second_preserved',(SELECT count(*)=1 FROM f WHERE id=:'second_submission_id'::uuid AND state='terminal' AND fence=3 AND attempt_id IS NULL AND result IS NULL AND outcome='ERROR' AND report IS NULL),
 'third_preserved',(SELECT count(*)=1 FROM f WHERE id=:'third_submission_id'::uuid AND state='running' AND fence=1 AND attempt_id IS NOT NULL AND result IS NULL AND outcome IS NULL AND report IS NULL),
 'journal_43',(SELECT count(*)=43 AND min(seq)=1 AND max(seq)=43 FROM reivro_cloud.events),'sequence_43_true',(SELECT last_value=43 AND is_called FROM reivro_cloud.events_seq_seq),
 'inventory',(SELECT count(*)=3 FROM reivro_cloud.task_contracts) AND (SELECT count(*)=3 FROM reivro_cloud.task_submissions) AND (SELECT count(*)=3 FROM reivro_cloud.runs WHERE task_submission_id IS NOT NULL) AND (SELECT count(*)=3 FROM reivro_cloud.execution_leases),
 'new_ids_absent',NOT EXISTS(SELECT FROM reivro_cloud.task_contracts WHERE id=:'new_contract_id'::uuid) AND NOT EXISTS(SELECT FROM reivro_cloud.task_submissions WHERE id=:'new_submission_id'::uuid),
 'no_prepared_xacts',(SELECT count(*)=0 FROM pg_prepared_xacts),
 'dispatch_fingerprints',(SELECT md5(prosrc)='3c56d88c40c4a66f564fa4d51fca0930' FROM pg_proc WHERE oid='reivro_cloud.task_dispatch(text,jsonb)'::regprocedure) AND (SELECT md5(prosrc)='e76a6ec5da5b3a2d9122cbd20e52f9d8' FROM pg_proc WHERE oid='reivro_cloud.execution_dispatch(text,jsonb,uuid)'::regprocedure)
) value)
SELECT jsonb_build_object('checks',value,'all_checks_pass',NOT EXISTS(SELECT FROM jsonb_each(value)e WHERE e.value IS DISTINCT FROM 'true'::jsonb),'installation_id',(SELECT installation_id FROM p),'repository',(SELECT repository FROM p),'base_ref',(SELECT trusted_base FROM p),'reviewer_id',(SELECT user_id FROM reivro_cloud.memberships m JOIN p ON p.id=m.project_id WHERE role='reviewer'),'agent_id',(SELECT user_id FROM reivro_cloud.memberships m JOIN p ON p.id=m.project_id WHERE role='agent'),'worker_id',(SELECT user_id FROM reivro_cloud.memberships m JOIN p ON p.id=m.project_id WHERE role='worker'),'contract_document',(SELECT document FROM doc),'contract_digest',(SELECT encode(sha256(convert_to(document::text,'UTF8')),'hex') FROM doc)) FROM checks;
COMMIT;
