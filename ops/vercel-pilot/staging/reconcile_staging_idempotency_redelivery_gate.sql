\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT jsonb_build_object(
 'journal',(SELECT count(*) FROM reivro_cloud.events),
 'sequence',(SELECT last_value FROM reivro_cloud.events_seq_seq),
 'contract',(SELECT to_jsonb(c) FROM reivro_cloud.task_contracts c WHERE id=:'new_contract_id'::uuid),
 'submission',(SELECT to_jsonb(s) FROM reivro_cloud.task_submissions s WHERE id=:'new_submission_id'::uuid),
 'run',(SELECT to_jsonb(r) FROM reivro_cloud.runs r WHERE task_submission_id=:'new_submission_id'::uuid),
 'lease',(SELECT to_jsonb(l) FROM reivro_cloud.execution_leases l WHERE run_id=(SELECT run_id FROM reivro_cloud.task_submissions WHERE id=:'new_submission_id'::uuid)),
 'events',(SELECT jsonb_agg(jsonb_build_object('seq',seq,'kind',kind,'subject',subject) ORDER BY seq) FROM reivro_cloud.events WHERE subject IN (:'new_contract_id'::uuid,:'new_submission_id'::uuid,(SELECT run_id FROM reivro_cloud.task_submissions WHERE id=:'new_submission_id'::uuid)))
);
COMMIT;
