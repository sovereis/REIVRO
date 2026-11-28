#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Plan)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$failed=$false
function Result([string]$Field,[bool]$Pass){if($Pass){Write-Output "PASS $Field"}else{Write-Output "FAIL $Field";$script:failed=$true}}
try{
 if(-not(Test-Path -LiteralPath $Plan -PathType Leaf)){Write-Output 'FAIL plan-file';exit 1}
 try{$doc=Get-Content -LiteralPath $Plan -Raw|ConvertFrom-Json}catch{Write-Output 'FAIL plan-json';exit 1}
 $p=$doc.PSObject.Properties['staging_ref'];Result 'staging_ref' ($null -ne $p -and $p.Value -is [string] -and $p.Value -cEQ 'lbklqqqbmeyseeccdqog')
 $p=$doc.PSObject.Properties['agent_id'];[guid]$g=[guid]::Empty;$agentOk=$false;if($null -ne $p -and $p.Value -is [string]){$agentOk=[guid]::TryParse($p.Value,[ref]$g) -and $g -eq [guid]'0dae2b29-adaa-48b6-9a96-e9ac646b2a7a'};Result 'agent_id' $agentOk
 $p=$doc.PSObject.Properties['base_sha'];Result 'base_sha' ($null -ne $p -and $p.Value -is [string] -and $p.Value -cEQ '07fc0b907d3aa9659ea7541f80acf6c18586e645')
 $p=$doc.PSObject.Properties['head_sha'];Result 'head_sha' ($null -ne $p -and $p.Value -is [string] -and $p.Value -cEQ 'e0d50dd239f8c8c3c39df84187741009f7496d09')
 $p=$doc.PSObject.Properties['digest'];Result 'digest' ($null -ne $p -and $p.Value -is [string] -and $p.Value -cmatch '^[0-9a-f]{64}$')
 if($failed){Write-Output 'PLAN_READ_ONLY_DIAGNOSTIC_FAIL';exit 1}
 Write-Output 'PLAN_READ_ONLY_DIAGNOSTIC_PASS'
}catch{Write-Output 'FAIL diagnostic-runtime';exit 1}
