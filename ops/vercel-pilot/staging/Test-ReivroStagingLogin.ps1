#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('reviewer-a','reviewer-b','viewer-a','worker-a','sem-vinculo')]
    [string]$Subject,
    [Parameter(Mandatory)][guid]$UserId,
    [Parameter(Mandatory)][long]$RepoA,
    [Parameter(Mandatory)][long]$RepoB,
    [Parameter(Mandatory)][guid]$RunA,
    [Parameter(Mandatory)][guid]$RunB
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-Hidden([string]$Label) {
    $secret = Read-Host -Prompt $Label -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        $secret.Dispose()
    }
}

function Invoke-Staging([string]$Path, [hashtable]$Payload, [switch]$Rpc) {
    $method = [Net.Http.HttpMethod]::Get
    if ($null -ne $Payload) { $method = [Net.Http.HttpMethod]::Post }
    $request = [Net.Http.HttpRequestMessage]::new($method, $Path)
    try {
        if ($Rpc) { $request.Headers.Add('Content-Profile', 'reivro_checks_api') }
        if ($null -ne $Payload) {
            $json = ConvertTo-Json -InputObject $Payload -Compress
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
try {
    if ($UserId -eq [guid]::Empty -or $RunA -eq [guid]::Empty -or $RunB -eq [guid]::Empty -or
        $RepoA -le 0 -or $RepoB -le 0 -or $RepoA -eq $RepoB -or $RunA -eq $RunB) {
        throw 'Use a valid user ID and distinct projects and runs.'
    }

    $stage = 'api-key'
    $key = (Read-Hidden 'Staging default publishable key').Trim()
    if ($key -cnotmatch '^sb_publishable_[A-Za-z0-9_-]+$') { throw 'Invalid key format.' }

    Add-Type -AssemblyName System.Net.Http
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseCookies = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.BaseAddress = [uri]'https://lbklqqqbmeyseeccdqog.supabase.co'
    $client.Timeout = [TimeSpan]::FromSeconds(15)
    $client.DefaultRequestHeaders.Add('apikey', $key)
    $key = $null
    $null = Invoke-Staging '/auth/v1/settings' $null
    Write-Output "PASS $Subject api-key"

    $stage = 'login'
    $email = (Read-Hidden "Staging email for $Subject").Trim()
    $password = Read-Hidden "Staging password for $Subject"
    try {
        if ([string]::IsNullOrWhiteSpace($email) -or [string]::IsNullOrEmpty($password)) {
            throw 'Email and password required.'
        }
        $session = Invoke-Staging '/auth/v1/token?grant_type=password' @{
            email=$email; password=$password
        } | ConvertFrom-Json
        if ($session.user.id -cne $UserId.ToString() -or
            $session.access_token -cnotmatch '^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){2}$') {
            throw 'Unexpected user or access token.'
        }
        $client.DefaultRequestHeaders.Authorization =
            [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $session.access_token)
    } finally { $email = $password = $session = $null }
    Write-Output "PASS $Subject login"

    $stage = 'auth'
    $identity = Invoke-Staging '/auth/v1/user' $null | ConvertFrom-Json
    if ($identity.id -cne $UserId.ToString() -or
        $identity.is_anonymous -isnot [bool] -or $identity.is_anonymous) {
        throw 'Unexpected identity.'
    }
    Write-Output "PASS $Subject auth"

    $fixtures = @(
        @{ scope='A'; repo=$RepoA; run=$RunA; visible=($Subject -in 'reviewer-a','viewer-a') }
        @{ scope='B'; repo=$RepoB; run=$RunB; visible=($Subject -eq 'reviewer-b') }
    )
    foreach ($item in $fixtures) {
        $stage = "legacy read $($item.scope)"
        $body = Invoke-Staging '/rest/v1/rpc/read_run' @{
            p_repository_id=$item.repo; p_run_id=$item.run.ToString()
        } -Rpc
        if ($item.visible) {
            $result = $body | ConvertFrom-Json
            if ($result.run.id -cne $item.run.ToString() -or
                $null -ne $result.run.task_submission_id) { throw 'Unexpected legacy run.' }
        } elseif ($body.Trim() -cne 'null') {
            throw 'Unexpected access or response.'
        }
        Write-Output "PASS $Subject $stage"
    }
} catch {
    $suffix = if ($null -ne $httpStatus) { " HTTP $httpStatus" } else { '' }
    [Console]::Error.WriteLine("FAIL $Subject $stage$suffix")
    if ($stage -eq 'api-key') {
        [Console]::Error.WriteLine('Use the default publishable key from the staging project API Keys page.')
    }
    exit 1
} finally {
    if ($null -ne $client) { $client.Dispose() }
    elseif ($null -ne $handler) { $handler.Dispose() }
}
