#requires -Version 5.1
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Read-Hidden([string]$Label) {
    $secure = Read-Host $Label -AsSecureString
    try {
        if ($secure.Length -eq 0) { throw 'Empty value.' }
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    }
    finally { $secure.Dispose() }
}

function Test-Login(
    [Net.Http.HttpClient]$Client,
    [string]$Label,
    [guid]$ExpectedId,
    [string]$Email,
    [string]$Password
) {
    $request = [Net.Http.HttpRequestMessage]::new(
        [Net.Http.HttpMethod]::Post,'/auth/v1/token?grant_type=password'
    )
    try {
        $request.Content = [Net.Http.StringContent]::new(
            (ConvertTo-Json @{email=$Email;password=$Password} -Compress),
            [Text.Encoding]::UTF8,'application/json'
        )
        $response = $Client.SendAsync($request).GetAwaiter().GetResult()
        try {
            $bodyText = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            if (-not $response.IsSuccessStatusCode) {
                $errorCode = 'unknown'
                try {
                    $body = $bodyText | ConvertFrom-Json
                    if ($null -ne $body.PSObject.Properties['error_code']) {
                        $candidate = [string]$body.error_code
                        if ($candidate -cmatch '^[a-z0-9_]{1,64}$') { $errorCode = $candidate }
                    }
                }
                catch { $errorCode = 'unparseable' }
                return [pscustomobject]@{
                    Label=$Label;Pass=$false;Status=[int]$response.StatusCode;Code=$errorCode
                }
            }

            $body = $bodyText | ConvertFrom-Json
            $actualId = [guid]$body.user.id
            $body.access_token = $null
            $body.refresh_token = $null
            if ($actualId -ne $ExpectedId) {
                return [pscustomobject]@{
                    Label=$Label;Pass=$false;Status=[int]$response.StatusCode;Code='uuid_mismatch'
                }
            }
            [pscustomobject]@{
                Label=$Label;Pass=$true;Status=[int]$response.StatusCode;Code='ok'
            }
        }
        finally { $response.Dispose() }
    }
    finally { $request.Dispose() }
}

$client = $handler = $publishableKey = $null
$entries = @()
try {
    Add-Type -AssemblyName System.Net.Http
    $publishableKey = (Read-Hidden 'Staging publishable key').Trim()
    $entries = @(
        [pscustomobject]@{
            Label='ReviewerA';Expected=[guid]'18c4dc88-f51b-462e-a87e-c43a494f2a66'
            Email=(Read-Hidden 'Reviewer A email');Password=(Read-Hidden 'Reviewer A password')
        }
        [pscustomobject]@{
            Label='AgentA';Expected=[guid]'0dae2b29-adaa-48b6-9a96-e9ac646b2a7a'
            Email=(Read-Hidden 'Agent A email');Password=(Read-Hidden 'Agent A password')
        }
        [pscustomobject]@{
            Label='WorkerA';Expected=[guid]'70e74944-e39e-4aa2-90ce-a94e8549c2d4'
            Email=(Read-Hidden 'Worker A email');Password=(Read-Hidden 'Worker A password')
        }
    )

    $handler = [Net.Http.HttpClientHandler]::new()
    $client = [Net.Http.HttpClient]::new($handler)
    $client.BaseAddress = [uri]'https://lbklqqqbmeyseeccdqog.supabase.co'
    $client.DefaultRequestHeaders.Add('apikey',$publishableKey)

    $results = @()
    foreach ($entry in $entries) {
        $result = Test-Login $client $entry.Label $entry.Expected $entry.Email $entry.Password
        $results += @($result)
        $entry.Email = $null
        $entry.Password = $null
        Write-Output ("{0} identity={1} status={2} code={3}" -f
            $(if ($result.Pass) {'PASS'} else {'FAIL'}),
            $result.Label,$result.Status,$result.Code)
    }

    $failures = @($results | Where-Object { -not [bool]$_.Pass }).Count
    if ($failures -ne 0) { throw "AUTH_DIAGNOSTIC_FAILED count=$failures" }
    Write-Output 'CONTROL_PLANE_THREE_IDENTITY_AUTH_PASS'
    Write-Output 'NO_CONTROL_PLANE_RPCS_CALLED'
}
finally {
    $publishableKey = $null
    foreach ($entry in $entries) { $entry.Email=$null;$entry.Password=$null }
    if ($null -ne $client) { $client.Dispose() }
    elseif ($null -ne $handler) { $handler.Dispose() }
}
