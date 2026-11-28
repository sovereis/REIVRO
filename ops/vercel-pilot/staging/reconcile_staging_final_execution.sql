\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT jsonb_build_object('events',(SELECT count(*) FROM reivro_cloud.events),
 'sequence',(SELECT last_value FROM reivro_cloud.events_seq_seq),'sequence_called',(SELECT is_called FROM reivro_cloud.events_seq_seq),
 'submission_result',(SELECT result FROM reivro_cloud.task_submissions WHERE id=:'submission_id'::uuid),
 'run',(SELECT jsonb_build_object('id',id,'outcome',outcome,'report',report) FROM reivro_cloud.runs WHERE task_submission_id=:'submission_id'::uuid),
 'lease',(SELECT jsonb_build_object('state',state,'fence',fence,'attempt_id',attempt_id,'lease_until',lease_until,'attempt_until',attempt_until) FROM reivro_cloud.execution_leases WHERE run_id=(SELECT run_id FROM reivro_cloud.task_submissions WHERE id=:'submission_id'::uuid)));
COMMIT;
