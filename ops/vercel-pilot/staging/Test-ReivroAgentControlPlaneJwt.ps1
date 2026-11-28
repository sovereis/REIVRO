#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ReceiptDirectory,
    [Parameter(Mandatory)][long]$RepositoryBId
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

function Send-Staging([Net.Http.HttpMethod]$Method, [string]$Path, [object]$Payload, [switch]$Rpc) {
    $request = [Net.Http.HttpRequestMessage]::new($Method, $Path)
    try {
        if ($Rpc) { $request.Headers.Add('Content-Profile', 'reivro_checks_api') }
        if ($null -ne $Payload) {
            $json = ConvertTo-Json -InputObject $Payload -Depth 12 -Compress
            $request.Content = [Net.Http.StringContent]::new($json,[Text.Encoding]::UTF8,'application/json')
        }
        $response = $script:client.SendAsync($request).GetAwaiter().GetResult()
        try {
            [pscustomobject]@{
                Status = [int]$response.StatusCode
                Body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            }
        } finally { $response.Dispose() }
    } finally { $request.Dispose() }
}

function Assert-Success([object]$Response, [string]$Stage) {
    if ($Response.Status -lt 200 -or $Response.Status -ge 300) {
        throw "$Stage returned HTTP $($Response.Status)."
    }
}

function Assert-Denied([object]$Response, [string]$Stage) {
    if ($Response.Status -notin 400,403) {
        throw "$Stage was not denied (HTTP $($Response.Status))."
    }
}

$stage = 'receipt'
$client = $handler = $key = $email = $password = $session = $null
try {
    $receiptPath = Join-Path $ReceiptDirectory 'agent-a-provisioning-receipt.json'
    if (-not (Test-Path -LiteralPath $receiptPath)) { throw 'Private Agent receipt not found.' }
    $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    if ($receipt.state -cne 'AGENT_A_PROVISIONED' -or
        $receipt.staging_ref -cne 'lbklqqqbmeyseeccdqog') { throw 'Agent receipt is not provisioned.' }
    $agentId = [guid]$receipt.agent_id
    $repositoryAId = [long]$receipt.repository_id
    if ($agentId -eq [guid]::Empty -or $repositoryAId -le 0 -or
        $RepositoryBId -le 0 -or $RepositoryBId -eq $repositoryAId) {
        throw 'Invalid Agent or repository inventory.'
    }

    $stage = 'credentials'
    $key = (Read-Hidden 'Staging default publishable key').Trim()
    $email = (Read-Hidden 'Agent A staging email').Trim()
    $password = Read-Hidden 'Agent A staging password'
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

    $stage = 'login'
    $response = Send-Staging ([Net.Http.HttpMethod]::Post) '/auth/v1/token?grant_type=password' @{
        email=$email; password=$password
    }
    Assert-Success $response $stage
    $session = $response.Body | ConvertFrom-Json
    if ($session.user.id -cne $agentId.ToString() -or
        $session.access_token -cnotmatch '^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){2}$') {
        throw 'Login returned an unexpected identity or token.'
    }
    $client.DefaultRequestHeaders.Authorization =
        [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer',$session.access_token)
    $email = $password = $session = $null
    Write-Output 'PASS Agent A login'

    $stage = 'auth'
    $response = Send-Staging ([Net.Http.HttpMethod]::Get) '/auth/v1/user' $null
    Assert-Success $response $stage
    $identity = $response.Body | ConvertFrom-Json
    if ($identity.id -cne $agentId.ToString() -or
        $identity.is_anonymous -isnot [bool] -or $identity.is_anonymous) {
        throw 'Auth returned an unexpected Agent identity.'
    }
    Write-Output 'PASS Agent A Auth identity'

    $stage = 'legacy isolation'
    $response = Send-Staging ([Net.Http.HttpMethod]::Post) '/rest/v1/rpc/read_run' @{
        p_repository_id=$repositoryAId; p_run_id=[guid]::NewGuid().ToString()
    } -Rpc
    Assert-Success $response $stage
    if ($response.Body.Trim() -cne 'null') { throw 'Agent unexpectedly read a legacy run.' }
    Write-Output 'PASS Agent A legacy isolation'

    $stage = 'reviewer boundary'
    $subject = [guid]::NewGuid().ToString()
    $response = Send-Staging ([Net.Http.HttpMethod]::Post) '/rest/v1/rpc/task_dispatch' @{
        action='approve_contract'; request=@{
            repository_id=$repositoryAId; id=$subject; version=1; digest=('0' * 64)
            document=@{base_sha=('0' * 40);criteria=@(@{kind='exists';path='guide.md'})}
        }
    } -Rpc
    Assert-Denied $response $stage
    Write-Output 'PASS Agent A cannot approve contracts'

    $stage = 'project A ownership boundary'
    $response = Send-Staging ([Net.Http.HttpMethod]::Post) '/rest/v1/rpc/task_dispatch' @{
        action='read'; request=@{repository_id=$repositoryAId;id=[guid]::NewGuid().ToString()}
    } -Rpc
    Assert-Denied $response $stage
    Write-Output 'PASS Agent A cannot read an unknown submission'

    $stage = 'cross-project boundary'
    $response = Send-Staging ([Net.Http.HttpMethod]::Post) '/rest/v1/rpc/task_dispatch' @{
        action='read'; request=@{repository_id=$RepositoryBId;id=[guid]::NewGuid().ToString()}
    } -Rpc
    Assert-Denied $response $stage
    Write-Output 'PASS Agent A cross-project isolation'
    Write-Output 'AGENT_A_JWT_READ_ONLY_PASS'
} catch {
    [Console]::Error.WriteLine("FAIL $stage")
    exit 1
} finally {
    $key = $email = $password = $session = $identity = $response = $null
    if ($null -ne $client) { $client.DefaultRequestHeaders.Authorization = $null; $client.Dispose() }
    elseif ($null -ne $handler) { $handler.Dispose() }
}
