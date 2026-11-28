#requires -Version 5.1
function Get-ReivroFinalPlanValidation([string]$PlanPath){
 if(-not(Test-Path -LiteralPath $PlanPath -PathType Leaf)){throw 'Private plan file is missing.'}
 try{$planDoc=Get-Content -LiteralPath $PlanPath -Raw|ConvertFrom-Json}catch{throw 'Private plan is not valid JSON.'}
 $results=[ordered]@{}
 $p=$planDoc.PSObject.Properties['staging_ref'];$results.staging_ref=($null -ne $p -and $p.Value -is [string] -and $p.Value -cEQ 'lbklqqqbmeyseeccdqog')
 $p=$planDoc.PSObject.Properties['agent_id'];[guid]$g=[guid]::Empty;$agentOk=$false;if($null -ne $p -and $p.Value -is [string]){$agentOk=[guid]::TryParse($p.Value,[ref]$g) -and $g -eq [guid]'0dae2b29-adaa-48b6-9a96-e9ac646b2a7a'};$results.agent_id=$agentOk
 $p=$planDoc.PSObject.Properties['base_sha'];$results.base_sha=($null -ne $p -and $p.Value -is [string] -and $p.Value -cEQ '07fc0b907d3aa9659ea7541f80acf6c18586e645')
 $p=$planDoc.PSObject.Properties['head_sha'];$results.head_sha=($null -ne $p -and $p.Value -is [string] -and $p.Value -cEQ 'e0d50dd239f8c8c3c39df84187741009f7496d09')
 $p=$planDoc.PSObject.Properties['digest'];$results.digest=($null -ne $p -and $p.Value -is [string] -and $p.Value -cmatch '^[0-9a-f]{64}$')
 [pscustomobject]@{Document=$planDoc;Results=$results}
}
