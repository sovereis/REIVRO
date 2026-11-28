#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ReceiptDirectory,
    [string]$PgBin = 'C:\Program Files\PostgreSQL\19\bin'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-Hidden([string]$Label) {
    $secret = Read-Host -Prompt $Label -AsSecureString
    try {
        if ($secret.Length -eq 0) { throw 'Password cannot be empty.' }
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
        try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    } finally { $secret.Dispose() }
}

$password = $null
try {
    $receiptPath = Join-Path $ReceiptDirectory 'agent-a-provisioning-receipt.json'
    $planPath = Join-Path $ReceiptDirectory 'control-plane-fixture-a-plan.json'
    $certificate = Join-Path $HOME 'Downloads\prod-ca-2021.crt'
    $sql = Join-Path $PSScriptRoot 'plan_staging_task_fixture.sql'
    foreach ($path in $ReceiptDirectory,$receiptPath,$certificate,$sql) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Required path missing: $path" }
    }
    if (Test-Path -LiteralPath $planPath) { throw 'A private fixture plan already exists; reconcile it before retrying.' }

    $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    if ($receipt.state -cne 'AGENT_A_PROVISIONED' -or
        $receipt.staging_ref -cne 'lbklqqqbmeyseeccdqog') { throw 'Agent receipt is not provisioned.' }
    $agentId = [guid]$receipt.agent_id
    $repositoryId = [long]$receipt.repository_id
    $reviewerId = [guid](Read-Host 'Reviewer A UUID')
    $baseSha = (Read-Host 'Synthetic BASE SHA (40 lowercase hex)').Trim()
    $headSha = (Read-Host 'Synthetic HEAD SHA (40 lowercase hex, distinct)').Trim()
    if ($agentId -eq [guid]::Empty -or $reviewerId -eq [guid]::Empty -or $repositoryId -le 0 -or
        $baseSha -cnotmatch '^[0-9a-f]{40}$' -or $headSha -cnotmatch '^[0-9a-f]{40}$' -or
        $baseSha -ceq $headSha) { throw 'Invalid fixture inputs.' }

    $psql = (Get-Command (Join-Path $PgBin 'psql.exe') -CommandType Application).Source
    if ((& $psql --version) -notmatch '\s19\.\d+(?:\s|$)') { throw 'Use PostgreSQL 19 psql.' }
    $password = Read-Hidden 'Staging PostgreSQL password'
    $oldPassword = [Environment]::GetEnvironmentVariable('PGPASSWORD','Process')
    $oldRoot = [Environment]::GetEnvironmentVariable('PGSSLROOTCERT','Process')
    try {
        $env:PGPASSWORD = $password
        $env:PGSSLROOTCERT = (Resolve-Path -LiteralPath $certificate).Path
        $connection = 'host=aws-1-us-west-1.pooler.supabase.com port=5432 user=postgres.lbklqqqbmeyseeccdqog dbname=postgres sslmode=verify-full'
        $output = & $psql '-X' '-w' '-qAt' '-v' 'ON_ERROR_STOP=1' '-d' $connection `
            '-v' "repository_id=$repositoryId" '-v' "reviewer_id=$reviewerId" `
            '-v' "agent_id=$agentId" '-v' "base_sha=$baseSha" '-v' "head_sha=$headSha" `
            '-f' $sql
        if ($LASTEXITCODE -ne 0) { throw "psql exited $LASTEXITCODE" }
    } finally {
        if ($null -eq $oldPassword) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
        else { $env:PGPASSWORD = $oldPassword }
        if ($null -eq $oldRoot) { Remove-Item Env:PGSSLROOTCERT -ErrorAction SilentlyContinue }
        else { $env:PGSSLROOTCERT = $oldRoot }
    }
    $json = @($output | Where-Object { $_ -match '^\{' })[-1]
    $plan = $json | ConvertFrom-Json
    if ($plan.staging_ref -cne 'lbklqqqbmeyseeccdqog' -or
        [guid]$plan.agent_id -ne $agentId -or [guid]$plan.reviewer_id -ne $reviewerId -or
        [long]$plan.repository_id -ne $repositoryId -or
        [string]$plan.digest -cnotmatch '^[0-9a-f]{64}$') { throw 'Generated plan failed validation.' }
    $plan | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $planPath -Encoding UTF8
    Write-Output "FIXTURE_A_PLAN_READY path=$planPath"
    Write-Output 'NO_STAGING_WRITES_PERFORMED'
} catch {
    [Console]::Error.WriteLine('FAIL fixture plan preparation')
    exit 1
} finally {
    $password = $null
    Remove-Item Env:PGPASSWORD,Env:PGSSLROOTCERT -ErrorAction SilentlyContinue
}
