#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Plan)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
function Read-Hidden([string]$Label){$s=Read-Host -Prompt $Label -AsSecureString;try{if($s.Length-eq 0){throw 'Value cannot be empty.'};$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);try{[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p)}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}}finally{$s.Dispose()}}
function Send([Net.Http.HttpMethod]$Method,[string]$Path,[object]$Payload){$q=[Net.Http.HttpRequestMessage]::new($Method,$Path);try{if($null-ne$Payload){$q.Headers.Add('Content-Profile','reivro_checks_api');$j=ConvertTo-Json $Payload -Depth 12 -Compress;$q.Content=[Net.Http.StringContent]::new($j,[Text.Encoding]::UTF8,'application/json')};$x=$script:client.SendAsync($q).GetAwaiter().GetResult();try{[pscustomobject]@{Status=[int]$x.StatusCode;Body=$x.Content.ReadAsStringAsync().GetAwaiter().GetResult()}}finally{$x.Dispose()}}finally{$q.Dispose()}}
$client=$handler=$key=$email=$password=$session=$null;$stage='plan';$diagnostic='Plan validation failed before credentials were requested.'
try{
 $f=Get-Content -LiteralPath $Plan -Raw|ConvertFrom-Json
 if($f.staging_ref-cne'lbklqqqbmeyseeccdqog'-or [guid]$f.agent_id-eq[guid]::Empty-or [guid]$f.reviewer_id-eq[guid]::Empty-or [guid]$f.submission_id-eq[guid]::Empty-or [long]$f.repository_id-le 0-or [string]$f.digest-cnotmatch'^[0-9a-f]{64}$'){throw 'Invalid private plan.'}
 $stage='identity inventory';$diagnostic='One or more UUIDs are empty, malformed, or duplicated.'
 $subjects=@(
  [pscustomobject]@{Name='agent-a';Id=[guid]$f.agent_id;Visible=$true},
  [pscustomobject]@{Name='reviewer-a';Id=[guid]$f.reviewer_id;Visible=$true},
  [pscustomobject]@{Name='viewer-a';Id=[guid](Read-Host 'Viewer A UUID');Visible=$true},
  [pscustomobject]@{Name='worker-a';Id=[guid](Read-Host 'Worker A UUID');Visible=$true},
  [pscustomobject]@{Name='reviewer-b';Id=[guid](Read-Host 'Reviewer B UUID');Visible=$false},
  [pscustomobject]@{Name='sem-vinculo';Id=[guid](Read-Host 'No-membership UUID');Visible=$false}
 )
 $emptyIds=@($subjects|Where-Object{$_.Id-eq[guid]::Empty})
 $uniqueIds=@($subjects|ForEach-Object{$_.Id}|Sort-Object -Unique)
 if($emptyIds.Count-ne 0-or $uniqueIds.Count-ne 6){throw 'Identity UUID inventory is invalid.'}
 Write-Output 'PASS private plan and six-identity inventory'
 $stage='publishable key';$diagnostic='The staging publishable key format is invalid.'
 $key=(Read-Hidden 'Staging default publishable key').Trim();if($key-cnotmatch'^sb_publishable_[A-Za-z0-9_-]+$'){throw 'Invalid publishable key.'}
 Add-Type -AssemblyName System.Net.Http;[Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol-bor[Net.SecurityProtocolType]::Tls12
 $handler=[Net.Http.HttpClientHandler]::new();$handler.AllowAutoRedirect=$false;$handler.UseCookies=$false;$client=[Net.Http.HttpClient]::new($handler);$client.BaseAddress=[uri]'https://lbklqqqbmeyseeccdqog.supabase.co';$client.Timeout=[TimeSpan]::FromSeconds(15);$client.DefaultRequestHeaders.Add('apikey',$key);$key=$null
 foreach($subject in $subjects){
  $stage="$($subject.Name) login";$diagnostic="Login failed for $($subject.Name); credentials and response body were not logged.";$email=(Read-Hidden "$($subject.Name) staging email").Trim();$password=Read-Hidden "$($subject.Name) staging password"
  $x=Send ([Net.Http.HttpMethod]::Post) '/auth/v1/token?grant_type=password' @{email=$email;password=$password};if($x.Status-lt 200-or$x.Status-ge 300){$diagnostic="Login denied for $($subject.Name) (HTTP $($x.Status)).";throw 'Login denied.'};$session=$x.Body|ConvertFrom-Json
  if($session.user.id-cne$subject.Id.ToString()-or$session.access_token-cnotmatch'^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){2}$'){$diagnostic="Auth identity mismatch for $($subject.Name).";throw 'Unexpected identity.'};$client.DefaultRequestHeaders.Authorization=[Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer',$session.access_token);$email=$password=$session=$null
  $stage="$($subject.Name) read";$diagnostic="Submission visibility check failed for $($subject.Name); no response body was logged.";$x=Send ([Net.Http.HttpMethod]::Post) '/rest/v1/rpc/task_dispatch' @{action='read';request=@{repository_id=[long]$f.repository_id;id=[string]$f.submission_id}}
  if($subject.Visible){if($x.Status-lt 200-or$x.Status-ge 300){$diagnostic="Expected read was denied for $($subject.Name) (HTTP $($x.Status)).";throw 'Read denied.'};$item=$x.Body|ConvertFrom-Json;if($item.id-cne[string]$f.submission_id-or$item.contract_id-cne[string]$f.contract_id-or$item.digest-cne[string]$f.digest-or$item.base_sha-cne[string]$f.base_sha-or$item.head_sha-cne[string]$f.head_sha-or$item.verifier-cne'task-completion-v1'-or$null-ne$item.run_id-or$null-ne$item.result){$diagnostic="Returned submission fields differ for $($subject.Name).";throw 'Unexpected submission view.'}}
  else{if($x.Status-notin 400,403){$diagnostic="Isolation was not enforced for $($subject.Name) (HTTP $($x.Status)).";throw 'Isolation failed.'}}
  Write-Output "PASS $($subject.Name) submission isolation";$client.DefaultRequestHeaders.Authorization=$null;$item=$x=$null
 }
 Write-Output 'SUBMISSION_JWT_MATRIX_READ_ONLY_PASS'
}catch{[Console]::Error.WriteLine("FAIL $stage");[Console]::Error.WriteLine("DETAIL $diagnostic");exit 1}finally{$key=$email=$password=$session=$item=$x=$diagnostic=$null;if($null-ne$client){$client.DefaultRequestHeaders.Authorization=$null;$client.Dispose()}elseif($null-ne$handler){$handler.Dispose()}}
