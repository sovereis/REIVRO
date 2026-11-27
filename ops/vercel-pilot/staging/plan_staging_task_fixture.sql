-- Staging only. Generates one private plan and causes no durable writes.
\set ON_ERROR_STOP on
BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';
WITH inputs AS (
    SELECT :'repository_id'::bigint AS repository_id,
           :'reviewer_id'::uuid AS reviewer_id,
           :'agent_id'::uuid AS agent_id,
           :'base_sha'::text AS base_sha,
           :'head_sha'::text AS head_sha
), checked AS (
    SELECT i.*, jsonb_build_object('base_sha',i.base_sha,'criteria',
        jsonb_build_array(jsonb_build_object('kind','exists','path','guide.md'))) AS document
    FROM inputs i
    JOIN reivro_cloud.projects p USING(repository_id)
    JOIN reivro_cloud.memberships r ON r.project_id=p.id AND r.user_id=i.reviewer_id AND r.role='reviewer'
    JOIN reivro_cloud.memberships a ON a.project_id=p.id AND a.user_id=i.agent_id AND a.role='agent'
    WHERE i.base_sha ~ '^[0-9a-f]{40}$' AND i.head_sha ~ '^[0-9a-f]{40}$'
      AND i.base_sha <> i.head_sha
      AND (SELECT md5(prosrc) FROM pg_proc WHERE oid =
           to_regprocedure('reivro_cloud.dispatch(text,jsonb)')) = '5789d2beb5926fbfe2006973dd66d337'
)
SELECT jsonb_build_object(
    'staging_ref','lbklqqqbmeyseeccdqog','repository_id',repository_id,
    'reviewer_id',reviewer_id,'agent_id',agent_id,'base_sha',base_sha,'head_sha',head_sha,
    'contract_id',gen_random_uuid(),'submission_id',gen_random_uuid(),
    'digest',encode(sha256(convert_to(document::text,'UTF8')),'hex')
) AS plan FROM checked \gset
\echo :plan
COMMIT;
