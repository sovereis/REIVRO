-- Staging only. Read-only reconciliation after the first Agent submission.
\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='20s';
WITH target AS (
 SELECT p.id AS project_id,
        :'contract_id'::uuid AS contract_id,
        :'submission_id'::uuid AS submission_id,
        :'reviewer_id'::uuid AS reviewer_id,
        :'agent_id'::uuid AS agent_id,
        :'digest'::text AS digest,
        :'base_sha'::text AS base_sha,
        :'head_sha'::text AS head_sha
 FROM reivro_cloud.projects p
 WHERE p.repository_id=:'repository_id'::bigint
), result AS (
 SELECT
  (SELECT count(*) FROM target)=1 AS project_ok,
  EXISTS (SELECT 1 FROM target t JOIN reivro_cloud.task_contracts c
    ON c.project_id=t.project_id AND c.id=t.contract_id
    WHERE c.version=1 AND c.digest=t.digest
      AND c.digest=encode(sha256(convert_to(c.document::text,'UTF8')),'hex')
      AND c.document->>'base_sha'=t.base_sha
      AND c.document->'criteria'='[{"kind":"exists","path":"guide.md"}]'::jsonb) AS contract_ok,
  EXISTS (SELECT 1 FROM target t JOIN reivro_cloud.task_submissions s
    ON s.project_id=t.project_id AND s.id=t.submission_id
    WHERE s.actor=t.agent_id AND s.contract_id=t.contract_id AND s.version=1
      AND s.digest=t.digest AND s.base_sha=t.base_sha AND s.head_sha=t.head_sha
      AND s.verifier='task-completion-v1' AND s.parent IS NULL
      AND s.run_id IS NULL AND s.result IS NULL AND NOT s.confirmed) AS submission_ok,
  (SELECT count(*) FROM reivro_cloud.task_contracts)=1 AS one_contract,
  (SELECT count(*) FROM reivro_cloud.task_submissions)=1 AS one_submission,
  (SELECT count(*) FROM target t JOIN reivro_cloud.events e
    ON e.project_id=t.project_id AND e.subject=t.contract_id
    WHERE e.actor=t.reviewer_id AND e.kind='task_approve_contract')=1 AS approval_event_ok,
  (SELECT count(*) FROM target t JOIN reivro_cloud.events e
    ON e.project_id=t.project_id AND e.subject=t.submission_id
    WHERE e.actor=t.agent_id AND e.kind='task_submit')=1 AS submission_event_ok,
  NOT EXISTS (SELECT 1 FROM reivro_cloud.runs WHERE task_submission_id IS NOT NULL) AS no_task_run,
  NOT EXISTS (SELECT 1 FROM reivro_cloud.execution_leases) AS no_leases,
  NOT EXISTS (SELECT 1 FROM reivro_cloud.runs WHERE outcome IS NULL) AS no_pending_runs,
  (SELECT count(*) FROM reivro_cloud.events)=14 AS events_fourteen,
  (SELECT last_value=14 AND is_called FROM reivro_cloud.events_seq_seq) AS sequence_fourteen
)
SELECT *, (SELECT bool_and(value::boolean) FROM jsonb_each_text(to_jsonb(result))) AS all_checks_pass
FROM result;
COMMIT;
