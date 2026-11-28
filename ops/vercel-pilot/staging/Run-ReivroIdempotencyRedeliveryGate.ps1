#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PlanPath,
    [Parameter(Mandatory)][string]$Repository,
    [string]$PgBin = 'C:\Program Files\PostgreSQL\19\bin',
    [string]$CaPath,
    [switch]$Simulation,
    [switch]$InitializationTest
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Read-Hidden([string]$Label) {
    $secure = Read-Host $Label -AsSecureString
    try {
        if ($secure.Length -eq 0) { throw 'Empty value.' }
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    }
    finally { $secure.Dispose() }
}

function Get-Sha256([string]$Value) {
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        ([BitConverter]::ToString($hash.ComputeHash(
            [Text.Encoding]::UTF8.GetBytes($Value)
        ))).Replace('-','').ToLowerInvariant()
    }
    finally { $hash.Dispose() }
}

function Assert-Checks([object]$Result,[string]$Label) {
    $bad = @()
    foreach ($property in $Result.checks.PSObject.Properties) {
        if ([bool]$property.Value) {
            Write-Output "PASS guard=$Label.$($property.Name)"
        }
        else {
            $bad += @($property.Name)
            [Console]::Error.WriteLine("FAIL guard=$Label.$($property.Name)")
        }
    }
    if ($bad.Count -ne 0 -or -not [bool]$Result.all_checks_pass) {
        throw "$Label failed $($bad.Count) guard(s)."
    }
}

function Login([string]$Label,[string]$Email,[string]$Password) {
    $request = [Net.Http.HttpRequestMessage]::new(
        [Net.Http.HttpMethod]::Post,'/auth/v1/token?grant_type=password'
    )
    try {
        $request.Content = [Net.Http.StringContent]::new(
            (ConvertTo-Json @{email=$Email;password=$Password} -Compress),
            [Text.Encoding]::UTF8,'application/json'
        )
        $response = $script:client.SendAsync($request).GetAwaiter().GetResult()
        try {
            if (-not $response.IsSuccessStatusCode) {
                throw "Auth $Label HTTP $([int]$response.StatusCode)"
            }
            $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() |
                ConvertFrom-Json
            [pscustomobject]@{
                Id = [guid]$body.user.id
                Token = [string]$body.access_token
            }
        }
        finally { $response.Dispose() }
    }
    finally { $request.Dispose() }
}

function Send-Raw([string]$Token,[string]$Json,[string]$Action) {
    $request = [Net.Http.HttpRequestMessage]::new(
        [Net.Http.HttpMethod]::Post,'/rest/v1/rpc/task_dispatch'
    )
    try {
        $request.Headers.Add('Content-Profile','reivro_checks_api')
        $request.Headers.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new(
            'Bearer',$Token
        )
        $request.Content = [Net.Http.StringContent]::new(
            $Json,[Text.Encoding]::UTF8,'application/json'
        )
        $response = $script:client.SendAsync($request).GetAwaiter().GetResult()
        try {
            $bodyText = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            $state = $null
            if ($response.IsSuccessStatusCode) {
                try { $state = [string](($bodyText | ConvertFrom-Json).state) }
                catch { $state = $null }
            }
            [pscustomobject]@{
                Action = $Action
                Status = [int]$response.StatusCode
                Success = [bool]$response.IsSuccessStatusCode
                State = $state
                Body = $bodyText
            }
        }
        finally { $response.Dispose() }
    }
    finally { $request.Dispose() }
}

function Send-And-LoseResponse([string]$Token,[string]$Json,[string]$Action) {
    $request = [Net.Http.HttpRequestMessage]::new(
        [Net.Http.HttpMethod]::Post,'/rest/v1/rpc/task_dispatch'
    )
    try {
        $request.Headers.Add('Content-Profile','reivro_checks_api')
        $request.Headers.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new(
            'Bearer',$Token
        )
        $request.Content = [Net.Http.StringContent]::new(
            $Json,[Text.Encoding]::UTF8,'application/json'
        )
        $response = $script:client.SendAsync($request).GetAwaiter().GetResult()
        try {
            # Deliberately discard status and body at the application boundary.
            [pscustomobject]@{
                Action = $Action
                Classification = 'response_lost'
                Status = $null
                Success = $null
                State = $null
            }
        }
        finally { $response.Dispose() }
    }
    finally { $request.Dispose() }
}

