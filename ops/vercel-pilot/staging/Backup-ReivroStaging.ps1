#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PrivateDirectory,
    [string]$PgBin,
    [ValidateRange(1024,65535)][int]$LocalPort=55465
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$staging='host=aws-1-us-west-1.pooler.supabase.com port=5432 user=postgres.lbklqqqbmeyseeccdqog dbname=postgres sslmode=verify-full'
$loopback="host=127.0.0.1 port=$LocalPort user=postgres dbname=postgres sslmode=disable"
$certificate=Join-Path $HOME 'Downloads/prod-ca-2021.crt'
if (-not (Test-Path -LiteralPath $certificate -PathType Leaf)) { throw 'Supabase CA certificate not found in Downloads.' }
$caPath=(Resolve-Path -LiteralPath $certificate).Path
$audit=Join-Path $PSScriptRoot 'audit_post_jwt_read_only.sql'
if (-not (Test-Path -LiteralPath $PrivateDirectory -PathType Container)) { throw 'Private backup directory must exist.' }
$PrivateDirectory=(Resolve-Path -LiteralPath $PrivateDirectory).Path
if ((Split-Path $PrivateDirectory -Leaf) -ne 'REIVRO-Backups') { throw 'Select the existing encrypted REIVRO-Backups folder.' }
foreach ($name in 'psql','pg_dump','pg_restore','initdb','pg_ctl') {
    $command = if ($PgBin) { Join-Path $PgBin "$name.exe" } else { "$name.exe" }
    Set-Variable -Name $name -Value (Get-Command $command -CommandType Application).Source
}
foreach ($tool in $psql,$pg_dump,$pg_restore,$initdb,$pg_ctl) {
    $version=& $tool --version
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '\s19\.\d+(?:\s|$)') { throw 'Use PostgreSQL 19 client and server binaries.' }
}

function Read-BackupPassword([string]$Label) {
    $secret=Read-Host -Prompt $Label -AsSecureString
    try {
        if ($secret.Length -eq 0) { throw 'Password cannot be empty.' }
        $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
        try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    } finally { $secret.Dispose() }
}

