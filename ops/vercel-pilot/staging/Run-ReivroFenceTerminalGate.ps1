#requires -Version 5.1
[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$PlanPath,
 [Parameter(Mandatory)][string]$ReceiptPath,
 [Parameter(Mandatory)][string]$Repository,
 [string]$PgBin='C:\Program Files\PostgreSQL\19\bin',
 [switch]$Simulation
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'

function Assert-Checks([object]$Record,[string]$Label){
 if($null -eq $Record -or $null -eq $Record.checks){throw "$Label returned no named checks."}
 $failed=New-Object System.Collections.Generic.List[string]
 foreach($p in $Record.checks.PSObject.Properties){
  if([bool]$p.Value){Write-Output "PASS guard=$Label.$($p.Name)"}else{[void]$failed.Add([string]$p.Name);[Console]::Error.WriteLine("FAIL guard=$Label.$($p.Name)")}
 }
 if($failed.Count-ne 0 -or -not [bool]$Record.all_checks_pass){throw "$Label failed $($failed.Count) named guard(s)."}
}
function Read-Hidden([string]$Label){$s=Read-Host $Label -AsSecureString;try{if($s.Length-eq 0){throw 'Empty value.'};$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);try{[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p)}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}}finally{$s.Dispose()}}
function Login([string]$Email,[string]$Password){$q=[Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Post,'/auth/v1/token?grant_type=password');try{$q.Content=[Net.Http.StringContent]::new((ConvertTo-Json @{email=$Email;password=$Password}-Compress),[Text.Encoding]::UTF8,'application/json');$x=$script:client.SendAsync($q).GetAwaiter().GetResult();try{if(-not$x.IsSuccessStatusCode){throw "Login HTTP $([int]$x.StatusCode)"};$b=$x.Content.ReadAsStringAsync().GetAwaiter().GetResult()|ConvertFrom-Json;[pscustomobject]@{Id=[guid]$b.user.id;Token=[string]$b.access_token}}finally{$x.Dispose()}}finally{$q.Dispose()}}
function SendAs([string]$Token,[string]$Action,[object]$Request){$q=[Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Post,'/rest/v1/rpc/task_dispatch');try{$q.Headers.Add('Content-Profile','reivro_checks_api');$q.Headers.Authorization=[Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer',$Token);$q.Content=[Net.Http.StringContent]::new((ConvertTo-Json @{action=$Action;request=$Request}-Depth 30 -Compress),[Text.Encoding]::UTF8,'application/json');$x=$script:client.SendAsync($q).GetAwaiter().GetResult();try{[pscustomobject]@{Status=[int]$x.StatusCode;Body=$x.Content.ReadAsStringAsync().GetAwaiter().GetResult()}}finally{$x.Dispose()}}finally{$q.Dispose()}}
function PsqlJson([string]$File,[hashtable]$Extra){$op=[Environment]::GetEnvironmentVariable('PGPASSWORD','Process');$oc=[Environment]::GetEnvironmentVariable('PGSSLROOTCERT','Process');try{$env:PGPASSWORD=$script:dbPassword;$env:PGSSLROOTCERT=$script:ca;$a=@('-X','-w','-qAt','-v','ON_ERROR_STOP=1','-d','host=aws-1-us-west-1.pooler.supabase.com port=5432 user=postgres.lbklqqqbmeyseeccdqog dbname=postgres sslmode=verify-full','-v',"repository_id=$($script:planDoc.repository_id)",'-v',"original_submission_id=$($script:planDoc.submission_id)",'-v',"contract_id=$($script:receiptDoc.contract_id)",'-v',"submission_id=$($script:receiptDoc.submission_id)",'-v',"run_id=$($script:receiptDoc.run_id)",'-v',"digest=$($script:planDoc.digest)",'-v',"base_sha=$($script:planDoc.base_sha)",'-v',"head_sha=$($script:planDoc.head_sha)");foreach($k in $Extra.Keys){$a+=@('-v',"$k=$($Extra[$k])")};$a+=@('-f',$File);$o=&$script:psql @a;if($LASTEXITCODE-ne 0){throw "psql exited $LASTEXITCODE"};$z=@($o|Where-Object{$_-match'^\{'});if($z.Count-ne 1){throw 'Expected one reconciliation record.'};$z[0]|ConvertFrom-Json}finally{if($null-eq$op){Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue}else{$env:PGPASSWORD=$op};if($null-eq$oc){Remove-Item Env:PGSSLROOTCERT -ErrorAction SilentlyContinue}else{$env:PGSSLROOTCERT=$oc}}}
function Checkpoint([string]$State,[int]$Fence,[int]$Events,[int]$Claims,[int]$Failures){$r=PsqlJson $script:checkpoint @{expected_state=$State;expected_fence=$Fence;expected_events=$Events;expected_claims=$Claims;expected_failures=$Failures;worker_id=$script:worker.Id};Assert-Checks $r "checkpoint-$Events"}
function Invoke-Claim([int]$Fence){$x=SendAs $script:worker.Token 'claim' $script:claimRequest;if($x.Status-lt200-or$x.Status-ge300){throw "Claim fence $Fence HTTP $($x.Status)"};$v=$x.Body|ConvertFrom-Json;if($v.state-cne'running'-or[int]$v.fence-ne$Fence-or[guid]$v.run_id-ne[guid]$script:receiptDoc.run_id){throw "Unexpected claim fence $Fence receipt."};$v}
function Invoke-Fail([object]$Claim,[string]$Expected){$r=@{repository_id=[long]$script:planDoc.repository_id;installation_id=[long]$script:scope.installation_id;id=[string]$script:receiptDoc.submission_id;run_id=[string]$script:receiptDoc.run_id;attempt_id=[string]$Claim.attempt_id;fence=[int]$Claim.fence};$x=SendAs $script:worker.Token 'fail' $r;if($x.Status-lt200-or$x.Status-ge300){throw "Fail fence $($Claim.fence) HTTP $($x.Status)"};$v=$x.Body|ConvertFrom-Json;if($v.state-cne$Expected){throw "Fail fence $($Claim.fence) did not become $Expected."};$v}
function Invoke-Simulation{
 $state='retryable';$fence=1;$journal=28;$claims=1;$failures=1;$first='completed/3/VERIFIED/INCONCLUSIVE'
 foreach($step in @(@{op='claim';f=2;j=30;s='running'},@{op='fail';f=2;j=32;s='retryable'},@{op='claim';f=3;j=34;s='running'},@{op='fail';f=3;j=36;s='terminal'})){
  if($step.op-eq'claim'){if($state-cne'retryable'-or$fence-ne($step.f-1)){throw 'Simulation claim precondition failed.'};$fence=$step.f;$claims++;$state='running'}else{if($state-cne'running'-or$fence-ne$step.f){throw 'Simulation fail precondition failed.'};$failures++;$state=$step.s}
  $journal=$step.j;if($state-cne$step.s){throw 'Simulation transition mismatch.'};Write-Output "PASS simulation $($step.op) fence=$fence state=$state journal=$journal"
 }
 if($journal-ne36-or$state-cne'terminal'-or$fence-ne3-or$claims-ne3-or$failures-ne3-or$first-cne'completed/3/VERIFIED/INCONCLUSIVE'){throw 'Simulation final invariant failed.'}
 Write-Output 'FENCE_TERMINAL_GATE_SIMULATION_PASS'
}
if($Simulation){Invoke-Simulation;exit 0}

$client=$handler=$key=$dbPassword=$workerEmail=$workerPassword=$approval=$null;$worker=$null;$stage='initialization';$writeStarted=$false
try{
 $shared=Join-Path $PSScriptRoot 'ReivroFinalPlanValidation.ps1';$preflight=Join-Path $PSScriptRoot 'preflight_staging_fence_terminal_gate.sql';$checkpoint=Join-Path $PSScriptRoot 'checkpoint_staging_fence_terminal_gate.sql';$reconcile=Join-Path $PSScriptRoot 'reconcile_staging_fence_terminal_gate.sql';$cert=Join-Path $HOME 'Downloads\prod-ca-2021.crt'
 foreach($p in @($PlanPath,$ReceiptPath,$shared,$preflight,$checkpoint,$reconcile,$cert)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw "Missing required input: $([IO.Path]::GetFileName($p))"}}
 . $shared;$validation=Get-ReivroFinalPlanValidation $PlanPath;foreach($f in @('staging_ref','agent_id','base_sha','head_sha','digest')){if(-not[bool]$validation.Results[$f]){throw "Plan guard failed: $f"};Write-Output "PASS guard=plan.$f"};$planDoc=$validation.Document
 try{$receiptDoc=Get-Content -LiteralPath $ReceiptPath -Raw|ConvertFrom-Json}catch{throw 'Renew/Fail receipt is not valid JSON.'}
 foreach($f in @('contract_id','submission_id','run_id')){$p=$receiptDoc.PSObject.Properties[$f];[guid]$g=[guid]::Empty;if($null-eq$p-or-not($p.Value-is[string])-or-not[guid]::TryParse($p.Value,[ref]$g)){throw "Receipt guard failed: $f"};Write-Output "PASS guard=receipt.$f"}
 if($receiptDoc.state-cne'RENEW_FAIL_RETRYABLE_PASS'-or[int]$receiptDoc.fence-ne1-or[int]$receiptDoc.journal-ne28){throw 'Receipt baseline guard failed.'};Write-Output 'PASS guard=receipt.baseline'
 $psql=(Resolve-Path (Join-Path $PgBin 'psql.exe')).Path;if((&$psql --version)-notmatch'PostgreSQL\)\s+19(?:\.\d+)?(?:\s|$)'){throw 'PostgreSQL 19 required.'};$git=(Get-Command git -CommandType Application).Source;$ca=(Resolve-Path $cert).Path
 $origin=(&$git -C $Repository remote get-url origin).Trim();if($origin-cnotmatch'(?i)(?:github\.com[/:])sovereis/REIVRO(?:\.git)?$'){throw 'Unexpected Git origin.'};&$git -C $Repository merge-base --is-ancestor $planDoc.base_sha $planDoc.head_sha;if($LASTEXITCODE-ne0){throw 'Invalid Git ancestry.'};&$git -C $Repository cat-file -e "$($planDoc.head_sha):guide.md";if($LASTEXITCODE-ne0){throw 'guide.md absent.'}
 # Every credential and confirmation is collected before the first 60-second lease begins.
 $key=(Read-Hidden 'Staging default publishable key').Trim();$workerEmail=(Read-Hidden 'Worker A staging email').Trim();$workerPassword=Read-Hidden 'Worker A staging password';$dbPassword=Read-Hidden 'Staging PostgreSQL password';$approval=Read-Host 'Type STAGING-FENCE-TERMINAL-GATE-APPROVED';if($approval-cne'STAGING-FENCE-TERMINAL-GATE-APPROVED'){throw 'Gate not locally confirmed.'};if($key-cnotmatch'^sb_publishable_[A-Za-z0-9_-]+$'){throw 'Invalid publishable key.'}
 $stage='preflight';$scope=PsqlJson $preflight @{};Assert-Checks $scope 'preflight'
 Add-Type -AssemblyName System.Net.Http;$handler=[Net.Http.HttpClientHandler]::new();$handler.AllowAutoRedirect=$false;$handler.UseCookies=$false;$client=[Net.Http.HttpClient]::new($handler);$client.BaseAddress=[uri]'https://lbklqqqbmeyseeccdqog.supabase.co';$client.Timeout=[TimeSpan]::FromSeconds(12);$client.DefaultRequestHeaders.Add('apikey',$key);$key=$null
 $stage='worker login';$worker=Login $workerEmail $workerPassword;if($worker.Id-ne[guid]$scope.worker_id){throw 'Unexpected Worker A identity.'};$workerEmail=$workerPassword=$null
 $claimRequest=@{repository_id=[long]$planDoc.repository_id;installation_id=[long]$scope.installation_id;repository=[string]$scope.repository;base_ref=[string]$scope.base_ref;id=[string]$receiptDoc.submission_id;delivery=[string]$scope.delivery;pr=[int]$scope.pr;base_sha=[string]$scope.base_sha;head_sha=[string]$scope.head_sha;digest=[string]$scope.digest;verifier='task-completion-v1'}
 # No prompts occur after this point.
 $writeStarted=$true;$stage='claim fence 2';$claim2=Invoke-Claim 2;Checkpoint 'running' 2 30 2 1
 $stage='fail fence 2 retryable';[void](Invoke-Fail $claim2 'retryable');Checkpoint 'retryable' 2 32 2 2
 $stage='claim fence 3';$claim3=Invoke-Claim 3;Checkpoint 'running' 3 34 3 2
 $stage='fail fence 3 terminal';[void](Invoke-Fail $claim3 'terminal');Checkpoint 'terminal' 3 36 3 3
 Write-Output 'PASS fence 2 retryable and fence 3 exhausted';Write-Output 'PASS terminal ERROR journal 36 and first run preserved';Write-Output 'FENCE_EXHAUSTION_TERMINAL_PASS'
}catch{[Console]::Error.WriteLine("FAIL stage=$stage type=$($_.Exception.GetType().Name) message=$($_.Exception.Message)");if($writeStarted){[Console]::Error.WriteLine('DO NOT RETRY. READ-ONLY RECONCILIATION FOLLOWS.');try{$r=PsqlJson $reconcile @{};[Console]::Error.WriteLine(('RECONCILIATION '+(ConvertTo-Json $r -Depth 20 -Compress)))}catch{[Console]::Error.WriteLine("READ-ONLY RECONCILIATION FAILED type=$($_.Exception.GetType().Name); stop and preserve evidence.")}};exit 1}finally{$key=$dbPassword=$workerEmail=$workerPassword=$approval=$null;if($null-ne$worker){$worker.Token=$null};Remove-Item Env:PGPASSWORD,Env:PGSSLROOTCERT -ErrorAction SilentlyContinue;if($null-ne$client){$client.Dispose()}elseif($null-ne$handler){$handler.Dispose()}}
