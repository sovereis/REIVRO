# Gate operacional do Control Plane no Windows

**Private Alpha bloqueada.** Em 27/11/2026 a auditoria somente leitura confirmou a linha de base pós-JWT no staging `lbklqqqbmeyseeccdqog`. Duas amostras sem transações de outros clientes ou transações preparadas. Na primeira amostra, zero runs pendentes, leases e submissões, 12 eventos e sequência 12/true. Confirme a suspensão dos writers com o operador antes do backup e mantenha o freeze até o encerramento da etapa aprovada.

## Backup e ensaio de restauração

Abra uma aba **Windows PowerShell** ou **PowerShell 7** no Windows Terminal. Use os binários PostgreSQL 19 já instalados e a pasta existente `REIVRO-Backups`, em volume criptografado, com ACL restrita e fora do checkout. O script usa o certificado existente em `$HOME\Downloads\prod-ca-2021.crt` com `sslmode=verify-full`. Ele solicita a senha do banco de staging uma vez por prompt oculto e a fornece somente aos processos PostgreSQL que acessam essa origem. A conexão local usa uma senha temporária separada, também por prompt oculto. O arquivo temporário de inicialização fica na pasta criptografada e é apagado logo após `initdb`. O ambiente temporário de cada comando é limpo inclusive em falha. Preserve as ACLs restritas da pasta.

```powershell
$RepoUrl = 'https://github.com/sovereis/REIVRO.git'
$GateBranch = 'docs/reivro-handoff-6-4'
$Checkout = Join-Path ([IO.Path]::GetTempPath()) ('reivro-gate-' + [guid]::NewGuid().ToString('N'))
git clone --single-branch --branch $GateBranch $RepoUrl $Checkout
if ($LASTEXITCODE -ne 0) { throw 'Clone falhou.' }
$Ops = Join-Path $Checkout 'ops/vercel-pilot/staging'
$PgBin = Read-Host 'Pasta bin do PostgreSQL 19 (exemplo C:\Program Files\PostgreSQL\19\bin)'
$PrivateDirectory = Read-Host 'Caminho completo da pasta privada existente REIVRO-Backups'
& (Join-Path $Ops 'Backup-ReivroStaging.ps1') -PgBin $PgBin -PrivateDirectory $PrivateDirectory
```

O ensaio usa um cluster novo em 127.0.0.1:55465. Se a porta estiver em uso, passe `-LocalPort` com outra porta local livre. Só avance após `SELECTIVE_RESTORE_PASS`, com o `receipt.json` e o arquivo preservados na pasta privada. O backup cobre schemas REIVRO, ledger e `auth.users`, excluindo dados de sessões, tokens e demais tabelas Auth. A restauração seletiva confere a linha de base pós-JWT e compara todas as linhas de `auth.users` sem expor detalhes. Ela preserva ACLs aplicáveis e usa papéis locais substitutos para o ensaio. Recuperação integral do Supabase, sessões Auth e login no cluster restaurado estão fora do ensaio. O arquivo contém dados sensíveis de Auth e deve permanecer privado.

O staging continua no PostgreSQL 17. O `pg_dump` 19 lê a origem 17 e o `pg_restore` 19 carrega o arquivo em um cluster novo 19, inicializado em UTF-8. O script confere a versão do servidor em ambos os lados e o diretório de dados do cluster de ensaio antes da primeira escrita local. O dump entre versões usa identificadores entre aspas e o PostgreSQL 19 exige `standard_conforming_strings=on`. Os hashes canônicos, o ledger, a sequência e as verificações de catálogo precisam passar no destino. O sucesso certifica a restauração seletiva 17→19. Uma restauração reversa para 17 exigiria evidência e ferramenta próprias. [pg_dump 19](https://www.postgresql.org/docs/19/app-pgdump.html) · [Notas da versão 19](https://www.postgresql.org/docs/19/release-19.html)

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
$PgBin = Read-Host 'Pasta bin do PostgreSQL 19'
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
