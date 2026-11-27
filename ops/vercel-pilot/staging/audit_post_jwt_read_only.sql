-- REIVRO staging only. Run with psql -X -v ON_ERROR_STOP=1.
-- Cloud baseline from the post-003 audit; Auth inventory from the JWT checkpoint.
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='5s';
DO $$
DECLARE obj text; role_name text;
BEGIN
 IF (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_cloud.execution_dispatch(text,jsonb,uuid)')) IS DISTINCT FROM 'e76a6ec5da5b3a2d9122cbd20e52f9d8'
 OR (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_cloud.dispatch(text,jsonb)')) IS DISTINCT FROM '5789d2beb5926fbfe2006973dd66d337'
 OR (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_cloud.task_dispatch(text,jsonb)')) IS DISTINCT FROM '3c56d88c40c4a66f564fa4d51fca0930'
 OR (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_cloud.dispatch_v1(text,jsonb)')) IS DISTINCT FROM '7b65dd994ca180ed06312d3c0a7820fe'
 OR (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_checks_api.dispatch(text,jsonb)')) IS DISTINCT FROM '33ebec2c2d3ac3c64b6955369778fc61'
 OR (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_checks_api.read_run(bigint,uuid)')) IS DISTINCT FROM '8815aa0cb0ee1f7b6c1d64315bd019d1'
 OR (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_checks_api.task_dispatch(text,jsonb)')) IS DISTINCT FROM '3458700a52910337fea6aca7f57d8f03'
 THEN RAISE EXCEPTION '003 function fingerprint mismatch'; END IF;
 IF EXISTS(SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE ((n.nspname='reivro_cloud' AND p.proname IN ('execution_dispatch','dispatch','task_dispatch','dispatch_v1'))
   OR (n.nspname='reivro_checks_api' AND p.proname IN ('dispatch','task_dispatch','read_run')))
  AND (pg_get_userbyid(p.proowner)<>'postgres'
   OR p.prosecdef IS DISTINCT FROM (n.nspname='reivro_cloud')
   OR p.proconfig IS DISTINCT FROM ARRAY['search_path='||chr(34)||chr(34)])) THEN
  RAISE EXCEPTION 'Unexpected function owner/security/search_path'; END IF;
 FOREACH obj IN ARRAY ARRAY['task_contracts','task_submissions','task_policies','task_corrections','execution_leases'] LOOP
  IF NOT coalesce((SELECT relrowsecurity FROM pg_class WHERE oid=to_regclass('reivro_cloud.'||obj)),false) THEN RAISE EXCEPTION 'Private table RLS missing'; END IF;
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
   IF has_table_privilege(role_name,'reivro_cloud.'||obj,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') THEN RAISE EXCEPTION 'Private table exposed'; END IF;
  END LOOP;
 END LOOP;
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
  IF has_function_privilege(role_name,'reivro_cloud.execution_dispatch(text,jsonb,uuid)','EXECUTE')
   OR has_function_privilege(role_name,'reivro_cloud.dispatch_v1(text,jsonb)','EXECUTE') THEN RAISE EXCEPTION 'Private function exposed'; END IF;
 END LOOP;
 IF NOT has_function_privilege('authenticated','reivro_checks_api.task_dispatch(text,jsonb)','EXECUTE')
 OR NOT has_function_privilege('authenticated','reivro_cloud.task_dispatch(text,jsonb)','EXECUTE')
 OR has_function_privilege('anon','reivro_checks_api.task_dispatch(text,jsonb)','EXECUTE')
 OR has_function_privilege('service_role','reivro_checks_api.task_dispatch(text,jsonb)','EXECUTE')
 OR has_function_privilege('anon','reivro_cloud.task_dispatch(text,jsonb)','EXECUTE')
 OR has_function_privilege('service_role','reivro_cloud.task_dispatch(text,jsonb)','EXECUTE')
 OR EXISTS(SELECT FROM reivro_cloud.task_contracts) OR EXISTS(SELECT FROM reivro_cloud.task_submissions)
 OR EXISTS(SELECT FROM reivro_cloud.task_policies) OR EXISTS(SELECT FROM reivro_cloud.task_corrections)
 OR EXISTS(SELECT FROM reivro_cloud.execution_leases)
 OR EXISTS(SELECT FROM reivro_cloud.runs WHERE task_submission_id IS NOT NULL)
 OR EXISTS(SELECT FROM pg_constraint k JOIN pg_namespace n ON n.oid=k.connamespace WHERE n.nspname='reivro_cloud' AND NOT k.convalidated)
 OR to_regclass('reivro_cloud.one_active_guard') IS NULL THEN RAISE EXCEPTION '003 privilege/history mismatch'; END IF;
 FOREACH obj IN ARRAY ARRAY['syntax_delivery','syntax_revision','task_execution'] LOOP
  IF NOT EXISTS(SELECT FROM pg_index WHERE indexrelid=to_regclass('reivro_cloud.'||obj) AND indisunique AND indisvalid AND indpred IS NOT NULL)
  THEN RAISE EXCEPTION 'Execution index missing or invalid'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT FROM pg_constraint WHERE conrelid='reivro_cloud.runs'::regclass AND contype='f'
  AND confrelid='reivro_cloud.task_submissions'::regclass) THEN RAISE EXCEPTION 'Task run identity FK missing'; END IF;
END $$;
SET LOCAL timezone='UTC';
DO $data_guard$
BEGIN
 IF current_database()<>'postgres'
 OR EXISTS(SELECT FROM (WITH rows AS (
SELECT 'reivro_cloud.projects'::text AS table_name,to_jsonb(t) AS doc FROM reivro_cloud.projects t
UNION ALL
SELECT 'reivro_cloud.memberships'::text AS table_name,to_jsonb(t) AS doc FROM reivro_cloud.memberships t
UNION ALL
SELECT 'reivro_cloud.runs'::text AS table_name,(to_jsonb(t)-'task_submission_id') AS doc FROM reivro_cloud.runs t
UNION ALL
SELECT 'reivro_cloud.findings'::text AS table_name,to_jsonb(t) AS doc FROM reivro_cloud.findings t
UNION ALL
SELECT 'reivro_cloud.protections'::text AS table_name,to_jsonb(t) AS doc FROM reivro_cloud.protections t
UNION ALL
SELECT 'reivro_cloud.events'::text AS table_name,to_jsonb(t) AS doc FROM reivro_cloud.events t
), names(table_name) AS (VALUES ('reivro_cloud.projects'),('reivro_cloud.memberships'),('reivro_cloud.runs'),('reivro_cloud.findings'),('reivro_cloud.protections'),('reivro_cloud.events'))
SELECT n.table_name, count(r.doc) AS rows,
 encode(sha256(convert_to(coalesce(string_agg(r.doc::text,E'\n' ORDER BY r.doc::text COLLATE "C"),''),'UTF8')),'hex') AS sha256
FROM names n LEFT JOIN rows r ON r.table_name=n.table_name GROUP BY n.table_name ORDER BY n.table_name) actual
 FULL JOIN (VALUES ('reivro_cloud.events','b28c1a5d549a5755bf99e2de42dd758e06c19baaff255c24cfb0e849209c7ad4'),('reivro_cloud.findings','cc657cb4220e3ac7b3e7e86d0a4dd8e870c176f65ceba2b7f7bfe0ee544205f9'),('reivro_cloud.memberships','e8d79feb721073d239a3e7c79cb9a229c2d71a4f125b417d2c7f4e823e2fad76'),('reivro_cloud.projects','2964cf57f722ca0c03d8a88f8560e33b272be50d877813f490ec73faef9da0d7'),('reivro_cloud.protections','e87c12ad0c72f3f041fe41a89824ab21fc634d0faa8c18f53e3cac2d348a1b93'),('reivro_cloud.runs','bf369f2ccc9a0a5c5e9dbc3c1f6fbb55ff15adb4651d003ea632c5866d061534')) expected(table_name,sha256) USING(table_name)
 WHERE actual.sha256 IS DISTINCT FROM expected.sha256)
 OR (SELECT last_value FROM reivro_cloud.events_seq_seq)<>12
 OR NOT (SELECT is_called FROM reivro_cloud.events_seq_seq)
 OR (SELECT count(*) FROM reivro_cloud.runs WHERE outcome IS NULL)<>0
 OR (SELECT count(*) FROM reivro_cloud.protections WHERE state='revoked')<>1
 THEN RAISE EXCEPTION 'Preserved-data baseline differs'; END IF;
END $data_guard$;
DO $$
BEGIN
 IF (SELECT count(*) FROM supabase_migrations.schema_migrations) <> 3
 OR NOT EXISTS (SELECT FROM supabase_migrations.schema_migrations WHERE version='20261123210041' AND name='reivro_firewall_staging')
 OR EXISTS (
 SELECT FROM (VALUES
 ('20261126000200','reivro_durable_execution_002','2ea6824530ffed52a33f6ac449f0b396f19b24d511eef092fc713bea10c39fb4'),
 ('20261126000300','reivro_control_plane_003','6ffe1673191eac4335c3798daf9d3c34cb01551f9f674dd9ebdfa31215c88c19')
 ) AS e(version,name,sha)
 WHERE NOT EXISTS (SELECT FROM supabase_migrations.schema_migrations m
 WHERE m.version=e.version AND m.name=e.name AND cardinality(m.statements)=1
 AND m.idempotency_key='reivro:'||e.version||':'||e.sha
 AND encode(sha256(convert_to(m.statements[1],'UTF8')),'hex')=e.sha))
 THEN RAISE EXCEPTION 'Unexpected migration ledger'; END IF;
END $$;
DO $$
BEGIN
 IF current_setting('transaction_read_only') <> 'on' THEN
  RAISE EXCEPTION 'Read-only transaction required';
 END IF;
END $$;
SELECT 'post_jwt_cloud_baseline_pass' AS status,
 current_setting('transaction_read_only') AS read_only,
 (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_cloud.dispatch(text,jsonb)')) AS dispatcher,
 (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_cloud.dispatch_v1(text,jsonb)')) AS alias_v1,
 (SELECT jsonb_agg(version ORDER BY version) FROM supabase_migrations.schema_migrations) AS ledger;
SELECT role, count(*) AS memberships FROM reivro_cloud.memberships
 GROUP BY role ORDER BY role;
DO $auth_check$
DECLARE observed record;
BEGIN
WITH scopes AS (
 SELECT project_id, CASE WHEN count(*)=3 AND count(*) FILTER (WHERE role='reviewer')=1 AND count(*) FILTER (WHERE role='viewer')=1 AND count(*) FILTER (WHERE role='worker')=1 THEN 'a'
 WHEN count(*)=1 AND count(*) FILTER (WHERE role='reviewer')=1 THEN 'b' END scope
 FROM reivro_cloud.memberships GROUP BY project_id
), inventory AS (
 SELECT u.id, CASE WHEN m.user_id IS NULL THEN 'sem-vinculo' ELSE m.role||'-'||s.scope END AS subject,
 u.email_confirmed_at IS NOT NULL AS confirmed, coalesce(u.encrypted_password <> '',false) AS has_password,
 u.is_anonymous, coalesce(u.banned_until > now(),false) AS banned
 FROM auth.users u LEFT JOIN reivro_cloud.memberships m ON m.user_id=u.id
 LEFT JOIN scopes s ON s.project_id=m.project_id
), expected(subject,fingerprint) AS (
 VALUES ('reviewer-a','64844df4046aefa19efb9165a20451e9353ca1c443f95e39aa0ee6ce46247009'),
 ('reviewer-b','cd8a6e034aafa36e81dff66d3940076cd38dadb331f0fb2213eb8cc1f9689d3b'),
 ('viewer-a','9530eb1a6d5cfc101489e129d9db3a5543e44193ef910af1ecc40a16dc35e657'),
 ('worker-a','fb7280fa780a84ee9df26c753beaf7d013f4ff1d004ee109d9c4c65eb81ed4c9'),
 ('sem-vinculo','99ffaac220b79d4040662b434a51c615db81b46566e8e58ce04248639bbd659e')
)
SELECT count(*) AS auth_identities,count(DISTINCT id) AS distinct_uuids,
 count(*) FILTER (WHERE subject='sem-vinculo') AS unlinked,
 count(*) FILTER (WHERE confirmed AND has_password AND NOT is_anonymous AND NOT banned) AS active_email_password_accounts,
 count(*) FILTER (WHERE e.fingerprint=encode(sha256(convert_to(i.subject||':'||i.id::text,'UTF8')),'hex')) AS uuid_role_matches,
 count(DISTINCT i.subject) AS distinct_subjects,
 encode(sha256(convert_to(string_agg(to_jsonb(i)::text,E'\n' ORDER BY i.subject COLLATE "C", i.id),'UTF8')),'hex') AS auth_inventory_sha256
INTO observed
FROM inventory i LEFT JOIN expected e USING(subject);
IF observed.auth_identities <> 5 OR observed.distinct_uuids <> 5
 OR observed.unlinked <> 1 OR observed.active_email_password_accounts <> 5
 OR observed.uuid_role_matches <> 5 OR observed.distinct_subjects <> 5
 OR observed.auth_inventory_sha256 IS DISTINCT FROM '5427ee4bafee7ae297c834518f5780043b974d57a57c91bdb9843fb606350c8c' THEN
 RAISE EXCEPTION 'Auth inventory baseline differs';
END IF;
END $auth_check$;
SELECT 'post_jwt_auth_baseline_pass' AS status, '5427ee4bafee7ae297c834518f5780043b974d57a57c91bdb9843fb606350c8c' AS auth_inventory_sha256;
COMMIT;
