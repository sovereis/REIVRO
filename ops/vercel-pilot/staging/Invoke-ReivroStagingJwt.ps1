#requires -Version 5.1
[CmdletBinding(DefaultParameterSetName='Legacy')]
param(
    [Parameter(Mandatory, ParameterSetName='Legacy')]
    [ValidateSet('reviewer-a','reviewer-b','viewer-a','worker-a','sem-vinculo')]
    [string]$Subject,
    [Parameter(Mandatory, ParameterSetName='Legacy')][long]$RepoA,
    [Parameter(Mandatory, ParameterSetName='Legacy')][long]$RepoB,
    [Parameter(Mandatory, ParameterSetName='Legacy')][guid]$RunA,
    [Parameter(Mandatory, ParameterSetName='Legacy')][guid]$RunB,
    [Parameter(Mandatory, ParameterSetName='Fixture')]
    [ValidateSet('approve_contract','submit')][string]$FixtureAction,
    [Parameter(Mandatory, ParameterSetName='Fixture')][string]$Plan,
    [Parameter(Mandatory, ParameterSetName='Fixture')][string]$Approval,
    [Parameter(Mandatory)][guid]$UserId
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Read-Hidden([string]$Label) {
    $secret = Read-Host -Prompt $Label -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        $secret.Dispose()
    }
}

function Invoke-Staging([string]$Path, [hashtable]$Payload) {
    $method = [Net.Http.HttpMethod]::Get
    if ($null -ne $Payload) { $method = [Net.Http.HttpMethod]::Post }
    $request = [Net.Http.HttpRequestMessage]::new($method, $Path)
    try {
        if ($null -ne $Payload) {
            $request.Headers.Add('Content-Profile', 'reivro_checks_api')
            $json = ConvertTo-Json -InputObject $Payload -Depth 12 -Compress
            $request.Content = [Net.Http.StringContent]::new($json, [Text.Encoding]::UTF8, 'application/json')
        }
        $response = $client.SendAsync($request).GetAwaiter().GetResult()
        try {
            if (-not $response.IsSuccessStatusCode) {
                $script:httpStatus = [int]$response.StatusCode
                throw 'Unexpected HTTP status.'
            }
            $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        } finally { $response.Dispose() }
    } finally { $request.Dispose() }
}

