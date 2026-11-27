-- Staging only. Verify the new Agent and preservation of the original inventory.
\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='15s';
SELECT set_config('reivro.agent_id', :'agent_id', true) AS agent,
       set_config('reivro.repository_id', :'repository_id', true) AS repo \gset
DO $$
DECLARE
    agent uuid := current_setting('reivro.agent_id')::uuid;
    repo bigint := current_setting('reivro.repository_id')::bigint;
BEGIN
    IF (SELECT count(*) FROM auth.users) <> 6
       OR (SELECT encode(sha256(convert_to(string_agg(id::text,E'\n'
            ORDER BY id),'UTF8')),'hex') FROM auth.users WHERE id<>agent)
          IS DISTINCT FROM '50c800cec24f925111e15977d39b8f08c3df18705df6eb682ffbd3c5e4e138ef'
       OR (SELECT count(*) FROM reivro_cloud.memberships) <> 5
       OR (SELECT encode(sha256(convert_to(string_agg(to_jsonb(m)::text,E'\n'
            ORDER BY to_jsonb(m)::text COLLATE "C"),'UTF8')),'hex')
           FROM reivro_cloud.memberships m WHERE m.user_id<>agent)
          IS DISTINCT FROM 'e8d79feb721073d239a3e7c79cb9a229c2d71a4f125b417d2c7f4e823e2fad76'
       OR NOT EXISTS (SELECT FROM reivro_cloud.memberships m
           JOIN reivro_cloud.projects p ON p.id=m.project_id
           WHERE m.user_id=agent AND m.role='agent' AND p.repository_id=repo)
       OR NOT EXISTS (SELECT FROM auth.users WHERE id=agent
           AND email_confirmed_at IS NOT NULL AND is_anonymous=false)
       OR (SELECT count(*) FROM reivro_cloud.memberships m
           JOIN reivro_cloud.projects p ON p.id=m.project_id
           WHERE p.repository_id=repo AND m.role IN ('reviewer','viewer','worker')) <> 3
    THEN RAISE EXCEPTION 'Agent or original inventory differs'; END IF;
END $$;
SELECT 'AGENT_A_INVENTORY_PASS' AS status;
COMMIT;
