-- Staging only. Run through the pinned TLS Session Pooler with psql -X -W.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT set_config('reivro.agent_id', :'agent_id', true) AS cfg_agent,
       set_config('reivro.repository_id', :'repository_id', true) AS cfg_repo,
       set_config('reivro.authorized_after', :'authorized_after', true) AS cfg_time,
       set_config('reivro.approval', :'approval', true) AS cfg_approval \gset

DO $$
DECLARE
    agent uuid := current_setting('reivro.agent_id')::uuid;
    repo bigint := current_setting('reivro.repository_id')::bigint;
    threshold timestamptz := current_setting('reivro.authorized_after')::timestamptz;
    target uuid;
BEGIN
    IF current_setting('reivro.approval') <> 'STAGING-AGENT-APPROVED'
       OR current_user <> 'postgres' OR current_database() <> 'postgres'
       OR threshold > now() OR threshold < now() - interval '24 hours'
       OR (SELECT md5(prosrc) FROM pg_proc WHERE oid =
           to_regprocedure('reivro_cloud.dispatch(text,jsonb)'))
           IS DISTINCT FROM '5789d2beb5926fbfe2006973dd66d337'
       OR NOT EXISTS (SELECT FROM supabase_migrations.schema_migrations
           WHERE version='20261126000300' AND name='reivro_control_plane_003') THEN
        RAISE EXCEPTION 'Approval, staging baseline or authorization timestamp invalid';
    END IF;
    -- Serialize membership changes during the narrow insert.
    LOCK TABLE reivro_cloud.memberships IN SHARE ROW EXCLUSIVE MODE;
    SELECT id INTO STRICT target FROM reivro_cloud.projects WHERE repository_id=repo FOR SHARE;
    IF NOT EXISTS (SELECT FROM auth.users WHERE id=agent AND created_at>=threshold
                   AND created_at<=now() AND email_confirmed_at IS NOT NULL
                   AND is_anonymous=false)
       OR EXISTS (SELECT FROM reivro_cloud.memberships WHERE user_id=agent) THEN
        RAISE EXCEPTION 'Expected new confirmed Auth identity without membership';
    END IF;

    INSERT INTO reivro_cloud.memberships(project_id,user_id,role)
    VALUES(target,agent,'agent');
END $$;
COMMIT;
SELECT 'AGENT_MEMBERSHIP_COMMIT_ACKNOWLEDGED' AS status;
