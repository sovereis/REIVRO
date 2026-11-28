\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT jsonb_build_object('all_checks_pass',
 EXISTS(SELECT FROM reivro_cloud.task_contracts c JOIN reivro_cloud.projects p ON p.id=c.project_id
  WHERE p.repository_id=:'repository_id'::bigint AND c.id=:'new_contract_id'::uuid AND c.version=1 AND c.digest=:'new_digest')
 AND (:'expected_events'::integer=22 OR EXISTS(SELECT FROM reivro_cloud.task_submissions s JOIN reivro_cloud.projects p ON p.id=s.project_id
  WHERE p.repository_id=:'repository_id'::bigint AND s.id=:'new_submission_id'::uuid AND s.contract_id=:'new_contract_id'::uuid
  AND s.digest=:'new_digest' AND s.base_sha=:'base_sha' AND s.head_sha=:'head_sha' AND s.run_id IS NULL AND s.result IS NULL))
 AND (SELECT count(*) FROM reivro_cloud.events)=:'expected_events'::integer
 AND (SELECT last_value=:'expected_events'::integer AND is_called FROM reivro_cloud.events_seq_seq));
COMMIT;
