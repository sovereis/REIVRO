-- Staging only. Report the known plan's persisted state without returning rows.
\set ON_ERROR_STOP on
BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';
WITH target AS (
    SELECT p.id, :'contract_id'::uuid AS contract_id, :'submission_id'::uuid AS submission_id,
           :'digest'::text AS digest, :'reviewer_id'::uuid AS reviewer_id,
           :'agent_id'::uuid AS agent_id, :'head_sha'::text AS head_sha
    FROM reivro_cloud.projects p WHERE p.repository_id=:'repository_id'::bigint
)
SELECT EXISTS (SELECT FROM target) AS project_exists,
       EXISTS (SELECT FROM target t JOIN reivro_cloud.task_contracts c ON c.project_id=t.id
               WHERE c.id=t.contract_id AND c.version=1 AND c.digest=t.digest) AS contract_matches,
       EXISTS (SELECT FROM target t JOIN reivro_cloud.task_submissions s ON s.project_id=t.id
               WHERE s.id=t.submission_id AND s.actor=t.agent_id AND s.contract_id=t.contract_id
                 AND s.version=1 AND s.digest=t.digest AND s.head_sha=t.head_sha) AS submission_matches,
       (SELECT count(*) FROM target t JOIN reivro_cloud.events e ON e.project_id=t.id
        WHERE e.kind='task_approve_contract' AND e.subject=t.contract_id AND e.actor=t.reviewer_id) AS approval_events,
       (SELECT count(*) FROM target t JOIN reivro_cloud.events e ON e.project_id=t.id
        WHERE e.kind='task_submit' AND e.subject=t.submission_id AND e.actor=t.agent_id) AS submission_events;
COMMIT;
