#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ReceiptDirectory,
    [string]$PgBin = 'C:\Program Files\PostgreSQL\19\bin'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$staging = 'host=aws-1-us-west-1.pooler.supabase.com port=5432 user=postgres.lbklqqqbmeyseeccdqog dbname=postgres sslmode=verify-full'
$certificate = Join-Path $HOME 'Downloads\prod-ca-2021.crt'
$audit = Join-Path $PSScriptRoot 'audit_agent_pending_read_only.sql'
$recoverySql = Join-Path $PSScriptRoot 'recover_staging_agent_membership.sql'
$postcheckSql = Join-Path $PSScriptRoot 'inspect_staging_agent.sql'
$pendingReceipt = Join-Path $ReceiptDirectory 'agent-a-provisioning-receipt.json'
$authReceipt = Join-Path $ReceiptDirectory 'agent-a-auth-created-receipt.json'

function Read-Hidden([string]$Label) {
    $secret = Read-Host -Prompt $Label -AsSecureString
    try {
        if ($secret.Length -eq 0) { throw 'Password cannot be empty.' }
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
        try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    } finally { $secret.Dispose() }
}

function Invoke-Staging([string[]]$Arguments) {
    $oldPassword = [Environment]::GetEnvironmentVariable('PGPASSWORD','Process')
    $oldRoot = [Environment]::GetEnvironmentVariable('PGSSLROOTCERT','Process')
    try {
        $env:PGPASSWORD = $script:stagingPassword
        $env:PGSSLROOTCERT = $script:caPath
        $output = & $script:psql @Arguments
        if ($LASTEXITCODE -ne 0) { throw "psql exited $LASTEXITCODE" }
        $output
    } finally {
        if ($null -eq $oldPassword) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
        else { $env:PGPASSWORD = $oldPassword }
        if ($null -eq $oldRoot) { Remove-Item Env:PGSSLROOTCERT -ErrorAction SilentlyContinue }
        else { $env:PGSSLROOTCERT = $oldRoot }
    }
}

$stage = 'pending-receipt'
$stagingPassword = $approval = $null
try {
    foreach ($path in $ReceiptDirectory,$pendingReceipt,$certificate,$audit,$recoverySql,$postcheckSql) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Required path missing: $path" }
    }
    $receipt = Get-Content -LiteralPath $pendingReceipt -Raw | ConvertFrom-Json
    if ($receipt.state -cne 'AUTH_CREATED_MEMBERSHIP_PENDING' -or
        $receipt.staging_ref -cne 'lbklqqqbmeyseeccdqog') {
        throw 'Private pending receipt does not identify the approved Agent A.'
    }
    $expectedAgent = [guid]$receipt.agent_id
    $repositoryId = [long]$receipt.repository_id
    if ($expectedAgent -eq [guid]::Empty -or $repositoryId -le 0) { throw 'Pending receipt identifiers are invalid.' }
    if (Test-Path -LiteralPath $authReceipt) { throw 'A recovery receipt already exists. Reconcile before retrying.' }
    $caPath = (Resolve-Path -LiteralPath $certificate).Path
    $psql = (Get-Command (Join-Path $PgBin 'psql.exe') -CommandType Application).Source
    if ((& $psql --version) -notmatch '\s19\.\d+(?:\s|$)') { throw 'Use PostgreSQL 19 psql.' }
    Write-Output 'PASS pending Agent receipt'

    $stage = 'read-only-preflight'
    $stagingPassword = Read-Hidden 'Staging PostgreSQL password'
    Invoke-Staging @('-X','-w','-v','ON_ERROR_STOP=1','-d',$staging,
        '-v',"agent_id=$expectedAgent",'-v',"repository_id=$repositoryId",'-f',$audit) | Write-Output
    $diagnostic = @"
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
DO `$preflight`$
BEGIN
 IF EXISTS (SELECT FROM pg_stat_activity WHERE backend_type='client backend'
      AND pid<>pg_backend_pid() AND xact_start IS NOT NULL)
 OR EXISTS (SELECT FROM pg_prepared_xacts WHERE database=current_database())
 OR (SELECT count(*) FROM auth.users)<>6
 OR NOT EXISTS (SELECT FROM auth.users WHERE id='$expectedAgent'::uuid
      AND created_at>='2026-11-27T00:00:00Z'::timestamptz AND created_at<=now()
      AND email_confirmed_at IS NOT NULL AND is_anonymous=false)
 OR EXISTS (SELECT FROM reivro_cloud.memberships WHERE user_id='$expectedAgent'::uuid)
 OR (SELECT count(*) FROM reivro_cloud.memberships)<>4
 OR EXISTS (SELECT FROM reivro_cloud.task_contracts)
 OR EXISTS (SELECT FROM reivro_cloud.task_submissions)
 OR EXISTS (SELECT FROM reivro_cloud.task_policies)
 OR EXISTS (SELECT FROM reivro_cloud.task_corrections)
 OR EXISTS (SELECT FROM reivro_cloud.execution_leases)
 OR EXISTS (SELECT FROM reivro_cloud.runs WHERE outcome IS NULL)
 THEN RAISE EXCEPTION 'Pending membership preflight differs'; END IF;
END `$preflight`$;
COMMIT;
"@
    Invoke-Staging @('-X','-w','-v','ON_ERROR_STOP=1','-d',$staging,'-c',$diagnostic) | Write-Output
    Write-Output 'PASS pending membership preflight'

    $stage = 'authorization'
    Write-Host 'Authorized scope: insert one membership agent for the existing Agent A UUID. No Auth update.'
    $approval = Read-Host 'Type STAGING-AGENT-MEMBERSHIP-RECOVERY-APPROVED to authorize this one write'
    if ($approval -cne 'STAGING-AGENT-MEMBERSHIP-RECOVERY-APPROVED') { throw 'Membership write was not authorized.' }
    Copy-Item -LiteralPath $pendingReceipt -Destination $authReceipt

    $stage = 'insert-membership'
    Invoke-Staging @('-X','-w','-v','ON_ERROR_STOP=1','-d',$staging,
        '-v',"agent_id=$expectedAgent",'-v',"repository_id=$repositoryId",
        '-v',"approval=$approval",'-f',$recoverySql) | Write-Output
    $stage = 'postcheck'
    Invoke-Staging @('-X','-w','-v','ON_ERROR_STOP=1','-d',$staging,
        '-v',"agent_id=$expectedAgent",'-v',"repository_id=$repositoryId",'-f',$postcheckSql) | Write-Output

    $receipt.state = 'AGENT_A_PROVISIONED'
    $receipt | Add-Member -NotePropertyName membership_recovered_utc -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
    $receipt | ConvertTo-Json | Set-Content -LiteralPath $pendingReceipt -Encoding UTF8
    Write-Output "AGENT_A_MEMBERSHIP_RECOVERED receipt=$pendingReceipt"
} catch {
    [Console]::Error.WriteLine("FAIL $stage")
    exit 1
} finally {
    $stagingPassword = $approval = $null
    Remove-Item Env:PGPASSWORD,Env:PGSSLROOTCERT -ErrorAction SilentlyContinue
}
