-- Staging only. Read-only gate for one Auth user awaiting Agent membership.
\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='5s';
SELECT set_config('reivro.agent_id', :'agent_id', true) AS cfg_agent,
       set_config('reivro.repository_id', :'repository_id', true) AS cfg_repo \gset
DO $pending$
DECLARE
    agent uuid := current_setting('reivro.agent_id')::uuid;
    repo bigint := current_setting('reivro.repository_id')::bigint;
BEGIN
 IF current_user<>'postgres' OR current_database()<>'postgres'
 OR NOT EXISTS (SELECT FROM supabase_migrations.schema_migrations
      WHERE version='20261126000300' AND name='reivro_control_plane_003')
 OR (SELECT count(*) FROM auth.users)<>6
 OR NOT EXISTS (SELECT FROM auth.users WHERE id=agent
      AND created_at>='2026-11-27T00:00:00Z'::timestamptz AND created_at<=now()
      AND email_confirmed_at IS NOT NULL AND is_anonymous=false)
 OR EXISTS (SELECT FROM reivro_cloud.memberships WHERE user_id=agent)
 OR (SELECT count(*) FROM reivro_cloud.memberships)<>4
 OR (SELECT count(*) FROM reivro_cloud.memberships WHERE role='reviewer')<>2
 OR (SELECT count(*) FROM reivro_cloud.memberships WHERE role='viewer')<>1
 OR (SELECT count(*) FROM reivro_cloud.memberships WHERE role='worker')<>1
 OR EXISTS (SELECT FROM reivro_cloud.memberships WHERE role='agent')
 OR NOT EXISTS (SELECT FROM reivro_cloud.projects p
      JOIN reivro_cloud.memberships m ON m.project_id=p.id
      WHERE p.repository_id=repo GROUP BY p.id
      HAVING count(*)=3 AND count(*) FILTER (WHERE m.role='reviewer')=1
       AND count(*) FILTER (WHERE m.role='viewer')=1
       AND count(*) FILTER (WHERE m.role='worker')=1)
 OR EXISTS (SELECT FROM reivro_cloud.task_contracts)
 OR EXISTS (SELECT FROM reivro_cloud.task_submissions)
 OR EXISTS (SELECT FROM reivro_cloud.task_policies)
 OR EXISTS (SELECT FROM reivro_cloud.task_corrections)
 OR EXISTS (SELECT FROM reivro_cloud.execution_leases)
 OR EXISTS (SELECT FROM reivro_cloud.runs WHERE outcome IS NULL)
 OR (SELECT count(*) FROM reivro_cloud.events)<>12
 OR (SELECT last_value FROM reivro_cloud.events_seq_seq)<>12
 OR NOT (SELECT is_called FROM reivro_cloud.events_seq_seq)
 THEN RAISE EXCEPTION 'Pending Agent inventory differs'; END IF;
END $pending$;
SELECT 'AGENT_A_AUTH_PENDING_MEMBERSHIP_PASS' AS status;
COMMIT;
