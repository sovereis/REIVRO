# Gate operacional do Control Plane no Windows

**Private Alpha bloqueada.** Em 27/11/2026 a auditoria somente leitura confirmou a linha de base pós-JWT no staging `lbklqqqbmeyseeccdqog`. Duas amostras sem transações de outros clientes ou transações preparadas. Na primeira amostra, zero runs pendentes, leases e submissões, 12 eventos e sequência 12/true. Confirme a suspensão dos writers com o operador antes do backup e mantenha o freeze até o encerramento da etapa aprovada.

## Backup e ensaio de restauração

Abra uma aba **Windows PowerShell** ou **PowerShell 7** no Windows Terminal. Use cliente e servidor PostgreSQL 17 instalados localmente e uma pasta privada em volume criptografado, com ACL restrita e fora do checkout. O libpq precisa confiar na CA do Session Pooler para SSL verify-full. O script pede as senhas pelo prompt do PostgreSQL. As primeiras conexões usam a senha do staging. Após o aviso de inicialização, os prompts usam a senha temporária do PostgreSQL local.

```powershell
$RepoUrl = 'https://github.com/sovereis/REIVRO.git'
$GateBranch = 'docs/reivro-handoff-6-4'
$Checkout = Join-Path ([IO.Path]::GetTempPath()) ('reivro-gate-' + [guid]::NewGuid().ToString('N'))
git clone --single-branch --branch $GateBranch $RepoUrl $Checkout
if ($LASTEXITCODE -ne 0) { throw 'Clone falhou.' }
$Ops = Join-Path $Checkout 'ops/vercel-pilot/staging'
$PgBin = Read-Host 'Pasta bin do PostgreSQL 17 (exemplo C:\Program Files\PostgreSQL\17\bin)'
$PrivateDirectory = Read-Host 'Pasta privada e criptografada existente para o backup'
& (Join-Path $Ops 'Backup-ReivroStaging.ps1') -PgBin $PgBin -PrivateDirectory $PrivateDirectory
```

O ensaio usa um cluster novo em 127.0.0.1:55464. Se a porta estiver em uso, passe `-LocalPort` com outra porta local livre. Só avance após `SELECTIVE_RESTORE_PASS`, com o `receipt.json` e o arquivo preservados na pasta privada. O backup cobre schemas REIVRO, ledger e `auth.users`, excluindo dados de sessões, tokens e demais tabelas Auth. A restauração seletiva confere a linha de base pós-JWT e compara todas as linhas de `auth.users` sem expor detalhes. Ela preserva ACLs aplicáveis e usa papéis locais substitutos para o ensaio. Recuperação integral do Supabase, sessões Auth e login no cluster restaurado estão fora do ensaio. O arquivo contém dados sensíveis de Auth e deve permanecer privado.

## Agent A após autorização específica

**Pare aqui até receber autorização explícita para as duas escritas de staging:** criar uma conta Auth sintética nova para Agent A e inserir uma membership `agent` no projeto A. O escopo de escrita termina nessa membership. Contratos, submissões e demais fixtures aguardam autorização própria.

Com o recibo aprovado e o freeze reconfirmado, consulte os UUIDs existentes e o repositório A pelo inventário privado. Antes de criar a conta, registre o início UTC da janela autorizada. No Dashboard do projeto `lbklqqqbmeyseeccdqog`, crie uma conta Auth dedicada e confirmada, com credencial exclusiva no cofre do Agent. Registre o UUID sem compartilhá-lo em chat. Use a janela real registrada antes da criação.

```powershell
$RepoUrl = 'https://github.com/sovereis/REIVRO.git'
$GateBranch = 'docs/reivro-handoff-6-4'
$Checkout = Join-Path ([IO.Path]::GetTempPath()) ('reivro-agent-' + [guid]::NewGuid().ToString('N'))
git clone --single-branch --branch $GateBranch $RepoUrl $Checkout
if ($LASTEXITCODE -ne 0) { throw 'Clone falhou.' }
$Ops = Join-Path $Checkout 'ops/vercel-pilot/staging'
$PgBin = Read-Host 'Pasta bin do PostgreSQL 17'
$Psql = Join-Path $PgBin 'psql.exe'
$Staging = 'host=aws-1-us-west-1.pooler.supabase.com port=5432 user=postgres.lbklqqqbmeyseeccdqog dbname=postgres sslmode=verify-full'
$AgentId = [guid](Read-Host 'UUID da nova conta Auth do Agent A')
$RepositoryId = [long](Read-Host 'ID numerico aprovado do repositorio sintetico A')
$AuthorizedAfter = Read-Host 'Inicio UTC da janela, registrado antes da criacao da conta'
$Approval = Read-Host 'Com autorizacao registrada, digite STAGING-AGENT-APPROVED'
if ($Approval -cne 'STAGING-AGENT-APPROVED') { throw 'Escrita cancelada.' }

& $Psql -X -W -d $Staging -v ON_ERROR_STOP=1 `
    -v "agent_id=$AgentId" -v "repository_id=$RepositoryId" `
    -v "authorized_after=$AuthorizedAfter" -v "approval=$Approval" `
    -f (Join-Path $Ops 'provision_staging_agent.sql')
if ($LASTEXITCODE -ne 0) { throw 'Resultado incerto ou divergente. Inspecione antes de repetir.' }

& $Psql -X -W -d $Staging -v ON_ERROR_STOP=1 `
    -v "agent_id=$AgentId" -v "repository_id=$RepositoryId" `
    -f (Join-Path $Ops 'inspect_staging_agent.sql')
if ($LASTEXITCODE -ne 0) { throw 'Pos-check pendente. Interrompa.' }
```

Espere `AGENT_MEMBERSHIP_COMMIT_ACKNOWLEDGED` e `AGENT_A_INVENTORY_PASS`. A criação no Auth e a inclusão no PostgreSQL são etapas separadas. Em falha parcial, preserve o UUID da conta nova e reconcilie seu estado antes de qualquer nova ação. Após o pós-check, aguarde escopo autorizado para a fixture. [Matriz e ordem operacional](CONTROL_PLANE_OPERATIONAL_GATE.md)
