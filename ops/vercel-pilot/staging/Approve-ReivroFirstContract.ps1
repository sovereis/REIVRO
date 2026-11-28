#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Plan,
    [string]$PgBin = 'C:\Program Files\PostgreSQL\19\bin'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Read-Hidden([string]$Label) {
    $secret = Read-Host -Prompt $Label -AsSecureString
    try {
        if ($secret.Length -eq 0) { throw 'Value cannot be empty.' }
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
        try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    } finally { $secret.Dispose() }
}

function Send-Staging([Net.Http.HttpMethod]$Method,[string]$Path,[object]$Payload,[switch]$Rpc) {
    $request = [Net.Http.HttpRequestMessage]::new($Method,$Path)
    try {
        if ($Rpc) { $request.Headers.Add('Content-Profile','reivro_checks_api') }
        if ($null -ne $Payload) {
            $json = ConvertTo-Json -InputObject $Payload -Depth 12 -Compress
            $request.Content = [Net.Http.StringContent]::new($json,[Text.Encoding]::UTF8,'application/json')
        }
        $response = $script:client.SendAsync($request).GetAwaiter().GetResult()
        try {
            [pscustomobject]@{
                Status=[int]$response.StatusCode
                Body=$response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            }
        } finally { $response.Dispose() }
    } finally { $request.Dispose() }
}

function Invoke-Reconciliation {
    $oldPassword = [Environment]::GetEnvironmentVariable('PGPASSWORD','Process')
    $oldRoot = [Environment]::GetEnvironmentVariable('PGSSLROOTCERT','Process')
    try {
        $env:PGPASSWORD = $script:databasePassword
        $env:PGSSLROOTCERT = $script:certificatePath
        $connection = 'host=aws-1-us-west-1.pooler.supabase.com port=5432 user=postgres.lbklqqqbmeyseeccdqog dbname=postgres sslmode=verify-full'
        $output = & $script:psql '-X' '-w' '-qAt' '-F' '|' '-v' 'ON_ERROR_STOP=1' '-d' $connection `
            '-v' "repository_id=$($script:fixture.repository_id)" `
            '-v' "contract_id=$($script:fixture.contract_id)" `
            '-v' "submission_id=$($script:fixture.submission_id)" `
            '-v' "digest=$($script:fixture.digest)" `
            '-v' "reviewer_id=$($script:fixture.reviewer_id)" `
            '-v' "agent_id=$($script:fixture.agent_id)" `
            '-v' "head_sha=$($script:fixture.head_sha)" `
            '-f' $script:inspectSql
        if ($LASTEXITCODE -ne 0) { throw "Reconciliation psql exited $LASTEXITCODE." }
        $row = @($output | Where-Object { $_ -match '^(t|f)\|' })[-1] -split '\|'
        if ($row.Count -ne 5) { throw 'Unexpected reconciliation result.' }
        [pscustomobject]@{
            ProjectExists=($row[0] -ceq 't')
            ContractMatches=($row[1] -ceq 't')
            SubmissionMatches=($row[2] -ceq 't')
            ApprovalEvents=[int]$row[3]
            SubmissionEvents=[int]$row[4]
        }
    } finally {
        if ($null -eq $oldPassword) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
        else { $env:PGPASSWORD = $oldPassword }
        if ($null -eq $oldRoot) { Remove-Item Env:PGSSLROOTCERT -ErrorAction SilentlyContinue }
        else { $env:PGSSLROOTCERT = $oldRoot }
    }
}

