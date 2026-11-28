\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT jsonb_build_object(
 'journal',(SELECT count(*) FROM reivro_cloud.events),
 'sequence',(SELECT last_value FROM reivro_cloud.events_seq_seq),
 'sequence_called',(SELECT is_called FROM reivro_cloud.events_seq_seq),
 'submission',(SELECT jsonb_build_object('id',s.id,'run_id',s.run_id,'result_is_null',s.result IS NULL) FROM reivro_cloud.task_submissions s WHERE s.id=:'submission_id'::uuid),
 'run',(SELECT jsonb_build_object('id',r.id,'outcome',r.outcome,'report_is_null',r.report IS NULL) FROM reivro_cloud.runs r WHERE r.id=:'run_id'::uuid),
 'lease',(SELECT jsonb_build_object('state',l.state,'fence',l.fence,'attempt_id',l.attempt_id,'lease_until',l.lease_until,'attempt_until',l.attempt_until) FROM reivro_cloud.execution_leases l WHERE l.run_id=:'run_id'::uuid),
 'event_counts',(SELECT jsonb_object_agg(kind,n) FROM (SELECT kind,count(*) n FROM reivro_cloud.events WHERE subject IN (:'submission_id'::uuid,:'run_id'::uuid) GROUP BY kind) q),
 'first_run',(SELECT jsonb_build_object('state',l.state,'fence',l.fence,'result_status',s.result->>'status','outcome',r.outcome,'report_matches_result',r.report=s.result) FROM reivro_cloud.task_submissions s JOIN reivro_cloud.runs r ON (r.project_id,r.id)=(s.project_id,s.run_id) JOIN reivro_cloud.execution_leases l ON (l.project_id,l.run_id)=(r.project_id,r.id) WHERE s.id=:'original_submission_id'::uuid));
COMMIT;
