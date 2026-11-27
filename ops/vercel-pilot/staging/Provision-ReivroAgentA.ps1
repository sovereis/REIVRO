#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ReceiptDirectory = 'C:\Users\LENOVO\REIVRO-Backups\reivro-staging-20261127-183321-65f72840',
    [string]$PgBin = 'C:\Program Files\PostgreSQL\19\bin'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$expectedProject = 'lbklqqqbmeyseeccdqog'
$staging = 'host=aws-1-us-west-1.pooler.supabase.com port=5432 user=postgres.lbklqqqbmeyseeccdqog dbname=postgres sslmode=verify-full'
$certificate = Join-Path $HOME 'Downloads\prod-ca-2021.crt'
$audit = Join-Path $PSScriptRoot 'audit_post_jwt_read_only.sql'
$membershipSql = Join-Path $PSScriptRoot 'provision_staging_agent.sql'
$postcheckSql = Join-Path $PSScriptRoot 'inspect_staging_agent.sql'
$receiptPath = Join-Path $ReceiptDirectory 'receipt.json'
$archivePath = Join-Path $ReceiptDirectory 'reivro-staging.dump'
$agentReceiptPath = Join-Path $ReceiptDirectory 'agent-a-provisioning-receipt.json'

function Read-Hidden([string]$Label) {
    $secret = Read-Host -Prompt $Label -AsSecureString
    try {
        if ($secret.Length -eq 0) { throw 'Secret cannot be empty.' }
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
        try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    } finally { $secret.Dispose() }
}

function Invoke-StagingPsql([string[]]$Arguments) {
    $previousPassword = [Environment]::GetEnvironmentVariable('PGPASSWORD', 'Process')
    $previousRoot = [Environment]::GetEnvironmentVariable('PGSSLROOTCERT', 'Process')
    try {
        $env:PGPASSWORD = $script:stagingPassword
        $env:PGSSLROOTCERT = $script:caPath
        $output = & $script:psql @Arguments
        if ($LASTEXITCODE -ne 0) { throw "psql exited $LASTEXITCODE" }
        $output
    } finally {
        if ($null -eq $previousPassword) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
        else { $env:PGPASSWORD = $previousPassword }
        if ($null -eq $previousRoot) { Remove-Item Env:PGSSLROOTCERT -ErrorAction SilentlyContinue }
        else { $env:PGSSLROOTCERT = $previousRoot }
    }
}

function Invoke-AuthAdmin([Net.Http.HttpMethod]$Method, [string]$Path, [hashtable]$Payload) {
    $request = [Net.Http.HttpRequestMessage]::new($Method, $Path)
    try {
        if ($null -ne $Payload) {
            $json = ConvertTo-Json -InputObject $Payload -Depth 5 -Compress
            $request.Content = [Net.Http.StringContent]::new($json, [Text.Encoding]::UTF8, 'application/json')
        }
        $response = $script:http.SendAsync($request).GetAwaiter().GetResult()
        try {
            if (-not $response.IsSuccessStatusCode) {
                $script:httpStatus = [int]$response.StatusCode
                throw 'Supabase Auth rejected the request.'
            }
            $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        } finally { $response.Dispose() }
    } finally { $request.Dispose() }
}

function Write-AgentReceipt([string]$State, [guid]$AgentId, [long]$RepositoryId, [string]$AuthCreatedUtc) {
    [pscustomobject]@{
        staging_ref = $expectedProject
        state = $State
        agent_id = $AgentId.ToString()
        repository_id = $RepositoryId
        auth_created_utc = $AuthCreatedUtc
        recorded_utc = [DateTime]::UtcNow.ToString('o')
        source_backup = Split-Path $ReceiptDirectory -Leaf
    } | ConvertTo-Json | Set-Content -LiteralPath $agentReceiptPath -Encoding UTF8
}

