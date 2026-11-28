#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'ReivroRenewFailFinishClassification.ps1')
function Response([string]$Action,[bool]$Success){
 $state=if(-not $Success){$null}elseif($Action -ceq 'renew'){'running'}elseif($Action -ceq 'fail'){'retryable'}else{'completed'}
 [pscustomobject]@{Action=$Action;Success=$Success;Status=$(if($Success){200}else{403});State=$state}
}
function Case([string]$Name,[object[]]$Responses,[int]$Renew,[int]$Fail,[int]$Finish,[string]$State,[int]$Journal){
 $c=Get-ReivroRenewFailFinishClassification $Responses
 if(-not$c.Pass-or$c.RenewSuccess-ne$Renew-or$c.FailSuccess-ne$Fail-or$c.FinishSuccess-ne$Finish-or$c.ExpectedState-cne$State-or$c.ExpectedJournal-ne$Journal){throw "Classification failed: $Name"}
 Write-Output "PASS order=$Name renew=$Renew fail=$Fail finish=$Finish state=$State journal=$Journal"
}
# All six serialization orders. Renew succeeds only when serialized before the closer.
Case 'renew-fail-finish' @((Response renew $true),(Response fail $true),(Response finish $false)) 1 1 0 retryable 50
Case 'renew-finish-fail' @((Response renew $true),(Response finish $true),(Response fail $false)) 1 0 1 completed 49
Case 'fail-renew-finish' @((Response fail $true),(Response renew $false),(Response finish $false)) 0 1 0 retryable 49
Case 'fail-finish-renew' @((Response fail $true),(Response finish $false),(Response renew $false)) 0 1 0 retryable 49
Case 'finish-renew-fail' @((Response finish $true),(Response renew $false),(Response fail $false)) 0 0 1 completed 48
Case 'finish-fail-renew' @((Response finish $true),(Response fail $false),(Response renew $false)) 0 0 1 completed 48
$bad=Get-ReivroRenewFailFinishClassification @((Response renew $true),(Response fail $true),(Response finish $true));if($bad.Pass){throw 'Two closing transitions were accepted.'}
Write-Output 'PASS rejects-two-closing-transitions'
$duplicate=Get-ReivroRenewFailFinishClassification @((Response renew $true),(Response fail $true),(Response fail $false));if($duplicate.Pass){throw 'Duplicate action was accepted.'}
Write-Output 'PASS rejects-duplicate-action'
$badState=@((Response renew $true),(Response fail $false),(Response finish $true));$badState[0].State='completed';if((Get-ReivroRenewFailFinishClassification $badState).Pass){throw 'Invalid successful state was accepted.'}
Write-Output 'PASS rejects-invalid-success-state'
Write-Output 'RENEW_FAIL_FINISH_CLASSIFIER_REGRESSION_PASS'
