#requires -Version 5.1
function Get-ReivroIdempotencyRedeliveryClassification([object[]]$Observations) {
    $items = @($Observations)
    $absent = @($items | Where-Object { $_.Kind -ceq 'absence_of_commit' -and [bool]$_.Pass }).Count
    $lost = @($items | Where-Object { $_.Kind -ceq 'response_lost' -and [bool]$_.Pass }).Count
    $known = @($items | Where-Object { $_.Kind -ceq 'known_response' -and [bool]$_.Pass }).Count
    $conflict = @($items | Where-Object { $_.Kind -ceq 'conflicting_replay' -and [bool]$_.Pass }).Count
    $unknown = @($items | Where-Object { $_.Kind -cnotin @(
        'absence_of_commit','response_lost','known_response','conflicting_replay'
    ) }).Count
    $failed = @($items | Where-Object { -not [bool]$_.Pass }).Count
    $duplicates = @(
        'absence_of_commit','response_lost','known_response','conflicting_replay' |
            Where-Object {
                $kind = $_
                @($items | Where-Object { $_.Kind -ceq $kind }).Count -ne 1
            }
    ).Count

    [pscustomobject]@{
        Total = $items.Count
        AbsenceOfCommit = $absent
        ResponseLost = $lost
        KnownResponse = $known
        ConflictingReplay = $conflict
        Unknown = $unknown
        Failed = $failed
        BadCardinality = $duplicates
        Pass = ($items.Count -eq 4 -and $absent -eq 1 -and $lost -eq 1 -and
            $known -eq 1 -and $conflict -eq 1 -and $unknown -eq 0 -and
            $failed -eq 0 -and $duplicates -eq 0)
    }
}
