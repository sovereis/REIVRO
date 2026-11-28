\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT jsonb_build_object('events',(SELECT count(*) FROM reivro_cloud.events),'sequence',(SELECT last_value FROM reivro_cloud.events_seq_seq),
 'contract_exists',EXISTS(SELECT FROM reivro_cloud.task_contracts WHERE id=:'new_contract_id'::uuid),
 'submission',(SELECT jsonb_build_object('id',id,'run_id',run_id,'result',result) FROM reivro_cloud.task_submissions WHERE id=:'new_submission_id'::uuid),
 'lease',(SELECT jsonb_build_object('state',state,'fence',fence,'attempt_id',attempt_id,'lease_until',lease_until,'attempt_until',attempt_until) FROM reivro_cloud.execution_leases WHERE run_id=(SELECT run_id FROM reivro_cloud.task_submissions WHERE id=:'new_submission_id'::uuid)));
COMMIT;
