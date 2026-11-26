[CmdletBinding()]
param(
 [ValidateSet('Prepare','Audit002','Ledger002','Preflight003','Apply003','Postcheck003','Inspect')][string]$Mode='Prepare',
 [Parameter(Mandatory=$true)][string]$Repo,
 [Parameter(Mandatory=$true)][string]$Work,
 [string]$PgBin='C:\Program Files\PostgreSQL\19\bin',
 [string]$ConfirmAction=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$ApprovedSha='e280fa4f096ff7aa4d6d190d678982d3ea26fe49'
function Lf([string]$Text) { return $Text.Replace("`r`n","`n").TrimEnd([char[]]"`r`n")+"`n" }
function Hash-Text([string]$Text) {
 $Hasher=[Security.Cryptography.SHA256]::Create()
 try { return ([BitConverter]::ToString($Hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-','').ToLowerInvariant() }
 finally { $Hasher.Dispose() }
}

# Read Git object bytes, not the working tree and not PowerShell's native text pipeline.
$Repo=(Resolve-Path -LiteralPath $Repo).Path
$Work=[IO.Path]::GetFullPath($Work)
$Git=(Get-Command git.exe -CommandType Application -ErrorAction Stop).Source
$StrictUtf8=New-Object Text.UTF8Encoding($false,$true)
# The commit and SQL hashes are fixed. No checkout, fetch, or download occurs.
function Read-Approved([string]$RelativePath,[string]$ExpectedHash) {
 $Info=New-Object Diagnostics.ProcessStartInfo
 $Info.FileName=$Git
 $Info.WorkingDirectory=$Repo
 $Info.Arguments='--no-replace-objects cat-file blob '+$ApprovedSha+':'+$RelativePath
 $Info.UseShellExecute=$false
 $Info.RedirectStandardOutput=$true
 $Info.RedirectStandardError=$true
 $Process=New-Object Diagnostics.Process
 $Process.StartInfo=$Info
 $Buffer=New-Object IO.MemoryStream
 try {
  if (-not $Process.Start()) { throw 'Could not start git' }
  $Errors=$Process.StandardError.ReadToEndAsync()
  $Process.StandardOutput.BaseStream.CopyTo($Buffer)
  $Process.WaitForExit()
  if ($Process.ExitCode -ne 0) { throw ('git failed: '+$Errors.Result) }
  $Bytes=$Buffer.ToArray()
  if ($Bytes.Length -eq 0) { throw 'Empty Git source' }
  if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 239 -and $Bytes[1] -eq 187 -and $Bytes[2] -eq 191) { throw 'Unexpected BOM' }
  $Text=Lf ($StrictUtf8.GetString($Bytes))
  if ((Hash-Text $Text) -ne $ExpectedHash) { throw ('Approved SQL SHA256 mismatch: '+$RelativePath) }
  return $Text
 } finally { $Buffer.Dispose(); $Process.Dispose() }
}

$Source002=Read-Approved 'supabase/staging/002_durable_execution.sql' '2ea6824530ffed52a33f6ac449f0b396f19b24d511eef092fc713bea10c39fb4'
$Source003=Read-Approved 'supabase/staging/003_control_plane.sql' '6ffe1673191eac4335c3798daf9d3c34cb01551f9f674dd9ebdfa31215c88c19'
$Guard002=@'
do $$
begin
    if not coalesce((select relrowsecurity from pg_class
           where oid = to_regclass('reivro_cloud.execution_leases')), false)
       or has_table_privilege('authenticated', 'reivro_cloud.execution_leases', 'select')
       or has_function_privilege('authenticated', 'reivro_cloud.dispatch_v1(text,jsonb)', 'execute')
       or not has_function_privilege('authenticated', 'reivro_checks_api.dispatch(text,jsonb)', 'execute')
       or has_function_privilege('anon', 'reivro_checks_api.dispatch(text,jsonb)', 'execute')
       or has_function_privilege('service_role', 'reivro_checks_api.dispatch(text,jsonb)', 'execute') then
        raise exception 'V2 privileges failed verification';
    end if;
end
$$;
DO $$
DECLARE role_name text;
BEGIN
 IF (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_cloud.dispatch(text,jsonb)')) IS DISTINCT FROM '821570bb9304b8e4348996990f804aa2'
 OR (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_cloud.dispatch_v1(text,jsonb)')) IS DISTINCT FROM '7b65dd994ca180ed06312d3c0a7820fe'
 OR (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_checks_api.dispatch(text,jsonb)')) IS DISTINCT FROM '33ebec2c2d3ac3c64b6955369778fc61'
 OR (SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_checks_api.read_run(bigint,uuid)')) IS DISTINCT FROM '8815aa0cb0ee1f7b6c1d64315bd019d1'
 OR to_regclass('reivro_cloud.task_submissions') IS NOT NULL
 OR EXISTS(SELECT FROM reivro_cloud.execution_leases)
 OR (SELECT last_value FROM reivro_cloud.events_seq_seq)<>12
 OR NOT (SELECT is_called FROM reivro_cloud.events_seq_seq)
 THEN RAISE EXCEPTION 'Unexpected 002 state'; END IF;
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
  IF has_table_privilege(role_name,'reivro_cloud.execution_leases','SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
   OR has_function_privilege(role_name,'reivro_cloud.dispatch_v1(text,jsonb)','EXECUTE')
  THEN RAISE EXCEPTION 'Unexpected private privilege'; END IF;
 END LOOP;
END $$;
'@
$Guard002=Lf $Guard002
$DataGuard=@'
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
'@
$DataGuard=Lf $DataGuard
$Locks=@'
SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='30s';
SELECT pg_advisory_xact_lock(1469495108);
LOCK TABLE auth.users,reivro_cloud.projects,reivro_cloud.memberships,reivro_cloud.runs,
 reivro_cloud.findings,reivro_cloud.protections,reivro_cloud.events IN SHARE MODE;
'@
$Locks=Lf $Locks
function New-Ledger([string]$Version,[string]$Name,[string]$Source) {
 $Template=@'
SET LOCAL standard_conforming_strings=on;
LOCK TABLE supabase_migrations.schema_migrations IN SHARE ROW EXCLUSIVE MODE;
DO $ledger_record$
DECLARE applied_sql text := '__SOURCE__';
BEGIN
 IF NOT EXISTS(SELECT FROM supabase_migrations.schema_migrations WHERE version='20261123210041' AND name='reivro_firewall_staging')
 OR EXISTS(SELECT FROM supabase_migrations.schema_migrations WHERE version NOT IN ('20261123210041','20261126000200','20261126000300'))
 THEN RAISE EXCEPTION 'Unknown migration ledger baseline'; END IF;
 IF encode(sha256(convert_to(applied_sql,'UTF8')),'hex')<>'__HASH__' THEN RAISE EXCEPTION 'Ledger SQL hash mismatch'; END IF;

 IF EXISTS(SELECT FROM supabase_migrations.schema_migrations WHERE version='__VERSION__') THEN
  IF NOT EXISTS(SELECT FROM supabase_migrations.schema_migrations
   WHERE version='__VERSION__' AND name='__NAME__' AND statements=ARRAY[applied_sql]
   AND idempotency_key='reivro:__VERSION__:__HASH__') THEN RAISE EXCEPTION 'Ledger version collision'; END IF;
 ELSE
  INSERT INTO supabase_migrations.schema_migrations(version,name,statements,created_by,idempotency_key)
  VALUES('__VERSION__','__NAME__',ARRAY[applied_sql],current_user,'reivro:__VERSION__:__HASH__');
 END IF;
END $ledger_record$;
'@
 return (Lf ($Template.Replace('__SOURCE__',$Source.Replace("'","''")).Replace('__VERSION__',$Version).Replace('__NAME__',$Name).Replace('__HASH__',(Hash-Text $Source))))
}
$Ledger002=New-Ledger '20261126000200' 'reivro_durable_execution_002' $Source002
$Ledger003=New-Ledger '20261126000300' 'reivro_control_plane_003' $Source003
$LedgerCheck=@'
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM supabase_migrations.schema_migrations WHERE version='20261123210041' AND name='reivro_firewall_staging')
 OR NOT EXISTS(SELECT FROM supabase_migrations.schema_migrations WHERE version='20261126000200' AND name='reivro_durable_execution_002'
  AND idempotency_key='reivro:20261126000200:2ea6824530ffed52a33f6ac449f0b396f19b24d511eef092fc713bea10c39fb4'
  AND cardinality(statements)=1
  AND encode(sha256(convert_to(statements[1],'UTF8')),'hex')='2ea6824530ffed52a33f6ac449f0b396f19b24d511eef092fc713bea10c39fb4')
 OR (SELECT count(*) FROM supabase_migrations.schema_migrations)<>2
 THEN RAISE EXCEPTION 'Reconcile 002 ledger before 003'; END IF;
END $$;
'@
$LedgerCheck=Lf $LedgerCheck
$Guard003=@'
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
'@
$Guard003=Lf $Guard003
$InspectSql=@'
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='5s';
SELECT jsonb_build_object('dispatcher',(SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_cloud.dispatch(text,jsonb)')),
 'v1_alias',(SELECT md5(prosrc) FROM pg_proc WHERE oid=to_regprocedure('reivro_cloud.dispatch_v1(text,jsonb)')),
 'leases',to_regclass('reivro_cloud.execution_leases') IS NOT NULL,'tasks',to_regclass('reivro_cloud.task_submissions') IS NOT NULL,
 'ledger',(SELECT jsonb_agg(jsonb_build_object('version',version,'name',name,'key',idempotency_key) ORDER BY version) FROM supabase_migrations.schema_migrations));
SELECT pid,application_name,state,xact_start FROM pg_stat_activity WHERE datname=current_database()
 AND pid<>pg_backend_pid() AND xact_start IS NOT NULL;
COMMIT;
'@
$InspectSql=Lf $InspectSql
if ((Hash-Text $Source002) -ne '2ea6824530ffed52a33f6ac449f0b396f19b24d511eef092fc713bea10c39fb4') { throw 'Approved 002 source changed' }
if ((Hash-Text $Source003) -ne '6ffe1673191eac4335c3798daf9d3c34cb01551f9f674dd9ebdfa31215c88c19') { throw 'Approved 003 source changed' }
if (-not $Source003.StartsWith("begin;`n") -or -not $Source003.EndsWith("commit;`n")) { throw 'Unexpected 003 transaction boundaries' }
$Body003=$Source003.Substring(7,$Source003.Length-15)
$Files=[ordered]@{
 '002-approved-source.txt'=$Source002
 '003-approved-source.txt'=$Source003
 'audit-002.sql'=("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='5s';`n"+$Guard002+$DataGuard+"COMMIT;`n")
 'reconcile-ledger-002.sql'=("BEGIN;`n"+$Locks+$Guard002+$DataGuard+$Ledger002+"COMMIT;`nSELECT 'LEDGER_002_COMMIT_ACKNOWLEDGED';`n")
 'preflight-003.sql'=("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='5s';`n"+$Guard002+$DataGuard+$LedgerCheck+"COMMIT;`n")
 'apply-003.sql'=("BEGIN;`n"+$Locks+$Guard002+$DataGuard+$LedgerCheck+$Body003+$Guard003+$DataGuard+$Ledger003+"COMMIT;`nSELECT 'MIGRATION_003_COMMIT_ACKNOWLEDGED';`n")
 'postcheck-003.sql'=("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='5s';`n"+$Guard003+$DataGuard+"DO "+'$check$'+" BEGIN IF NOT EXISTS(SELECT FROM supabase_migrations.schema_migrations WHERE version='20261126000300' AND name='reivro_control_plane_003' AND cardinality(statements)=1 AND encode(sha256(convert_to(statements[1],'UTF8')),'hex')='6ffe1673191eac4335c3798daf9d3c34cb01551f9f674dd9ebdfa31215c88c19' AND idempotency_key='reivro:20261126000300:6ffe1673191eac4335c3798daf9d3c34cb01551f9f674dd9ebdfa31215c88c19') THEN RAISE EXCEPTION '003 ledger missing'; END IF; END "+'$check$'+";`nCOMMIT;`n")
 'inspect-state.sql'=$InspectSql
}
$Utf8=New-Object Text.UTF8Encoding($false)
if ($Mode -eq 'Prepare') {
 if (Test-Path -LiteralPath $Work) { throw 'Choose a fresh directory inside the protected operator folder' }
 New-Item -ItemType Directory -Path $Work | Out-Null
 $Manifest=[ordered]@{}
 foreach ($Name in $Files.Keys) {
  $Text=Lf $Files[$Name]
  [IO.File]::WriteAllText((Join-Path $Work $Name),$Text,$Utf8)
  $Manifest[$Name]=Hash-Text $Text
 }
 [IO.File]::WriteAllText((Join-Path $Work 'sha256.json'),($Manifest|ConvertTo-Json),$Utf8)
 Write-Host 'PASS: files prepared. No database connection was made.'
 return
}
foreach ($Name in $Files.Keys) {
 $Path=Join-Path $Work $Name
 if (-not (Test-Path -LiteralPath $Path)) { throw "Prepared file missing: $Name" }
 if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() -ne (Hash-Text (Lf $Files[$Name]))) { throw "Prepared file changed: $Name" }
}
if ($Mode -eq 'Ledger002' -and $ConfirmAction -ne 'RECONCILE-002-STAGING') { throw 'Ledger-only write requires explicit mode confirmation' }
if ($Mode -eq 'Apply003' -and $ConfirmAction -ne 'APPLY-003-STAGING') { throw '003 application requires explicit mode confirmation' }
$EnvNames=@('PGSSLMODE','PGCONNECT_TIMEOUT','PGAPPNAME','PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGOPTIONS','PGPASSWORD','PGCLIENTENCODING')
$OldEnv=@{}
foreach ($Name in $EnvNames) { $OldEnv[$Name]=[Environment]::GetEnvironmentVariable($Name,'Process') }
try {
$env:PGSSLMODE='verify-full'
$env:PGCLIENTENCODING='UTF8'
$env:PGCONNECT_TIMEOUT='10'
$env:PGAPPNAME='reivro-6-4-'+$Mode
Remove-Item Env:PGSERVICE,Env:PGSERVICEFILE,Env:PGHOSTADDR,Env:PGOPTIONS,Env:PGPASSWORD -ErrorAction SilentlyContinue
$SqlName=@{Audit002='audit-002.sql';Ledger002='reconcile-ledger-002.sql';Preflight003='preflight-003.sql';Apply003='apply-003.sql';Postcheck003='postcheck-003.sql';Inspect='inspect-state.sql'}[$Mode]
$ReceiptBase=Join-Path $Work ((Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+$Mode+'-'+[guid]::NewGuid().ToString('N'))
$Arguments=@('-X','-W','-q','-t','-A','-h','aws-1-us-west-1.pooler.supabase.com','-p','5432','-U','postgres.lbklqqqbmeyseeccdqog','-d','postgres','-v','ON_ERROR_STOP=1','-f',(Join-Path $Work $SqlName),'-o',($ReceiptBase+'.out.txt'))
# Keep stderr attached to the terminal so -W remains interactive on Windows.
$Arguments += @('-L',($ReceiptBase+'.psql-log.txt'))
$PsqlPath=Join-Path $PgBin 'psql.exe'
if (-not (Test-Path -LiteralPath $PsqlPath -PathType Leaf)) { throw 'psql executable unavailable' }
& $PsqlPath @Arguments
$Code=$LASTEXITCODE
[IO.File]::WriteAllText(($ReceiptBase+'.exit.txt'),[string]$Code,$Utf8)
if ($Code -ne 0) { throw 'SQL failed or commit is uncertain. Keep writers frozen; run Inspect before any retry. Review the private receipts.' }
Write-Host "PASS: $Mode. Receipt: $ReceiptBase.out.txt"
} finally {
 foreach ($Name in $EnvNames) { [Environment]::SetEnvironmentVariable($Name,$OldEnv[$Name],'Process') }
}
