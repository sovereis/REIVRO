#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ReivroConcurrentClaimClassification.ps1')
function Case([string]$Name,[string[]]$States,[bool]$Expected) {
    $bodies = @($States | ForEach-Object { [pscustomobject]@{ state = $_ } })
    $actual = Get-ReivroConcurrentClaimClassification $bodies
    if ([bool]$actual.Pass -ne $Expected) { throw "Regression case failed: $Name" }
    Write-Output "PASS classifier=$Name total=$($actual.Total) running=$($actual.Running) busy=$($actual.Busy) other=$($actual.Other)"
}
Case 'one-running-three-busy' @('running','busy','busy','busy') $true
Case 'inverted-three-running-one-busy' @('running','running','running','busy') $false
Case 'all-busy' @('busy','busy','busy','busy') $false
Case 'two-and-two' @('running','running','busy','busy') $false
Case 'unexpected-state' @('running','busy','busy','unknown') $false
Write-Output 'CONCURRENT_CLAIM_CLASSIFIER_REGRESSION_PASS'