$stage = 'local-receipt'
$stagingPassword = $secretKey = $agentPassword = $confirmation = $approval = $null
$http = $handler = $null
$httpStatus = $null
$authCreated = $false
$agentId = [guid]::Empty
try {
    foreach ($file in $ReceiptDirectory, $receiptPath, $archivePath, $certificate, $audit, $membershipSql, $postcheckSql) {
        if (-not (Test-Path -LiteralPath $file)) { throw "Required path missing: $file" }
    }
    if (Test-Path -LiteralPath $agentReceiptPath) { throw 'An Agent A receipt already exists. Reconcile it before proceeding.' }
    $caPath = (Resolve-Path -LiteralPath $certificate).Path
    $psql = (Get-Command (Join-Path $PgBin 'psql.exe') -CommandType Application).Source
    if ((& $psql --version) -notmatch '\s19\.\d+(?:\s|$)') { throw 'Use the installed PostgreSQL 19 psql.' }

    $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    if ($receipt.status -cne 'SELECTIVE_RESTORE_PASS' -or
        [string]$receipt.source_server_version_num -cnotmatch '^17\d{4}$' -or
        [string]$receipt.restore_server_version_num -cnotmatch '^19\d{4}$' -or
        [long]$receipt.archive_bytes -ne (Get-Item -LiteralPath $archivePath).Length -or
        [int]$receipt.toc_entries -le 0 -or
        [string]$receipt.archive_sha256 -cne (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw 'The selective-restore receipt does not match its archive.'
    }
    Write-Output 'PASS local receipt reconciliation'

    $stage = 'cloud-preflight'
    $stagingPassword = Read-Hidden 'Staging PostgreSQL password'
    Invoke-StagingPsql @('-X','-w','-v','ON_ERROR_STOP=1','-d',$staging,'-f',$audit) | Write-Output
    $projectQuery = @"
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
DO `$freeze`$
BEGIN
 IF EXISTS (SELECT FROM pg_stat_activity WHERE backend_type='client backend'
     AND pid<>pg_backend_pid() AND xact_start IS NOT NULL)
 OR EXISTS (SELECT FROM pg_prepared_xacts WHERE database=current_database())
 THEN RAISE EXCEPTION 'Another transaction is active or prepared'; END IF;
 IF (SELECT count(*) FROM auth.users)<>5
 OR (SELECT count(*) FROM reivro_cloud.memberships)<>4
 OR EXISTS (SELECT FROM reivro_cloud.memberships WHERE role='agent')
 OR EXISTS (SELECT FROM reivro_cloud.task_submissions)
 OR EXISTS (SELECT FROM reivro_cloud.execution_leases)
 OR EXISTS (SELECT FROM reivro_cloud.runs WHERE outcome IS NULL)
 THEN RAISE EXCEPTION 'Unexpected pre-Agent inventory'; END IF;
END `$freeze`$;
SELECT p.repository_id FROM reivro_cloud.projects p
JOIN reivro_cloud.memberships m ON m.project_id=p.id
GROUP BY p.id,p.repository_id
HAVING count(*)=3 AND count(*) FILTER (WHERE m.role='reviewer')=1
 AND count(*) FILTER (WHERE m.role='viewer')=1
 AND count(*) FILTER (WHERE m.role='worker')=1;
COMMIT;
"@
    $projectOutput = @(Invoke-StagingPsql @('-X','-w','-qAt','-v','ON_ERROR_STOP=1','-d',$staging,'-c',$projectQuery))
    if ($projectOutput.Count -ne 1 -or $projectOutput[0] -cnotmatch '^\d+$') { throw 'Project A was not uniquely identified.' }
    $repositoryId = [long]$projectOutput[0]
    Write-Output 'PASS staging freeze and pre-Agent inventory'

    $stage = 'auth-preflight'
    $secretKey = (Read-Hidden 'Existing staging secret API key').Trim()
    if ($secretKey -cnotmatch '^sb_secret_[A-Za-z0-9_-]+$') { throw 'Use a modern staging secret key.' }
    $agentEmail = (Read-Host 'Dedicated synthetic email for Agent A').Trim().ToLowerInvariant()
    if ($agentEmail -cnotmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') { throw 'Invalid Agent A email.' }
    $agentPassword = Read-Hidden 'New dedicated Agent A password (save it in the Agent vault first)'
    $confirmation = Read-Hidden 'Confirm Agent A password'
    if ($agentPassword -cne $confirmation -or $agentPassword.Length -lt 30 -or
        [Text.Encoding]::UTF8.GetByteCount($agentPassword) -gt 72) { throw 'Agent password validation failed.' }
    $confirmation = $null

    Add-Type -AssemblyName System.Net.Http
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseCookies = $false
    $http = [Net.Http.HttpClient]::new($handler)
    $http.BaseAddress = [uri]'https://lbklqqqbmeyseeccdqog.supabase.co'
    $http.Timeout = [TimeSpan]::FromSeconds(20)
    $http.DefaultRequestHeaders.Add('apikey', $secretKey)
    $secretKey = $null
    $users = Invoke-AuthAdmin ([Net.Http.HttpMethod]::Get) '/auth/v1/admin/users?page=1&per_page=50' $null
    if (@($users.users).Count -ne 5 -or @($users.users | Where-Object { $_.email -ceq $agentEmail }).Count -ne 0) {
        throw 'Unexpected Auth inventory or Agent email already exists.'
    }
    Write-Output 'PASS Auth preflight'

    $stage = 'authorization'
    Write-Host 'Authorized scope: create one confirmed synthetic Auth user Agent A and insert one agent membership in project A.'
    $approval = Read-Host 'Type AGENT-A-AUTH-AND-MEMBERSHIP-APPROVED to authorize both staging writes'
    if ($approval -cne 'AGENT-A-AUTH-AND-MEMBERSHIP-APPROVED') { throw 'Writes were not authorized.' }

    $authorizedAfter = [DateTime]::UtcNow.ToString('o')
    $stage = 'create-auth-agent'
    $created = Invoke-AuthAdmin ([Net.Http.HttpMethod]::Post) '/auth/v1/admin/users' @{
        email = $agentEmail
        password = $agentPassword
        email_confirm = $true
    }
    $agentPassword = $null
    $agentId = [guid]$created.id
    if ($agentId -eq [guid]::Empty -or $created.email -cne $agentEmail -or
        [string]::IsNullOrWhiteSpace($created.email_confirmed_at)) { throw 'Unexpected Agent Auth response.' }
    $authCreated = $true
    Write-AgentReceipt 'AUTH_CREATED_MEMBERSHIP_PENDING' $agentId $repositoryId $authorizedAfter
    Write-Output 'PASS Agent A Auth creation'

    $stage = 'insert-membership'
    Invoke-StagingPsql @('-X','-w','-v','ON_ERROR_STOP=1','-d',$staging,
        '-v',"agent_id=$agentId",'-v',"repository_id=$repositoryId",
        '-v',"authorized_after=$authorizedAfter",'-v','approval=STAGING-AGENT-APPROVED',
        '-f',$membershipSql) | Write-Output
    $stage = 'postcheck'
    Invoke-StagingPsql @('-X','-w','-v','ON_ERROR_STOP=1','-d',$staging,
        '-v',"agent_id=$agentId",'-v',"repository_id=$repositoryId",'-f',$postcheckSql) | Write-Output
    $confirmed = Invoke-AuthAdmin ([Net.Http.HttpMethod]::Get) "/auth/v1/admin/users/$agentId" $null
    if ([guid]$confirmed.id -ne $agentId -or $confirmed.email -cne $agentEmail) { throw 'Agent Auth postcheck failed.' }
    Write-AgentReceipt 'AGENT_A_PROVISIONED' $agentId $repositoryId $authorizedAfter
    Write-Output "AGENT_A_PROVISIONED receipt=$agentReceiptPath"
} catch {
    $suffix = if ($httpStatus -ge 400) { " HTTP $httpStatus" } else { '' }
    [Console]::Error.WriteLine("FAIL $stage$suffix")
    if ($authCreated) {
        [Console]::Error.WriteLine("Auth user was created with UUID $agentId. Preserve it and reconcile the private Agent receipt. Do not retry creation.")
    }
    exit 1
} finally {
    $stagingPassword = $secretKey = $agentPassword = $confirmation = $approval = $null
    if ($null -ne $http) { $http.Dispose() }
    elseif ($null -ne $handler) { $handler.Dispose() }
    Remove-Item Env:PGPASSWORD,Env:PGSSLROOTCERT -ErrorAction SilentlyContinue
}
