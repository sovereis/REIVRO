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

O founder reportou `SELECTIVE_RESTORE_PASS` para
`C:\Users\LENOVO\REIVRO-Backups\reivro-staging-20261127-183321-65f72840`,
com auditorias Cloud e Auth aprovadas antes e depois do backup e na restauração
PostgreSQL 19. O conteúdo privado do recibo não foi transferido. O comando abaixo
recalcula localmente o SHA256 e confere tamanho, TOC e versões 17→19 contra o
archive antes de iniciar o preflight de staging.

**Pare antes de executá-lo até confirmar o freeze e autorizar estas duas escritas:**
uma conta Auth sintética confirmada para Agent A e uma membership `agent` no
projeto A. O script solicita a senha PostgreSQL e a secret API key do staging por
prompts ocultos. Solicita também e-mail e senha exclusivos do Agent, identifica
o projeto A pelo inventário e exige a frase
`AGENT-A-AUTH-AND-MEMBERSHIP-APPROVED` imediatamente antes das escritas.

Cole todo o bloco em uma aba nova do Windows PowerShell ou PowerShell 7 no Windows
Terminal. Ele não depende de variáveis de sessões anteriores.

```powershell
& {
    $Checkout = Join-Path ([IO.Path]::GetTempPath()) ('reivro-agent-a-' + [guid]::NewGuid().ToString('N'))
    git clone --no-checkout https://github.com/sovereis/REIVRO.git $Checkout
    if ($LASTEXITCODE -ne 0) { throw 'Clone falhou.' }

    git -C $Checkout checkout --detach 097424290189371ed42da75b105c04af44d56bcc
    if ($LASTEXITCODE -ne 0) { throw 'Kit aprovado indisponivel.' }

    $Ops = Join-Path $Checkout 'ops/vercel-pilot/staging'
    & (Join-Path $Ops 'Reconcile-ReivroReceipt.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Receipt privado nao reconciliado.' }

    & (Join-Path $Ops 'Provision-ReivroAgentA.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Provisionamento incompleto. Leia o recibo privado antes de qualquer nova acao.' }
}
```

A saída esperada termina em `AGENT_A_PROVISIONED` e aponta para
`agent-a-provisioning-receipt.json` dentro da pasta privada do backup. Em falha
após a criação Auth, preserve o UUID e o recibo `AUTH_CREATED_MEMBERSHIP_PENDING`.
Não repita a criação. Reconcilie o mesmo usuário antes de qualquer ação.

O gate preserva os cinco UUIDs e quatro memberships anteriores. Ele falha se
existirem contratos, submissões, policies, corrections, leases, runs pendentes
ou mudança no journal. Não cria contratos nem submissões. Depois do PASS, faça
login normal do Agent em seu contexto isolado e aguarde nova autorização para
fixtures. [Matriz e ordem operacional](CONTROL_PLANE_OPERATIONAL_GATE.md)