function Invoke-PsqlJson([string]$File,[hashtable]$Variables) {
    $oldPassword = [Environment]::GetEnvironmentVariable('PGPASSWORD','Process')
    $oldCertificate = [Environment]::GetEnvironmentVariable('PGSSLROOTCERT','Process')
    try {
        $env:PGPASSWORD = $script:dbPassword
        $env:PGSSLROOTCERT = $script:ca
        $arguments = @(
            '-X','-w','-qAt','-v','ON_ERROR_STOP=1',
            '-d','host=aws-1-us-west-1.pooler.supabase.com port=5432 user=postgres.lbklqqqbmeyseeccdqog dbname=postgres sslmode=verify-full',
            '-v',"repository_id=$($script:planDoc.repository_id)",
            '-v',"first_submission_id=$($script:planDoc.submission_id)",
            '-v','second_submission_id=bd30c2f8-3702-4fe1-a1b4-f6a1f18019bf',
            '-v','third_submission_id=f43a2b86-373a-4432-bd97-3e1fcb1bcfc8',
            '-v','fourth_submission_id=028707c4-9b98-40df-a309-ed789172970e',
            '-v',"new_contract_id=$script:contractId",
            '-v',"new_submission_id=$script:submissionId",
            '-v',"base_sha=$($script:planDoc.base_sha)",
            '-v',"head_sha=$($script:planDoc.head_sha)"
        )
        foreach ($keyName in $Variables.Keys) {
            $arguments += @('-v',"$keyName=$($Variables[$keyName])")
        }
        $arguments += @('-f',$File)
        $output = & $script:psql @arguments
        if ($LASTEXITCODE -ne 0) { throw "psql exited $LASTEXITCODE" }
        $jsonLines = @($output | Where-Object { $_ -match '^\{' })
        if ($jsonLines.Count -ne 1) { throw 'Expected one JSON record.' }
        $jsonLines[0] | ConvertFrom-Json
    }
    finally {
        if ($null -eq $oldPassword) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
        else { $env:PGPASSWORD = $oldPassword }
        if ($null -eq $oldCertificate) { Remove-Item Env:PGSSLROOTCERT -ErrorAction SilentlyContinue }
        else { $env:PGSSLROOTCERT = $oldCertificate }
    }
}

function Get-Sanitized([object]$Response,[string]$Classification) {
    [ordered]@{
        action = [string]$Response.Action
        classification = $Classification
        status = if ($null -eq $Response.Status) { $null } else { [int]$Response.Status }
        success = if ($null -eq $Response.Success) { $null } else { [bool]$Response.Success }
        state = if ($null -eq $Response.State) { $null } else { [string]$Response.State }
    }
}

function Invoke-Simulation {
    & (Join-Path $PSScriptRoot 'Test-ReivroIdempotencyRedeliveryClassification.ps1')
    Write-Output 'IDEMPOTENCY_REDELIVERY_GATE_SIMULATION_PASS'
}

if ($Simulation) { Invoke-Simulation; exit 0 }

