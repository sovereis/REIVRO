-- Staging post-003 audit only. Not a migration. Never replay 001/002/003.
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
 IF current_user<>'postgres' OR current_database()<>'postgres'
 OR EXISTS(SELECT FROM (WITH rows AS (
SELECT 'auth.users'::text AS table_name,to_jsonb(t) AS doc FROM auth.users t
UNION ALL
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
), names(table_name) AS (VALUES ('auth.users'),('reivro_cloud.projects'),('reivro_cloud.memberships'),('reivro_cloud.runs'),('reivro_cloud.findings'),('reivro_cloud.protections'),('reivro_cloud.events'))
SELECT n.table_name, count(r.doc) AS rows,
 encode(sha256(convert_to(coalesce(string_agg(r.doc::text,E'\n' ORDER BY r.doc::text COLLATE "C"),''),'UTF8')),'hex') AS sha256
FROM names n LEFT JOIN rows r ON r.table_name=n.table_name GROUP BY n.table_name ORDER BY n.table_name) actual
 FULL JOIN (VALUES ('auth.users','cc37fe0aba790380a60dce3fab3c392b40cc3629afdf3c09caacc79226bbcee8'),('reivro_cloud.events','b28c1a5d549a5755bf99e2de42dd758e06c19baaff255c24cfb0e849209c7ad4'),('reivro_cloud.findings','cc657cb4220e3ac7b3e7e86d0a4dd8e870c176f65ceba2b7f7bfe0ee544205f9'),('reivro_cloud.memberships','e8d79feb721073d239a3e7c79cb9a229c2d71a4f125b417d2c7f4e823e2fad76'),('reivro_cloud.projects','2964cf57f722ca0c03d8a88f8560e33b272be50d877813f490ec73faef9da0d7'),('reivro_cloud.protections','e87c12ad0c72f3f041fe41a89824ab21fc634d0faa8c18f53e3cac2d348a1b93'),('reivro_cloud.runs','bf369f2ccc9a0a5c5e9dbc3c1f6fbb55ff15adb4651d003ea632c5866d061534')) expected(table_name,sha256) USING(table_name)
 WHERE actual.sha256 IS DISTINCT FROM expected.sha256)
 OR (SELECT last_value FROM reivro_cloud.events_seq_seq)<>12
 OR NOT (SELECT is_called FROM reivro_cloud.events_seq_seq)
 OR (SELECT count(*) FROM reivro_cloud.runs WHERE outcome IS NULL)<>0
 OR (SELECT count(*) FROM reivro_cloud.protections WHERE state='revoked')<>1
 THEN RAISE EXCEPTION 'Preserved-data baseline differs'; END IF;
END $data_guard$;
DO $check$ BEGIN IF NOT EXISTS(SELECT FROM supabase_migrations.schema_migrations WHERE version='20261126000300' AND name='reivro_control_plane_003' AND cardinality(statements)=1 AND encode(sha256(convert_to(statements[1],'UTF8')),'hex')='6ffe1673191eac4335c3798daf9d3c34cb01551f9f674dd9ebdfa31215c88c19' AND idempotency_key='reivro:20261126000300:6ffe1673191eac4335c3798daf9d3c34cb01551f9f674dd9ebdfa31215c88c19') THEN RAISE EXCEPTION '003 ledger missing'; END IF; END $check$;

DO $ledger_guard$
BEGIN
 IF (SELECT count(*) FROM supabase_migrations.schema_migrations)<>3
 OR NOT EXISTS(SELECT FROM supabase_migrations.schema_migrations
  WHERE version='20261123210041' AND name='reivro_firewall_staging'
   AND cardinality(statements)=1
   AND encode(sha256(convert_to(statements[1],'UTF8')),'hex')='8f40e7609c9116fe63a422851730ebf0685d4e64cdfcde9b69c24577612591f1')
 OR NOT EXISTS(SELECT FROM supabase_migrations.schema_migrations
  WHERE version='20261126000200' AND name='reivro_durable_execution_002'
   AND cardinality(statements)=1
   AND encode(sha256(convert_to(statements[1],'UTF8')),'hex')='2ea6824530ffed52a33f6ac449f0b396f19b24d511eef092fc713bea10c39fb4'
   AND idempotency_key='reivro:20261126000200:2ea6824530ffed52a33f6ac449f0b396f19b24d511eef092fc713bea10c39fb4')
 THEN RAISE EXCEPTION 'Migration ledger differs from audited 001/002/003'; END IF;
END $ledger_guard$;
SELECT 'AUDIT_003_READONLY_PASS' AS result;
COMMIT;
