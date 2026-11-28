\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT jsonb_build_object('checks',jsonb_build_object(
 'contract',EXISTS(SELECT FROM reivro_cloud.task_contracts WHERE id=:'new_contract_id'::uuid AND digest=:'new_digest'),
 'submission',CASE WHEN :'expected_events'::integer=37 THEN NOT EXISTS(SELECT FROM reivro_cloud.task_submissions WHERE id=:'new_submission_id'::uuid) ELSE EXISTS(SELECT FROM reivro_cloud.task_submissions WHERE id=:'new_submission_id'::uuid AND contract_id=:'new_contract_id'::uuid AND digest=:'new_digest' AND base_sha=:'base_sha' AND head_sha=:'head_sha' AND run_id IS NULL AND result IS NULL) END,
 'journal',(SELECT count(*)=:'expected_events'::integer AND max(seq)=:'expected_events'::integer FROM reivro_cloud.events),
 'sequence',(SELECT last_value=:'expected_events'::integer AND is_called FROM reivro_cloud.events_seq_seq)),
 'all_checks_pass',EXISTS(SELECT FROM reivro_cloud.task_contracts WHERE id=:'new_contract_id'::uuid AND digest=:'new_digest')
 AND (SELECT count(*)=:'expected_events'::integer AND max(seq)=:'expected_events'::integer FROM reivro_cloud.events)
 AND (SELECT last_value=:'expected_events'::integer AND is_called FROM reivro_cloud.events_seq_seq)
 AND CASE WHEN :'expected_events'::integer=37 THEN NOT EXISTS(SELECT FROM reivro_cloud.task_submissions WHERE id=:'new_submission_id'::uuid) ELSE EXISTS(SELECT FROM reivro_cloud.task_submissions WHERE id=:'new_submission_id'::uuid AND contract_id=:'new_contract_id'::uuid AND digest=:'new_digest' AND base_sha=:'base_sha' AND head_sha=:'head_sha' AND run_id IS NULL AND result IS NULL) END);
COMMIT;
