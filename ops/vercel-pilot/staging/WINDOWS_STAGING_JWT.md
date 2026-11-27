# JWT real no Windows e preparação de fixtures

**Private Alpha bloqueada.** Único destino: staging `lbklqqqbmeyseeccdqog`. Use o checkout da revisão publicada, a partir da raiz do repositório. O PowerShell recebe uma chave publicável e um access token por execução, ambos em prompts ocultos. Use a sessão Supabase Auth normal de cada pessoa de teste e um access token ainda válido. Uma nova autenticação pode atualizar registros de sessão e timestamps do Auth. O script usa a sessão existente por meio do seu token e chama somente `GET /auth/v1/user` e a RPC legada estável na primeira fase.

## Login automático por e-mail e senha

Use esta opção para obter o JWT pelo Auth e testar RLS na mesma execução. A chave publicável `default` do staging foi aceita por Auth, o provedor e-mail está habilitado e a RPC legada negou chamada sem usuário. As cinco identidades têm e-mail confirmado e senha cadastrada. No painel de staging, abra **Authentication → Users** e use cada UUID do inventário privado para conferir o e-mail correspondente. Preserve a correspondência entre papel, UUID e titular.

Prepare o bloco de dados comuns da seção seguinte em cada terminal independente. Em **Settings → API Keys**, selecione a chave publicável moderna `default` (`sb_publishable_…`) do projeto `lbklqqqbmeyseeccdqog`. O script verifica a chave antes de solicitar e-mail e senha, todos por prompt oculto. Cada login pode atualizar o estado da sessão no Supabase Auth. O teste da aplicação usa somente `read_run`.

```powershell
$LoginScript = Join-Path $PWD 'ops/vercel-pilot/staging/Test-ReivroStagingLogin.ps1'
& $LoginScript @Legacy -Subject reviewer-a -UserId ([guid](Read-Host 'UUID reviewer A'))
& $LoginScript @Legacy -Subject reviewer-b -UserId ([guid](Read-Host 'UUID reviewer B'))
& $LoginScript @Legacy -Subject viewer-a -UserId ([guid](Read-Host 'UUID viewer A'))
& $LoginScript @Legacy -Subject worker-a -UserId ([guid](Read-Host 'UUID worker A'))
& $LoginScript @Legacy -Subject sem-vinculo -UserId ([guid](Read-Host 'UUID sujeito sem vinculo'))
```

Execute cada linha no contexto do próprio titular, começando pelos dois reviewers. Continue após os dois controles positivos. O access token é usado em memória para verificar o UUID pelo Auth e fazer as leituras. O script mantém senhas, tokens e corpos de resposta fora da saída. Registre apenas papel, etapa, resultado e status HTTP.

`FAIL … api-key HTTP 401` indica que a API de staging recusou a chave apresentada. Confira a origem da chave no painel. Com `PASS … api-key`, um `FAIL … login` indica falha na etapa de autenticação ou divergência do UUID esperado. Pare diante de um resultado inesperado e preserve o resultado sanitizado.


## Redefinir senha de uma conta existente

Use este fluxo somente com autorização para staging. O script fixa o host `lbklqqqbmeyseeccdqog`, confere o par papel/UUID contra o inventário das cinco contas e chama o Supabase Auth Admin pelo UUID existente. O único campo enviado no update é `password`. Em seguida, confira o papel com o kit de login real. A credencial administrativa serve exclusivamente para a redefinição. Mantenha-a fora do terminal de validação de JWT e dos contextos do agent e worker.

Em um terminal administrativo Windows confiável, use a chave secreta existente do staging, por prompt oculto. Para cada conta, gere uma senha nova no gerenciador de senhas, usando pelo menos 24 caracteres aleatórios seguidos de `-<papel>`, com até 72 bytes no total. Por exemplo, o sufixo literal do primeiro papel é `-reviewer-a`. Salve a senha no cofre privado apropriado antes de executar e repita por prompt oculto. Mantenha os cofres e sessões dos reviewers fora do alcance do agente.

```powershell
$ResetScript = Join-Path $PWD 'ops/vercel-pilot/staging/Reset-ReivroStagingPassword.ps1'
$Subject = Read-Host 'Papel: reviewer-a, reviewer-b, viewer-a, worker-a ou sem-vinculo'
$UserId = [guid](Read-Host 'UUID do papel no inventario privado de staging')
& $ResetScript -Subject $Subject -UserId $UserId
# Apos PASS no preflight e com autorizacao de escrita ja registrada:
& $ResetScript -Subject $Subject -UserId $UserId -Apply
```