$client = $handler = $dbPassword = $reviewer = $agent = $worker = $null
$stage = 'initialization'
$writeStarted = $false
try {
    $shared = Join-Path $PSScriptRoot 'ReivroFinalPlanValidation.ps1'
    $classifier = Join-Path $PSScriptRoot 'ReivroIdempotencyRedeliveryClassification.ps1'
    $preflight = Join-Path $PSScriptRoot 'preflight_staging_idempotency_redelivery_gate.sql'
    $checkpoint = Join-Path $PSScriptRoot 'checkpoint_staging_idempotency_redelivery_gate.sql'
    $postcheck = Join-Path $PSScriptRoot 'postcheck_staging_idempotency_redelivery_gate.sql'
    $reconcile = Join-Path $PSScriptRoot 'reconcile_staging_idempotency_redelivery_gate.sql'
    $certificate = if ([string]::IsNullOrWhiteSpace($CaPath)) {
        Join-Path $HOME 'Downloads\prod-ca-2021.crt'
    } else { $CaPath }

    foreach ($path in @(
        $PlanPath,$shared,$classifier,$preflight,$checkpoint,$postcheck,$reconcile,$certificate
    )) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Missing input: $([IO.Path]::GetFileName($path))"
        }
    }

    . $shared
    . $classifier
    $validation = Get-ReivroFinalPlanValidation $PlanPath
    foreach ($field in @('staging_ref','agent_id','base_sha','head_sha','digest')) {
        if (-not [bool]$validation.Results[$field]) { throw "Plan guard: $field" }
    }
    $planDoc = $validation.Document
    $psql = (Resolve-Path (Join-Path $PgBin 'psql.exe')).Path
    if ((& $psql --version) -notmatch 'PostgreSQL\)\s+19') {
        throw 'PostgreSQL 19 required.'
    }
    $git = @(Get-Command git -CommandType Application)[0].Source
    $ca = (Resolve-Path $certificate).Path
    $origin = (& $git -C $Repository remote get-url origin).Trim()
    if ($origin -cnotmatch '(?i)(?:github\.com[/:])sovereis/REIVRO(?:\.git)?$') {
        throw 'Unexpected Git origin.'
    }
    & $git -C $Repository merge-base --is-ancestor $planDoc.base_sha $planDoc.head_sha
    if ($LASTEXITCODE -ne 0) { throw 'Invalid ancestry.' }
    & $git -C $Repository cat-file -e "$($planDoc.head_sha):guide.md"
    if ($LASTEXITCODE -ne 0) { throw 'guide.md absent.' }

    if ($InitializationTest) {
        Write-Output 'IDEMPOTENCY_REDELIVERY_INITIALIZATION_PASS'
        exit 0
    }

    $contractId = [guid]::NewGuid()
    $submissionId = [guid]::NewGuid()
    $receiptPath = Join-Path (Split-Path $PlanPath -Parent) 'idempotency-redelivery-gate-receipt.json'
    if (Test-Path -LiteralPath $receiptPath) { throw 'Gate receipt already exists.' }

    $publishableKey = (Read-Hidden 'Publishable key').Trim()
    $reviewerEmail = Read-Hidden 'Reviewer email'
    $reviewerPassword = Read-Hidden 'Reviewer password'
    $agentEmail = Read-Hidden 'Agent email'
    $agentPassword = Read-Hidden 'Agent password'
    $workerEmail = Read-Hidden 'Worker email'
    $workerPassword = Read-Hidden 'Worker password'
    $dbPassword = Read-Hidden 'PostgreSQL password'
    $approval = Read-Host 'Type STAGING-IDEMPOTENCY-REDELIVERY-APPROVED'
    if ($approval -cne 'STAGING-IDEMPOTENCY-REDELIVERY-APPROVED') {
        throw 'Not approved.'
    }

    $stage = 'preflight'
    $scope = Invoke-PsqlJson $preflight @{}
    Assert-Checks $scope 'preflight'

    Add-Type -AssemblyName System.Net.Http
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.MaxConnectionsPerServer = 6
    $client = [Net.Http.HttpClient]::new($handler)
    $client.BaseAddress = [uri]'https://lbklqqqbmeyseeccdqog.supabase.co'
    $client.DefaultRequestHeaders.Add('apikey',$publishableKey)
    $reviewer = Login 'ReviewerA' $reviewerEmail $reviewerPassword
    $agent = Login 'AgentA' $agentEmail $agentPassword
    $worker = Login 'WorkerA' $workerEmail $workerPassword
    if ($reviewer.Id -ne [guid]$scope.reviewer_id -or
        $agent.Id -ne [guid]$scope.agent_id -or
        $worker.Id -ne [guid]$scope.worker_id) {
        throw 'Identity mismatch.'
    }
    $publishableKey = $reviewerEmail = $reviewerPassword = $null
    $agentEmail = $agentPassword = $workerEmail = $workerPassword = $null

    $digest = [string]$scope.contract_digest
    $approveRequest = [ordered]@{
        repository_id=[long]$planDoc.repository_id;id=$contractId;version=1
        digest=$digest;document=$scope.contract_document
    }
    $submitRequest = [ordered]@{
        repository_id=[long]$planDoc.repository_id;id=$submissionId
        contract_id=$contractId;version=1;digest=$digest;head_sha=[string]$planDoc.head_sha
    }
    $claimRequest = [ordered]@{
        repository_id=[long]$planDoc.repository_id;installation_id=[long]$scope.installation_id
        repository=[string]$scope.repository;base_ref=[string]$scope.base_ref
        id=$submissionId;delivery=$submissionId;pr=5
        base_sha=[string]$planDoc.base_sha;head_sha=[string]$planDoc.head_sha
        digest=$digest;verifier='task-completion-v1'
    }
    $approveJson = ConvertTo-Json ([ordered]@{action='approve_contract';request=$approveRequest}) -Depth 30 -Compress
    $submitJson = ConvertTo-Json ([ordered]@{action='submit';request=$submitRequest}) -Depth 30 -Compress
    $claimJson = ConvertTo-Json ([ordered]@{action='claim';request=$claimRequest}) -Depth 30 -Compress
    $conflictRequest = [ordered]@{}
    foreach ($property in $submitRequest.GetEnumerator()) { $conflictRequest[$property.Key]=$property.Value }
    $conflictRequest.head_sha = [string]$planDoc.base_sha
    $conflictJson = ConvertTo-Json ([ordered]@{action='submit';request=$conflictRequest}) -Depth 30 -Compress

    [ordered]@{
        state='PLANNED';baseline=50;contract_id=$contractId;submission_id=$submissionId
        payloads=[ordered]@{
            approve=[ordered]@{sha256=(Get-Sha256 $approveJson);json=$approveJson}
            submit=[ordered]@{sha256=(Get-Sha256 $submitJson);json=$submitJson}
            claim=[ordered]@{sha256=(Get-Sha256 $claimJson);json=$claimJson}
            conflicting_submit=[ordered]@{sha256=(Get-Sha256 $conflictJson);json=$conflictJson}
        }
    } | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $receiptPath -Encoding UTF8

    $persistedPlan = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    if ([string]$persistedPlan.payloads.approve.json -cne $approveJson -or
        [string]$persistedPlan.payloads.submit.json -cne $submitJson -or
        [string]$persistedPlan.payloads.claim.json -cne $claimJson -or
        [string]$persistedPlan.payloads.conflicting_submit.json -cne $conflictJson) {
        throw 'Persisted payload bytes changed before send.'
    }

    $observations = @(
        [pscustomobject]@{Kind='absence_of_commit';Pass=[bool]$scope.checks.new_ids_absent}
    )
    $sanitized = @([ordered]@{
        action='preflight';classification='absence_of_commit'
        status=$null;success=$null;state='absent'
    })
    $writeStarted = $true

    $stage = 'approve known response'
    $approve = Send-Raw $reviewer.Token $approveJson 'approve_contract'
    if (-not $approve.Success) { throw "Approve HTTP $($approve.Status)" }
    $sanitized += @(Get-Sanitized $approve 'known_response')
    $saved = Invoke-PsqlJson $checkpoint @{
        new_digest=$digest;expected_events=51;expected_claim_events=0
    }
    Assert-Checks $saved 'checkpoint51'

    $stage = 'submit known response'
    $submit = Send-Raw $agent.Token $submitJson 'submit'
    if (-not $submit.Success) { throw "Submit HTTP $($submit.Status)" }
    $sanitized += @(Get-Sanitized $submit 'known_response')
    $saved = Invoke-PsqlJson $checkpoint @{
        new_digest=$digest;expected_events=52;expected_claim_events=0
    }
    Assert-Checks $saved 'checkpoint52-before-redelivery'

    $stage = 'byte-equivalent submit redelivery'
    $submitReplay = Send-Raw $agent.Token $submitJson 'submit'
    if (-not $submitReplay.Success -or $submitReplay.State -cne 'duplicate') {
        throw 'Exact submit replay was not duplicate.'
    }
    $sanitized += @(Get-Sanitized $submitReplay 'known_response')
    $saved = Invoke-PsqlJson $checkpoint @{
        new_digest=$digest;expected_events=52;expected_claim_events=0
    }
    Assert-Checks $saved 'checkpoint52-after-redelivery'

    $stage = 'conflicting submit replay'
    $conflict = Send-Raw $agent.Token $conflictJson 'submit'
    if ($conflict.Status -lt 400 -or $conflict.Status -ge 500) {
        throw "Conflicting replay HTTP $($conflict.Status)"
    }
    $sanitized += @(Get-Sanitized $conflict 'conflicting_replay')
    $saved = Invoke-PsqlJson $checkpoint @{
        new_digest=$digest;expected_events=52;expected_claim_events=0
    }
    Assert-Checks $saved 'checkpoint52-after-conflict'
    $observations += @([pscustomobject]@{Kind='conflicting_replay';Pass=$true})

    $stage = 'claim response loss'
    $leaseWindow = [Diagnostics.Stopwatch]::StartNew()
    $lost = Send-And-LoseResponse $worker.Token $claimJson 'claim'
    $sanitized += @(Get-Sanitized $lost 'response_lost')

    $stage = 'read-only reconciliation before claim redelivery'
    $saved = Invoke-PsqlJson $checkpoint @{
        new_digest=$digest;expected_events=54;expected_claim_events=1
    }
    Assert-Checks $saved 'checkpoint54-response-lost-committed'
    $observations += @([pscustomobject]@{Kind='response_lost';Pass=$true})
    if ($leaseWindow.Elapsed.TotalSeconds -ge 45) { throw 'Lease safety window exceeded.' }

    $stage = 'byte-equivalent claim redelivery'
    $claimReplay = Send-Raw $worker.Token $claimJson 'claim'
    if (-not $claimReplay.Success -or $claimReplay.State -cne 'busy') {
        throw 'Exact claim replay was not busy.'
    }
    $leaseWindow.Stop()
    $sanitized += @(Get-Sanitized $claimReplay 'known_response')
    $observations += @([pscustomobject]@{Kind='known_response';Pass=$true})

    $saved = Invoke-PsqlJson $checkpoint @{
        new_digest=$digest;expected_events=55;expected_claim_events=2
    }
    Assert-Checks $saved 'checkpoint55-single-durable-effect'
    $final = Invoke-PsqlJson $postcheck @{new_digest=$digest}
    Assert-Checks $final 'postcheck'

    $classification = Get-ReivroIdempotencyRedeliveryClassification $observations
    if (-not $classification.Pass) { throw 'Classification failed.' }

    [ordered]@{
        state='IDEMPOTENCY_REDELIVERY_PASS';baseline=50;journal=[int]$final.journal
        contract_id=$contractId;submission_id=$submissionId;run_id=$final.run_id
        attempt_id=$final.attempt_id;fence=[int]$final.fence
        payload_hashes=[ordered]@{
            approve=(Get-Sha256 $approveJson);submit=(Get-Sha256 $submitJson)
            claim=(Get-Sha256 $claimJson);conflicting_submit=(Get-Sha256 $conflictJson)
        }
        payloads=[ordered]@{
            approve=$approveJson;submit=$submitJson;claim=$claimJson
            conflicting_submit=$conflictJson
        }
        observations=$sanitized
    } | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $receiptPath -Encoding UTF8

    Write-Output 'IDEMPOTENCY_REDELIVERY_SINGLE_EFFECT_PASS'
    Write-Output 'FINAL_JOURNAL=55'
    Write-Output "RECEIPT=$receiptPath"
}
catch {
    [Console]::Error.WriteLine(
        "FAIL stage=$stage type=$($_.Exception.GetType().Name) message=$($_.Exception.Message)"
    )
    if ($writeStarted) {
        try {
            $state = Invoke-PsqlJson $reconcile @{}
            [Console]::Error.WriteLine(
                'RECONCILIATION ' + (ConvertTo-Json $state -Depth 20 -Compress)
            )
        }
        catch { [Console]::Error.WriteLine('READ-ONLY RECONCILIATION FAILED.') }
    }
    exit 1
}
finally {
    $publishableKey = $dbPassword = $approval = $null
    if ($null -ne $reviewer) { $reviewer.Token = $null }
    if ($null -ne $agent) { $agent.Token = $null }
    if ($null -ne $worker) { $worker.Token = $null }
    Remove-Item Env:PGPASSWORD,Env:PGSSLROOTCERT -ErrorAction SilentlyContinue
    if ($null -ne $client) { $client.Dispose() }
    elseif ($null -ne $handler) { $handler.Dispose() }
}
