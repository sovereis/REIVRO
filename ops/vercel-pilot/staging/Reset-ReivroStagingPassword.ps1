#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('reviewer-a','reviewer-b','viewer-a','worker-a','sem-vinculo')]
    [string]$Subject,
    [Parameter(Mandatory)][guid]$UserId,
    [switch]$Apply
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

function Invoke-AuthAdmin([Net.Http.HttpMethod]$Method, [string]$Path, [string]$Password) {
    $request = [Net.Http.HttpRequestMessage]::new($Method, $Path)
    try {
        if ($Method -eq [Net.Http.HttpMethod]::Put) {
            $json = ConvertTo-Json -InputObject @{password=$Password} -Compress
            $request.Content = [Net.Http.StringContent]::new($json, [Text.Encoding]::UTF8, 'application/json')
        }
        $response = $client.SendAsync($request).GetAwaiter().GetResult()
        try {
            $script:httpStatus = [int]$response.StatusCode
            if (-not $response.IsSuccessStatusCode) { throw 'Auth rejected the request.' }
            $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        } finally { $response.Dispose() }
    } finally { $request.Dispose() }
}

# SHA256 of each role label and the UUID from the approved staging inventory.
$targets = @{
    'reviewer-a' = '64844df4046aefa19efb9165a20451e9353ca1c443f95e39aa0ee6ce46247009'
    'reviewer-b' = 'cd8a6e034aafa36e81dff66d3940076cd38dadb331f0fb2213eb8cc1f9689d3b'
    'viewer-a' = '9530eb1a6d5cfc101489e129d9db3a5543e44193ef910af1ecc40a16dc35e657'
    'worker-a' = 'fb7280fa780a84ee9df26c753beaf7d013f4ff1d004ee109d9c4c65eb81ed4c9'
    'sem-vinculo' = '99ffaac220b79d4040662b434a51c615db81b46566e8e58ce04248639bbd659e'
}

$stage = 'target'
$client = $handler = $httpStatus = $null
$writeStarted = $false
try {
    $Subject = $Subject.ToLowerInvariant()
    $id = $UserId.ToString()
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $fingerprint = [BitConverter]::ToString($sha.ComputeHash(
            [Text.Encoding]::UTF8.GetBytes("${Subject}:$id"))).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
    if ($fingerprint -cne $targets[$Subject]) { throw 'Unexpected staging target.' }

    $stage = 'admin-key'
    $key = (Read-Hidden 'Existing staging secret API key').Trim()
    $legacy = $false
    if ($key -cnotmatch '^sb_secret_[A-Za-z0-9_-]+$') {
        if ($key -cnotmatch '^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$') { throw 'Invalid key format.' }
        $claims64 = $key.Split('.')[1].Replace('-', '+').Replace('_', '/')
        $claims64 += '=' * ((4 - ($claims64.Length % 4)) % 4)
        $claims = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($claims64)) | ConvertFrom-Json
        if ($claims.role -cne 'service_role' -or $claims.ref -cne 'lbklqqqbmeyseeccdqog') {
            throw 'Expected a legacy service_role key for staging.'
        }
        $legacy = $true
    }

    Add-Type -AssemblyName System.Net.Http
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseCookies = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.BaseAddress = [uri]'https://lbklqqqbmeyseeccdqog.supabase.co'
    $client.Timeout = [TimeSpan]::FromSeconds(20)
    $client.DefaultRequestHeaders.Add('apikey', $key)
    if ($legacy) {
        $client.DefaultRequestHeaders.Authorization =
            [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $key)
    }
    $key = $null

    $path = "/auth/v1/admin/users/$id"
    $stage = 'preflight'
    $before = Invoke-AuthAdmin ([Net.Http.HttpMethod]::Get) $path
    if ($before.id -cne $id -or [string]::IsNullOrWhiteSpace($before.email) -or
        [string]::IsNullOrWhiteSpace($before.email_confirmed_at)) { throw 'Unexpected Auth identity.' }
    Write-Output "PASS $Subject preflight"
    if (-not $Apply) { return }

    $stage = 'password'
    $suffix = "-$Subject"
    try {
        $password = Read-Hidden "New password ending in $suffix (save in private vault first)"
        $confirmation = Read-Hidden 'Confirm new password'
        if ($password -cne $confirmation -or
            -not $password.EndsWith($suffix, [StringComparison]::Ordinal) -or
            $password.Length -lt (24 + $suffix.Length) -or
            [Text.Encoding]::UTF8.GetByteCount($password) -gt 72) { throw 'Password check failed.' }
        $confirmation = $null
        $stage = 'reset'
        $httpStatus = $null
        $writeStarted = $true
        $updated = Invoke-AuthAdmin ([Net.Http.HttpMethod]::Put) $path $password
        if ($updated.id -cne $id) { throw 'Unexpected reset response.' }
    } finally { $password = $confirmation = $null }

    $stage = 'postcheck'
    $httpStatus = $null
    $after = Invoke-AuthAdmin ([Net.Http.HttpMethod]::Get) $path
    if ($after.id -cne $id -or $after.email -cne $before.email -or
        $after.role -cne $before.role -or $after.email_confirmed_at -cne $before.email_confirmed_at) {
        throw 'Auth identity changed unexpectedly.'
    }
    Write-Output "PASS $Subject reset"
} catch {
    $suffix = if ($httpStatus -ge 400) { " HTTP $httpStatus" } else { '' }
    [Console]::Error.WriteLine("FAIL $Subject $stage$suffix")
    if ($writeStarted) {
        [Console]::Error.WriteLine('Check the intended password with the login kit before retrying.')
    }
    exit 1
} finally {
    if ($null -ne $client) { $client.Dispose() }
    elseif ($null -ne $handler) { $handler.Dispose() }
}
