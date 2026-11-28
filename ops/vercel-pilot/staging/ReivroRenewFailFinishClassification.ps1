#requires -Version 5.1
function Get-ReivroRenewFailFinishClassification([object[]]$Responses) {
    $items = @($Responses)
    $renew = @($items | Where-Object { $_.Action -ceq 'renew' -and [bool]$_.Success }).Count
    $fail = @($items | Where-Object { $_.Action -ceq 'fail' -and [bool]$_.Success }).Count
    $finish = @($items | Where-Object { $_.Action -ceq 'finish' -and [bool]$_.Success }).Count
    $unknown = @($items | Where-Object { $_.Action -cnotin @('renew','fail','finish') }).Count
    $badStatus = @($items | Where-Object { -not ([bool]$_.Success) -and ([int]$_.Status -lt 400 -or [int]$_.Status -ge 500) }).Count
    $badCardinality = @('renew','fail','finish' | Where-Object { $name=$_; @($items | Where-Object { $_.Action -ceq $name }).Count -ne 1 }).Count
    $badSuccessState = @($items | Where-Object {
        [bool]$_.Success -and (
            ($_.Action -ceq 'renew' -and $_.State -cne 'running') -or
            ($_.Action -ceq 'fail' -and $_.State -cne 'retryable') -or
            ($_.Action -ceq 'finish' -and $_.State -cne 'completed'))
    }).Count
    $closing = $fail + $finish
    $state = if ($finish -eq 1) { 'completed' } elseif ($fail -eq 1) { 'retryable' } else { 'invalid' }
    $journalDelta = $renew + $finish + (2 * $fail)
    [pscustomobject]@{
        Total=$items.Count; RenewSuccess=$renew; FailSuccess=$fail; FinishSuccess=$finish
        ClosingSuccess=$closing; Unknown=$unknown; BadStatus=$badStatus
        BadCardinality=$badCardinality; BadSuccessState=$badSuccessState; ExpectedState=$state
        ExpectedJournal=(47 + $journalDelta)
        Pass=($items.Count -eq 3 -and $unknown -eq 0 -and $badStatus -eq 0 -and
            $badCardinality -eq 0 -and $badSuccessState -eq 0 -and $renew -le 1 -and $closing -eq 1)
    }
}