$stage = 'plan'
$client = $handler = $key = $email = $password = $session = $databasePassword = $null
$fixture = $null
$writeAttempted = $false
$rpcFailure = $null
try {
    $inspectSql = Join-Path $PSScriptRoot 'inspect_staging_task_fixture.sql'
    $certificate = Join-Path $HOME 'Downloads\prod-ca-2021.crt'
    foreach ($path in $Plan,$inspectSql,$certificate) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Required path missing: $path" }
    }
    $fixture = Get-Content -LiteralPath $Plan -Raw | ConvertFrom-Json
    if ($fixture.staging_ref -cne 'lbklqqqbmeyseeccdqog' -or
        [guid]$fixture.reviewer_id -ne [guid]'18c4dc88-f51b-462e-a87e-c43a494f2a66' -or
        [guid]$fixture.agent_id -eq [guid]::Empty -or [long]$fixture.repository_id -le 0 -or
        [guid]$fixture.contract_id -eq [guid]::Empty -or [guid]$fixture.submission_id -eq [guid]::Empty -or
        [guid]$fixture.contract_id -eq [guid]$fixture.submission_id -or
        [string]$fixture.base_sha -cne '07fc0b907d3aa9659ea7541f80acf6c18586e645' -or
        [string]$fixture.head_sha -cne 'e0d50dd239f8c8c3c39df84187741009f7496d09' -or
        [string]$fixture.digest -cnotmatch '^[0-9a-f]{64}$') { throw 'Private fixture plan does not match the approved scope.' }

    $psql = (Get-Command (Join-Path $PgBin 'psql.exe') -CommandType Application).Source
    if ((& $psql --version) -notmatch '\s19\.\d+(?:\s|$)') { throw 'Use PostgreSQL 19 psql.' }
    $certificatePath = (Resolve-Path -LiteralPath $certificate).Path

    $stage = 'credentials'
    $key = (Read-Hidden 'Staging default publishable key').Trim()
    $email = (Read-Hidden 'Reviewer A staging email').Trim()
    $password = Read-Hidden 'Reviewer A staging password'
    $databasePassword = Read-Hidden 'Staging PostgreSQL password for reconciliation'
    if ($key -cnotmatch '^sb_publishable_[A-Za-z0-9_-]+$') { throw 'Invalid publishable key format.' }

    Add-Type -AssemblyName System.Net.Http
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseCookies = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.BaseAddress = [uri]'https://lbklqqqbmeyseeccdqog.supabase.co'
    $client.Timeout = [TimeSpan]::FromSeconds(15)
    $client.DefaultRequestHeaders.Add('apikey',$key)
    $key = $null

    $stage = 'reviewer login'
    $response = Send-Staging ([Net.Http.HttpMethod]::Post) '/auth/v1/token?grant_type=password' @{
        email=$email;password=$password
    }
    if ($response.Status -lt 200 -or $response.Status -ge 300) { throw "Login returned HTTP $($response.Status)." }
    $session = $response.Body | ConvertFrom-Json
    if ($session.user.id -cne [string]$fixture.reviewer_id -or
        $session.access_token -cnotmatch '^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){2}$') {
        throw 'Reviewer login returned an unexpected identity.'
    }
    $client.DefaultRequestHeaders.Authorization =
        [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer',$session.access_token)
    $email = $password = $session = $null
    Write-Output 'PASS reviewer A Auth identity'

    $stage = 'prewrite reconciliation'
    $before = Invoke-Reconciliation
    if (-not $before.ProjectExists -or $before.ContractMatches -or $before.SubmissionMatches -or
        $before.ApprovalEvents -ne 0 -or $before.SubmissionEvents -ne 0) {
        throw 'Fixture IDs already have persisted state; stop and reconcile manually.'
    }
    Write-Output 'PASS fixture IDs unused'

    $stage = 'authorization'
    $approval = Read-Host 'Type STAGING-FIRST-CONTRACT-APPROVED to execute the authorized RPC'
    if ($approval -cne 'STAGING-FIRST-CONTRACT-APPROVED') { throw 'Contract approval not confirmed.' }

    $stage = 'approve contract'
    $writeAttempted = $true
    try {
        $response = Send-Staging ([Net.Http.HttpMethod]::Post) '/rest/v1/rpc/task_dispatch' @{
            action='approve_contract';request=@{
                repository_id=[long]$fixture.repository_id
                id=[string]$fixture.contract_id
                version=1
                digest=[string]$fixture.digest
                document=@{
                    base_sha=[string]$fixture.base_sha
                    criteria=@(@{kind='exists';path='guide.md'})
                }
            }
        } -Rpc
        if ($response.Status -lt 200 -or $response.Status -ge 300) {
            throw "Approval RPC returned HTTP $($response.Status)."
        }
        $rpcResult = $response.Body | ConvertFrom-Json
        if ($rpcResult.id -cne [string]$fixture.contract_id -or
            $rpcResult.digest -cne [string]$fixture.digest) { throw 'Unexpected approval receipt.' }
    } catch { $rpcFailure = $_ }

    $stage = 'postwrite reconciliation'
    $after = Invoke-Reconciliation
    if (-not $after.ProjectExists -or -not $after.ContractMatches -or $after.SubmissionMatches -or
        $after.ApprovalEvents -ne 1 -or $after.SubmissionEvents -ne 0) {
        throw 'Persisted state does not match the single authorized approval.'
    }
    Write-Output 'PASS contract and approval event reconciled'
    if ($null -ne $rpcFailure) { Write-Output 'PASS commit reconciled after uncertain RPC response' }
    Write-Output 'FIRST_CONTRACT_APPROVED_NO_SUBMISSION'
} catch {
    [Console]::Error.WriteLine("FAIL $stage")
    if ($writeAttempted) { [Console]::Error.WriteLine('Do not retry. Reconcile the private fixture IDs first.') }
    exit 1
} finally {
    $key = $email = $password = $session = $databasePassword = $approval = $response = $rpcResult = $null
    Remove-Item Env:PGPASSWORD,Env:PGSSLROOTCERT -ErrorAction SilentlyContinue
    if ($null -ne $client) { $client.DefaultRequestHeaders.Authorization = $null; $client.Dispose() }
    elseif ($null -ne $handler) { $handler.Dispose() }
}
