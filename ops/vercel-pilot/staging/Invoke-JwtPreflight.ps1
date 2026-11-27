[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][ValidateSet('agent','reviewer','worker','viewer','other-reviewer','no-membership')][string]$Role,
 [Parameter(Mandatory=$true)][string]$Manifest,
 [ValidateSet('auth','legacy-read','task-read')][string]$Phase='auth',
 [string]$Python='python.exe'
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Manifest=(Resolve-Path -LiteralPath $Manifest).Path
$Runner=Join-Path $PSScriptRoot 'jwt_preflight.py'
if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) { throw 'Runner missing' }
# No login, session refresh, provisioning, approval, migration, or write action.
& $Python -I $Runner --role $Role --phase $Phase --manifest $Manifest
$Code=$LASTEXITCODE
if ($Code -eq 2) { throw 'BLOCKED: inspect the sanitized JSON; do not provision automatically' }
if ($Code -ne 0) { throw 'FAIL: stop dependent operations and preserve sanitized evidence' }