function Invoke-Pg([string]$Exe, [string[]]$Arguments, [ValidateSet('Staging','Local')][string]$Connection) {
    $previousPassword=[Environment]::GetEnvironmentVariable('PGPASSWORD','Process')
    $previousRoot=[Environment]::GetEnvironmentVariable('PGSSLROOTCERT','Process')
    try {
        if ($Connection -eq 'Staging') {
            $env:PGPASSWORD=$stagingPassword
            $env:PGSSLROOTCERT=$caPath
        } elseif ($Connection -eq 'Local') {
            $env:PGPASSWORD=$localPassword
        } else {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
        & $Exe @Arguments
        if ($LASTEXITCODE -ne 0) { throw "$(Split-Path $Exe -Leaf) exited $LASTEXITCODE" }
    } finally {
        if ($null -eq $previousPassword) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
        else { $env:PGPASSWORD=$previousPassword }
        if ($null -eq $previousRoot) { Remove-Item Env:PGSSLROOTCERT -ErrorAction SilentlyContinue }
        else { $env:PGSSLROOTCERT=$previousRoot }
    }
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
$stagingPassword=$localPassword=$null
$passwordFile=Join-Path $root 'initdb-password.tmp'
try {
    Write-Host 'Before continuing, confirm the directory is private and encrypted, and all staging writers are paused.'
    if ((Read-Host 'Type FREEZE to confirm') -cne 'FREEZE') { throw 'Freeze not confirmed by operator.' }
    $stagingPassword=Read-BackupPassword 'Staging PostgreSQL password'
    Invoke-Pg $psql @('-X','-w','-v','ON_ERROR_STOP=1','-d',$staging,'-c',$probe,'-f',$audit) -Connection Staging
    $sourceVersion=Invoke-Pg $psql @('-X','-w','-qAt','-v','ON_ERROR_STOP=1','-d',$staging,'-c','SHOW server_version_num') -Connection Staging
    if ($sourceVersion -notmatch '^17\d{4}$') { throw 'Expected a PostgreSQL 17 staging source.' }
    $before=@(Invoke-Pg $psql @('-X','-w','-qAt','-v','ON_ERROR_STOP=1','-d',$staging,'-c',$inventory) -Connection Staging)
    if ($before.Count -lt 2 -or $before[0] -cnotmatch '^[0-9a-f]{64}$') { throw 'Unexpected source inventory.' }
    $dumpArgs=@('-w','--format=custom','--quote-all-identifiers','--strict-names','--lock-wait-timeout=5s','--no-publications','--no-subscriptions',
        '--schema=auth','--schema=reivro_cloud','--schema=reivro_checks_api','--schema=supabase_migrations',
        "--file=$dump","--dbname=$staging")
    foreach ($table in ($before | Select-Object -Skip 1)) {
        if ($table -cnotmatch '^[a-z_][a-z0-9_]*$') { throw 'Unexpected Auth table name.' }
        $dumpArgs+="--exclude-table-data=auth.$table"
    }
    Invoke-Pg $pg_dump $dumpArgs -Connection Staging
    $toc=@(Invoke-Pg $pg_restore @('--list',$dump))
    $authData=@($toc | Where-Object { $_ -match '\bTABLE DATA auth\s' })
    if ($authData.Count -ne 1 -or $authData[0] -notmatch '\bTABLE DATA auth users\s') {
        throw 'Unexpected Auth data in archive. Keep archive private and stop.'
    }
    $toc | Set-Content -LiteralPath (Join-Path $root 'archive.toc.txt') -Encoding UTF8
    Invoke-Pg $psql @('-X','-w','-v','ON_ERROR_STOP=1','-d',$staging,'-c',$probe,'-f',$audit) -Connection Staging
    $after=@(Invoke-Pg $psql @('-X','-w','-qAt','-v','ON_ERROR_STOP=1','-d',$staging,'-c',$inventory) -Connection Staging)
    if (Compare-Object $before $after -SyncWindow 0) { throw 'Source inventory changed during backup.' }

    $stagingPassword=$null
    $localPassword=Read-BackupPassword 'New temporary PostgreSQL password for the local rehearsal cluster'
    if ($localPassword -match '[\x00\r\n]' -or $localPassword -ne $localPassword.Trim()) {
        throw 'Choose a local password without control characters or leading/trailing spaces.'
    }
    try {
        [IO.File]::WriteAllText($passwordFile, $localPassword + "`n", [Text.UTF8Encoding]::new($false))
        Invoke-Pg $initdb @('-D',$data,'-U','postgres','-A','scram-sha-256','--encoding=UTF8','--locale=C',"--pwfile=$passwordFile")
    } finally {
        if ([IO.File]::Exists($passwordFile)) { [IO.File]::Delete($passwordFile) }
    }
    Invoke-Pg $pg_ctl @('-D',$data,'-l',(Join-Path $root 'restore-local.log'),'-o',"-h 127.0.0.1 -p $LocalPort",'-w','start')
    $started=$true
    $localIdentity=@(Invoke-Pg $psql @('-X','-w','-qAt','-v','ON_ERROR_STOP=1','-d',$loopback,
        '-c','SHOW server_version_num','-c','SHOW data_directory') -Connection Local)
    if ($localIdentity.Count -ne 2 -or $localIdentity[0] -notmatch '^19\d{4}$' -or
        [IO.Path]::GetFullPath($localIdentity[1]) -ne [IO.Path]::GetFullPath($data)) {
        throw 'Expected the new PostgreSQL 19 rehearsal cluster.'
    }
    $roles='CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE authenticator; CREATE ROLE service_role; CREATE ROLE dashboard_user; CREATE ROLE supabase_admin; CREATE ROLE supabase_auth_admin;'
    Invoke-Pg $psql @('-X','-w','-v','ON_ERROR_STOP=1','-d',$loopback,'-c',$roles) -Connection Local
    Invoke-Pg $pg_restore @('-w','--exit-on-error','--single-transaction','--no-owner',"-d",$loopback,$dump) -Connection Local
    Invoke-Pg $psql @('-X','-w','-v','ON_ERROR_STOP=1','-d',$loopback,'-f',$audit) -Connection Local
    $restored=@(Invoke-Pg $psql @('-X','-w','-qAt','-v','ON_ERROR_STOP=1','-d',$loopback,'-c',$inventory) -Connection Local)
    if (Compare-Object $before $restored -SyncWindow 0) { throw 'Restored Auth data or schema inventory differs.' }
    $hash=(Get-FileHash -LiteralPath $dump -Algorithm SHA256).Hash.ToLowerInvariant()
    [pscustomobject]@{
        status='SELECTIVE_RESTORE_PASS'
        source_server_version_num=$sourceVersion
        restore_server_version_num=$localIdentity[0]
        captured_utc=[DateTime]::UtcNow.ToString('o')
        archive_sha256=$hash
        archive_bytes=(Get-Item -LiteralPath $dump).Length
        toc_entries=@($toc | Where-Object { $_ -match '^\d+;' }).Count
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'receipt.json') -Encoding UTF8
    Write-Output "SELECTIVE_RESTORE_PASS $root"
} finally {
    $stagingPassword=$localPassword=$null
    try {
        if ([IO.File]::Exists($passwordFile)) { [IO.File]::Delete($passwordFile) }
    } finally {
        if ($started) { Invoke-Pg $pg_ctl @('-D',$data,'-m','fast','-w','stop') }
    }
}