$stage = 'inputs'
$httpStatus = $null
$client = $null
$handler = $null
$writeStarted = $false
try {
    if ($UserId -eq [guid]::Empty) { throw 'Invalid user.' }
    if ($PSCmdlet.ParameterSetName -eq 'Legacy') {
        if ($RepoA -le 0 -or $RepoB -le 0 -or $RepoA -eq $RepoB -or
            $RunA -eq [guid]::Empty -or $RunB -eq [guid]::Empty -or $RunA -eq $RunB) {
            throw 'Use two distinct repositories and runs.'
        }
    } else {
        if ($Approval -cne 'STAGING-FIXTURE-APPROVED') { throw 'Approval required.' }
        $fixture = Get-Content -LiteralPath $Plan -Raw | ConvertFrom-Json
        $contractId = [guid]$fixture.contract_id
        $submissionId = [guid]$fixture.submission_id
        $repositoryId = [long]$fixture.repository_id
        $base = [string]$fixture.base_sha
        $head = [string]$fixture.head_sha
        $digest = [string]$fixture.digest
        if ($fixture.staging_ref -cne 'lbklqqqbmeyseeccdqog' -or $repositoryId -le 0 -or
            $contractId -eq [guid]::Empty -or $submissionId -eq [guid]::Empty -or
            $contractId -eq $submissionId -or $base -cnotmatch '^[0-9a-f]{40}$' -or
            $head -cnotmatch '^[0-9a-f]{40}$' -or $base -ceq $head -or
            $digest -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid fixture plan.' }
        $expectedUser = [guid]$fixture.reviewer_id
        if ($FixtureAction -eq 'submit') { $expectedUser = [guid]$fixture.agent_id }
        if ($UserId -ne $expectedUser) { throw 'Unexpected fixture user.' }
        $ack = Read-Host "Confirmed operator authorization for $FixtureAction, staging repository $repositoryId (type APPLY)"
        if ($ack -cne 'APPLY') { throw 'Aborted.' }
    }

    $stage = 'credentials'
    $key = Read-Hidden 'Staging publishable key'
    $jwt = Read-Hidden 'Staging user access token (JWT)'
    if ($key -cnotmatch '^sb_publishable_[A-Za-z0-9_-]+$' -or
        $jwt -cnotmatch '^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){2}$') { throw 'Invalid credentials.' }

    Add-Type -AssemblyName System.Net.Http
    # Windows PowerShell uses the .NET Framework TLS defaults.
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.BaseAddress = [uri]'https://lbklqqqbmeyseeccdqog.supabase.co'
    $client.Timeout = [TimeSpan]::FromSeconds(15)
    $client.DefaultRequestHeaders.Add('apikey', $key)
    $client.DefaultRequestHeaders.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $jwt)
    $key = $jwt = $null

    $stage = 'auth'
    $identity = Invoke-Staging '/auth/v1/user' $null | ConvertFrom-Json
    if ($identity.id -cne $UserId.ToString() -or $identity.is_anonymous -isnot [bool] -or
        $identity.is_anonymous) { throw 'Unexpected identity.' }
    Write-Output 'PASS auth'
    if ($PSCmdlet.ParameterSetName -eq 'Legacy') {
        $fixtures = @(
            @{ scope='A'; repo=$RepoA; run=$RunA; visible=($Subject -in 'reviewer-a','viewer-a') }
            @{ scope='B'; repo=$RepoB; run=$RunB; visible=($Subject -eq 'reviewer-b') }
        )
        foreach ($item in $fixtures) {
            $stage = "legacy read $($item.scope)"
            $body = Invoke-Staging '/rest/v1/rpc/read_run' @{
                p_repository_id=$item.repo; p_run_id=$item.run.ToString()
            }
            if ($item.visible) {
                $result = $body | ConvertFrom-Json
                if ($result.run.id -cne $item.run.ToString() -or
                    $null -ne $result.run.task_submission_id) { throw 'Unexpected legacy run.' }
            } elseif ($body.Trim() -cne 'null') { throw 'Unexpected access or response.' }
            Write-Output "PASS $Subject $stage"
        }
    } else {
        $stage = $FixtureAction
        $payload = @{ repository_id=$repositoryId; version=1; digest=$digest }
        if ($FixtureAction -eq 'approve_contract') {
            $payload.id = $contractId.ToString()
            $payload.document = @{ base_sha=$base; criteria=@(@{ kind='exists'; path='guide.md' }) }
        } else {
            $payload.id = $submissionId.ToString()
            $payload.contract_id = $contractId.ToString()
            $payload.head_sha = $head
        }
        $writeStarted = $true
        $result = Invoke-Staging '/rest/v1/rpc/task_dispatch' @{
            action=$FixtureAction; request=$payload
        } | ConvertFrom-Json
        if ($result.id -cne $payload.id -or
            ($FixtureAction -eq 'approve_contract' -and $result.digest -cne $digest)) {
            throw 'Unexpected fixture receipt.'
        }
        Write-Output "PASS $stage"
    }
} catch {
    $suffix = if ($null -ne $httpStatus) { " HTTP $httpStatus" } else { '' }
    [Console]::Error.WriteLine("FAIL $stage$suffix")
    if ($writeStarted) {
        [Console]::Error.WriteLine('Reconcile persisted fixture IDs before any retry.')
    }
    exit 1
} finally {
    if ($null -ne $client) { $client.Dispose() }
    elseif ($null -ne $handler) { $handler.Dispose() }
}