Sem `-Apply`, há apenas leitura. Repita para os cinco papéis, um por vez. Se houver falha após o início do reset, teste a senha pretendida com o kit de login antes de considerar nova tentativa. Ao final, compare os mesmos cinco UUIDs e quatro vínculos com a consulta de inventário e execute os controles positivos de reviewer A/B antes dos demais papéis. O hash da tabela `auth.users` da linha de base histórica muda após redefinir senhas. Preserve o recibo anterior e registre a nova linha de base autorizada. Sessões e tokens existentes seguem as regras de expiração e revogação do Supabase Auth. [Supabase Auth Admin](https://supabase.com/docs/reference/javascript/auth-admin-updateuserbyid)

## Cinco identidades existentes

O founder reportou aprovação das cinco identidades em 27/11/2026. Use esta seção para reexecuções. Consulte o [checkpoint e os gates de tarefas](CONTROL_PLANE_OPERATIONAL_GATE.md).

Consulte o inventário privado para os UUIDs e confirme que os runs são fixtures de sintaxe, uma por projeto. Os dois reviewers devem completar seus controles positivos antes de interpretar resultados nulos. Execute o bloco de dados comuns em cada terminal independente. A pessoa sem vínculo usa sua própria sessão. O contexto do reviewer permanece inacessível ao processo do agent.

```powershell
$JwtScript = Join-Path $PWD 'ops/vercel-pilot/staging/Invoke-ReivroStagingJwt.ps1'
$Legacy = @{
    RepoA = [long](Read-Host 'ID numerico do repositorio sintetico A')
    RunA  = [guid](Read-Host 'UUID do run legado A')
    RepoB = [long](Read-Host 'ID numerico do repositorio sintetico B')
    RunB  = [guid](Read-Host 'UUID do run legado B')
}
```

Execute cada linha no terminal do respectivo titular, na ordem indicada. Em cada execução, informe o UUID do sujeito e, nos prompts ocultos do script, a chave publicável e o JWT da sessão correspondente. UUIDs e IDs são referências de fixture, não credenciais.

```powershell
& $JwtScript @Legacy -Subject reviewer-a -UserId ([guid](Read-Host 'UUID reviewer A'))
& $JwtScript @Legacy -Subject reviewer-b -UserId ([guid](Read-Host 'UUID reviewer B'))
& $JwtScript @Legacy -Subject viewer-a -UserId ([guid](Read-Host 'UUID viewer A'))
& $JwtScript @Legacy -Subject worker-a -UserId ([guid](Read-Host 'UUID worker A'))
& $JwtScript @Legacy -Subject sem-vinculo -UserId ([guid](Read-Host 'UUID sujeito sem vinculo'))
```

Para cada linha, espere `PASS auth` e dois resultados `PASS … legacy read …`. Reviewer A e viewer A verão apenas A. Reviewer B verá apenas B. Worker e sujeito sem vínculo receberão JSON nulo em ambos. Qualquer FAIL encerra a execução daquele sujeito. Pare a matriz em falha de controle positivo, identidade divergente ou acesso inesperado. Registre apenas papel, etapa, resultado, status HTTP e revisão do script. O resultado da etapa é JWT/RLS legada, com a matriz de tarefas ainda pendente.

## Preparação do agent e das fixtures

Use primeiro o [gate Windows atualizado](WINDOWS_CONTROL_PLANE_GATE.md) para recuperar o backup e executar o provisionamento de Agent A após autorização. Os passos de planejamento de fixtures abaixo se aplicam à fase seguinte.

A auditoria somente leitura encontrou cinco contas, uma sem membership, dois reviewers, um viewer, um worker e zero submissões. Mantenha todas as contas e associações existentes. Antes da primeira escrita, confirme a conclusão das cinco leituras, a suspensão dos outros writers, a cópia de recuperação recente e o escopo sintético A/B. Registre autorização específica por etapa e por identidade. Os valores de confirmação abaixo exigem essa autorização prévia.

Defina o cliente PostgreSQL local. O certificado do Session Pooler deve ser verificável pela instalação do libpq. `-W` solicita senha sem eco. Use psql 15 ou superior.

```powershell
$Psql = (Get-Command psql.exe -ErrorAction Stop).Source
$Staging = 'host=aws-1-us-west-1.pooler.supabase.com port=5432 user=postgres.lbklqqqbmeyseeccdqog dbname=postgres sslmode=verify-full'
$Ops = Join-Path $PWD 'ops/vercel-pilot/staging'
& $Psql -X -W --dbname=$Staging -v ON_ERROR_STOP=1 -f (Join-Path $Ops 'audit_post_jwt_read_only.sql')
if ($LASTEXITCODE -ne 0) { throw 'Baseline divergiu. Interrompa.' }
```

### Etapa autorizada de Auth e membership

Registre em UTC o início da janela aprovada **antes** da criação. No painel Supabase, selecione o staging pelo ref e crie uma nova conta Auth sintética dedicada, com email confirmado conforme a operação aprovada. Obtenha o UUID pelo painel. Use credenciais exclusivas armazenadas no contexto do titular da conta. Preserve a conta anterior sem vínculo para o controle negativo.

```powershell
$AuthorizedAfter = (Read-Host 'Inicio UTC aprovado antes da criacao (exemplo 2026-11-27T01:00:00Z)')
$AgentId = [guid](Read-Host 'UUID Auth novo do agent A')
$RepositoryId = [long](Read-Host 'ID do repositorio sintetico A aprovado')
$AgentApproval = Read-Host 'Com autorizacao registrada, digite STAGING-AGENT-APPROVED'
& $Psql -X -W --dbname=$Staging -v ON_ERROR_STOP=1 `
    -v "agent_id=$AgentId" -v "repository_id=$RepositoryId" `
    -v "authorized_after=$AuthorizedAfter" -v "approval=$AgentApproval" `
    -f (Join-Path $Ops 'provision_staging_agent.sql')
if ($LASTEXITCODE -ne 0) { throw 'Reconcile a membership antes de repetir.' }
```

Espere `AGENT_MEMBERSHIP_COMMIT_ACKNOWLEDGED`. Confirme por leitura administrativa que o UUID novo tem apenas `agent` no projeto aprovado. O SQL faz uma inserção em membership para uma conta confirmada criada na janela, interrompe se já houver associação e preserva as linhas anteriores.

### Plano somente leitura e criação autorizada da fixture

Forneça revisões distintas de um repositório sintético aprovado, fixadas no Git. O critério da fixture é a existência de `guide.md`. Escolha os commits de acordo com o resultado de verificação pretendido. O SQL calcula o digest com a codificação JSONB do servidor e gera IDs para contrato e submissão. Guarde o plano em uma pasta privada, fora do checkout. Transfira o mesmo plano aos contextos autorizados, preservando a separação de credenciais.

```powershell
$ReviewerId = [guid](Read-Host 'UUID reviewer do projeto da fixture')
$BaseSha = Read-Host 'SHA completo de BASE'
$HeadSha = Read-Host 'SHA completo de HEAD'
$PlanPath = Read-Host 'Caminho absoluto privado do plano JSON'
if (Test-Path -LiteralPath $PlanPath) { throw 'Use um caminho novo para o plano.' }
$PlanJson = & $Psql -X -W -qAt --dbname=$Staging -v ON_ERROR_STOP=1 `
    -v "repository_id=$RepositoryId" -v "reviewer_id=$ReviewerId" -v "agent_id=$AgentId" `
    -v "base_sha=$BaseSha" -v "head_sha=$HeadSha" `
    -f (Join-Path $Ops 'plan_staging_task_fixture.sql')
if ($LASTEXITCODE -ne 0 -or @($PlanJson).Count -ne 1) { throw 'Plano nao gerado.' }
$Fixture = $PlanJson | ConvertFrom-Json
if ($Fixture.staging_ref -cne 'lbklqqqbmeyseeccdqog') { throw 'Destino inesperado.' }
Set-Content -LiteralPath $PlanPath -Value $PlanJson -Encoding UTF8
```

Após autorização da fixture e revisão do plano, execute primeiro a aprovação com o reviewer. Depois de reconciliar o contrato com a consulta abaixo, execute a submissão com o agent em outro contexto. Defina `$JwtScript` e `$PlanPath` em cada terminal conforme os blocos anteriores.

```powershell
# Terminal independente do reviewer.
$Approval = Read-Host 'Com autorizacao registrada, digite STAGING-FIXTURE-APPROVED'
& $JwtScript -FixtureAction approve_contract -Plan $PlanPath -Approval $Approval `
    -UserId ([guid](Read-Host 'UUID reviewer da fixture'))
```

Use a consulta com o mesmo plano antes do submit e novamente depois dele. Após a aprovação, espere `contract_matches=t`, `approval_events=1`, `submission_matches=f` e `submission_events=0`. Após a submissão, espere os dois matches verdadeiros e um evento de cada tipo.

```powershell
$Fixture = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
& $Psql -X -W --dbname=$Staging -v ON_ERROR_STOP=1 `
    -v "repository_id=$($Fixture.repository_id)" -v "reviewer_id=$($Fixture.reviewer_id)" `
    -v "agent_id=$($Fixture.agent_id)" -v "contract_id=$($Fixture.contract_id)" `
    -v "submission_id=$($Fixture.submission_id)" -v "digest=$($Fixture.digest)" `
    -v "head_sha=$($Fixture.head_sha)" -f (Join-Path $Ops 'inspect_staging_task_fixture.sql')
if ($LASTEXITCODE -ne 0) { throw 'Inspecao inconclusiva. Interrompa.' }
```

```powershell
# Terminal do agent dedicado, apos confirmar o contrato persistido.
$Approval = Read-Host 'Com autorizacao registrada, digite STAGING-FIXTURE-APPROVED'
& $JwtScript -FixtureAction submit -Plan $PlanPath -Approval $Approval `
    -UserId ([guid](Read-Host 'UUID agent da fixture'))
```

Em cada execução, confirme a operação digitando `APPLY` e forneça os segredos pelos prompts ocultos. Registre os IDs do plano e reconcilie contrato, submissão e eventos por leitura administrativa antes de avançar. Em timeout ou resultado incerto, pare e inspecione os mesmos IDs. Gere novo plano para cada fixture. A matriz completa exige também uma submissão de outro ator em A e uma submissão de B para controles positivos de escopo. Use o mesmo procedimento com identidades agent dedicadas e separadamente autorizadas em A/B. Reserve fixtures distintas para cenários de fencing, revogação e correção. Confirme o escopo de execução do worker, incluindo repositório, instalação, base e PR, antes de claim. O guia pós-003 define as transições e o aceite. Quaisquer alterações ou limpeza precisam de escopo aprovado e preservação do histórico.
