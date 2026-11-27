#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PrivateDirectory,
    [string]$PgBin,
    [ValidateRange(1024,65535)][int]$LocalPort=55464
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$staging='host=aws-1-us-west-1.pooler.supabase.com port=5432 user=postgres.lbklqqqbmeyseeccdqog dbname=postgres sslmode=verify-full'
$loopback="host=127.0.0.1 port=$LocalPort user=postgres dbname=postgres sslmode=disable"
$audit=Join-Path $PSScriptRoot 'audit_post_jwt_read_only.sql'
if (-not (Test-Path -LiteralPath $PrivateDirectory -PathType Container)) { throw 'Private backup directory must exist.' }
foreach ($name in 'psql','pg_dump','pg_restore','initdb','pg_ctl') {
    $command = if ($PgBin) { Join-Path $PgBin "$name.exe" } else { "$name.exe" }
    Set-Variable -Name $name -Value (Get-Command $command -CommandType Application).Source
}
foreach ($tool in $psql,$pg_dump,$pg_restore,$initdb,$pg_ctl) {
    $version=& $tool --version
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '\s17\.\d+') { throw 'Use PostgreSQL 17 client and server binaries.' }
}

function Invoke-Pg([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$(Split-Path $Exe -Leaf) exited $LASTEXITCODE" }
}

$probe=@'
BEGIN READ ONLY;
DO $freeze$
BEGIN
 IF EXISTS (SELECT FROM pg_stat_activity
  WHERE backend_type='client backend' AND pid<>pg_backend_pid()
   AND xact_start IS NOT NULL)
 OR EXISTS (SELECT FROM pg_prepared_xacts WHERE database=current_database())
 THEN RAISE EXCEPTION 'Another transaction is active or prepared'; END IF;
END $freeze$;
COMMIT;
'@
$inventory=@'
BEGIN READ ONLY;
SET LOCAL timezone='UTC';
SELECT encode(sha256(convert_to(coalesce(string_agg(to_jsonb(u)::text,E'\n'
 ORDER BY u.id),''),'UTF8')),'hex') FROM auth.users u;
SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='auth' AND c.relkind IN ('r','p','m','f') AND c.relname<>'users'
 ORDER BY c.relname;
COMMIT;
'@

$root=Join-Path (Resolve-Path -LiteralPath $PrivateDirectory).Path ("reivro-staging-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
$null=New-Item -ItemType Directory -Path $root
$dump=Join-Path $root 'reivro-staging.dump'
$data=Join-Path $root 'restore-local'
$started=$false
try {
    Write-Host 'Before continuing, confirm the directory is private and encrypted, and all staging writers are paused.'
    if ((Read-Host 'Type FREEZE to confirm') -cne 'FREEZE') { throw 'Freeze not confirmed by operator.' }
    Invoke-Pg $psql @('-X','-W','-v','ON_ERROR_STOP=1','-d',$staging,'-c',$probe,'-f',$audit)
    $before=@(Invoke-Pg $psql @('-X','-W','-qAt','-v','ON_ERROR_STOP=1','-d',$staging,'-c',$inventory))
    if ($before.Count -lt 2 -or $before[0] -cnotmatch '^[0-9a-f]{64}$') { throw 'Unexpected source inventory.' }
    $dumpArgs=@('-W','--format=custom','--strict-names','--lock-wait-timeout=5s','--no-publications','--no-subscriptions',
        '--schema=auth','--schema=reivro_cloud','--schema=reivro_checks_api','--schema=supabase_migrations',
        "--file=$dump","--dbname=$staging")
    foreach ($table in ($before | Select-Object -Skip 1)) {
        if ($table -cnotmatch '^[a-z_][a-z0-9_]*$') { throw 'Unexpected Auth table name.' }
        $dumpArgs+="--exclude-table-data=auth.$table"
    }
    Invoke-Pg $pg_dump $dumpArgs
    $toc=@(Invoke-Pg $pg_restore @('--list',$dump))
    $authData=@($toc | Where-Object { $_ -match '\bTABLE DATA auth\s' })
    if ($authData.Count -ne 1 -or $authData[0] -notmatch '\bTABLE DATA auth users\s') {
        throw 'Unexpected Auth data in archive. Keep archive private and stop.'
    }
    $toc | Set-Content -LiteralPath (Join-Path $root 'archive.toc.txt') -Encoding UTF8
    Invoke-Pg $psql @('-X','-W','-v','ON_ERROR_STOP=1','-d',$staging,'-c',$probe,'-f',$audit)
    $after=@(Invoke-Pg $psql @('-X','-W','-qAt','-v','ON_ERROR_STOP=1','-d',$staging,'-c',$inventory))
    if (Compare-Object $before $after -SyncWindow 0) { throw 'Source inventory changed during backup.' }

    Write-Host 'Choose a temporary local PostgreSQL password for the restore rehearsal. The next prompts use that local password.'
    Invoke-Pg $initdb @('-D',$data,'-U','postgres','-A','scram-sha-256','-W')
    Invoke-Pg $pg_ctl @('-D',$data,'-l',(Join-Path $root 'restore-local.log'),'-o',"-h 127.0.0.1 -p $LocalPort",'-w','start')
    $started=$true
    $roles='CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE authenticator; CREATE ROLE service_role; CREATE ROLE dashboard_user; CREATE ROLE supabase_admin; CREATE ROLE supabase_auth_admin;'
    Invoke-Pg $psql @('-X','-W','-v','ON_ERROR_STOP=1','-d',$loopback,'-c',$roles)
    Invoke-Pg $pg_restore @('-W','--exit-on-error','--single-transaction','--no-owner',"-d",$loopback,$dump)
    Invoke-Pg $psql @('-X','-W','-v','ON_ERROR_STOP=1','-d',$loopback,'-f',$audit)
    $restored=@(Invoke-Pg $psql @('-X','-W','-qAt','-v','ON_ERROR_STOP=1','-d',$loopback,'-c',$inventory))
    if (Compare-Object $before $restored -SyncWindow 0) { throw 'Restored Auth data or schema inventory differs.' }
    $hash=(Get-FileHash -LiteralPath $dump -Algorithm SHA256).Hash.ToLowerInvariant()
    [pscustomobject]@{
        status='SELECTIVE_RESTORE_PASS'
        captured_utc=[DateTime]::UtcNow.ToString('o')
        archive_sha256=$hash
        archive_bytes=(Get-Item -LiteralPath $dump).Length
        toc_entries=@($toc | Where-Object { $_ -match '^\d+;' }).Count
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'receipt.json') -Encoding UTF8
    Write-Output "SELECTIVE_RESTORE_PASS $root"
} finally {
    if ($started) { Invoke-Pg $pg_ctl @('-D',$data,'-m','fast','-w','stop') }
}
