#requires -Version 5.1
function Get-ReivroConcurrentClaimClassification([object[]]$Bodies) {
    $items = @($Bodies)
    $runningCount = @($items | Where-Object { [string]$_.state -ceq 'running' }).Count
    $busyCount = @($items | Where-Object { [string]$_.state -ceq 'busy' }).Count
    $otherCount = $items.Count - $runningCount - $busyCount
    [pscustomobject]@{
        Total = $items.Count
        Running = $runningCount
        Busy = $busyCount
        Other = $otherCount
        Pass = ($items.Count -eq 4 -and $runningCount -eq 1 -and $busyCount -eq 3 -and $otherCount -eq 0)
    }
}
