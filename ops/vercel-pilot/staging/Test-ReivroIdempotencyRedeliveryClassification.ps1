#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ReivroIdempotencyRedeliveryClassification.ps1')

function Observation([string]$Kind,[bool]$Pass) {
    [pscustomobject]@{ Kind = $Kind; Pass = $Pass }
}

$valid = @(
    (Observation 'absence_of_commit' $true)
    (Observation 'response_lost' $true)
    (Observation 'known_response' $true)
    (Observation 'conflicting_replay' $true)
)
$result = Get-ReivroIdempotencyRedeliveryClassification $valid
if (-not $result.Pass) { throw 'Valid classification rejected.' }
Write-Output 'PASS classifier-valid-four-categories'

$missing = Get-ReivroIdempotencyRedeliveryClassification @($valid[0..2])
if ($missing.Pass) { throw 'Missing category accepted.' }
Write-Output 'PASS classifier-rejects-missing-category'

$duplicate = Get-ReivroIdempotencyRedeliveryClassification @(
    $valid[0],$valid[1],$valid[2],$valid[2]
)
if ($duplicate.Pass) { throw 'Duplicate category accepted.' }
Write-Output 'PASS classifier-rejects-duplicate-category'

$failed = @($valid)
$failed[1] = Observation 'response_lost' $false
if ((Get-ReivroIdempotencyRedeliveryClassification $failed).Pass) {
    throw 'Failed observation accepted.'
}
Write-Output 'PASS classifier-rejects-failed-observation'
Write-Output 'IDEMPOTENCY_REDELIVERY_CLASSIFIER_PASS'
