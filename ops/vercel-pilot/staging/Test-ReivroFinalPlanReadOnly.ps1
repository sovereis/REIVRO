#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory)][string]$PlanPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$failed=$false
function Result([string]$Field,[bool]$Pass){if($Pass){Write-Output "PASS $Field"}else{Write-Output "FAIL $Field";$script:failed=$true}}
try{
 . (Join-Path $PSScriptRoot 'ReivroFinalPlanValidation.ps1')
 $validation=Get-ReivroFinalPlanValidation $PlanPath
 foreach($field in @('staging_ref','agent_id','base_sha','head_sha','digest')){Result $field ([bool]$validation.Results[$field])}
 if($failed){Write-Output 'PLAN_READ_ONLY_DIAGNOSTIC_FAIL';exit 1}
 Write-Output 'PLAN_READ_ONLY_DIAGNOSTIC_PASS'
}catch{Write-Output 'FAIL diagnostic-runtime';exit 1}
