# Staging pós-003: auditoria independente e preparação JWT

Checkpoint: 26/11/2026 (America/Sao_Paulo). Base desta branch:
`d64249066dead9662fdbd96dbfb8e72fb9b0eec4`. Código SQL aprovado:
`e280fa4f096ff7aa4d6d190d678982d3ea26fe49`. Nenhuma migration foi reaplicada.

## Resultado independente

Consultas pelo conector SQL administrativo, exclusivamente no projeto
`lbklqqqbmeyseeccdqog`, usaram BEGIN READ ONLY, timeouts e COMMIT. Esse acesso não
representa autenticação de agent/reviewer/worker pelo Auth/PostgREST.

O pós-check anterior foi executado independentemente e retornou
`POSTCHECK003_INDEPENDENT_PASS`. O script publicável
`ops/vercel-pilot/staging/audit-003-readonly.sql`, com checagem adicional do ledger
001/002/003, também foi executado em leitura e retornou `AUDIT_003_READONLY_PASS`.

| Critério | Evidência independente |
| --- | --- |
| tasks / leases | Ambas presentes; quatro tabelas task e execution_leases vazias |
| Ledger | Exatamente 001, 002 e 003; nomes e source hashes 002/003 conferem |
| Dispatcher V3 | MD5 5789d2beb5926fbfe2006973dd66d337 |
| Alias V1 privado | MD5 7b65dd994ca180ed06312d3c0a7820fe preservado |
| execution_dispatch | MD5 e76a6ec5da5b3a2d9122cbd20e52f9d8 |
| task_dispatch privado / API | MD5 3c56d88c40c4a66f564fa4d51fca0930 / 3458700a52910337fea6aca7f57d8f03 |
| API dispatch / read_run | Hashes legados preservados |
| Segurança das funções | Owner postgres; helpers SECURITY DEFINER, API SECURITY INVOKER; search_path vazio |
| Grants | authenticated executa task_dispatch; anon/service_role não; nenhum cliente executa execution_dispatch/dispatch_v1 |
| RLS | Ativo nas 11 tabelas REIVRO; task/leases sem grants diretos de cliente |
| Constraints | Zero não validadas |
| Índices | one_active_guard, syntax_delivery, syntax_revision, task_execution e one_task_root_submission válidos e únicos, com os predicados esperados |
| Histórico | Sete digests de dados preservados pelo guard; runs desconsidera a nova coluna NULL task_submission_id |
| Contagens | 2 projetos, 4 memberships, 5 Auth users, 5 runs/0 pendentes, 4 findings, 1 protection, 12 eventos |
| Sequência | 12/true |

As cinco identidades Auth estão confirmadas e não anônimas. Há dois reviewers,
um viewer e um worker nos memberships, **nenhum agent** e um usuário sem membership.
Não foram lidos senhas/tokens, criados usuários ou alteradas associações.

### Diferença da 001: preservar hardening, não reaplicar

O arquivo Git `001_firewall.sql` tem SHA256
`3ff87132971c85fae078b73bcc0bbbda1822ab88cbcf27552060ddcc45ee84d3`.
O texto histórico da entrada 001 tem SHA256
`8f40e7609c9116fe63a422851730ebf0685d4e64cdfcde9b69c24577612591f1`.
A comparação demonstrou que a única diferença textual é este endurecimento da
política own_membership:

```sql
-- Git histórico:
using (user_id = (select auth.uid()));

-- Ledger e política hospedada:
using (user_id = (select auth.uid())
       and (select auth.jwt()->>'is_anonymous') is distinct from 'true');
```

Substituir somente a expressão no texto do Git reproduz os 17462 bytes e o SHA256
exato do ledger. A política em pg_policies contém a restrição. Portanto, 002/003
conferem byte a byte com suas fontes, enquanto 001 possui essa diferença documentada
mais restritiva. Não reescrever ledger, aplicar o arquivo antigo ou enfraquecer RLS
para obter igualdade. Uma eventual consolidação futura desse hardening no código
precisa de revisão própria; nenhuma migration foi modificada nesta entrega.

## Scripts publicados

- `audit-003-readonly.sql`: auditoria administrativa pós-003; só leitura, sem DDL/DML.
- `fixture-inventory-readonly.sql`: inventário mínimo privado para o operador montar
  manifests; retorna UUIDs, roles, escopo e revisões, nunca emails/senhas/JWTs.
  Não publicar sua saída. Esse arquivo foi revisado, mas não executado nesta entrega.
- `jwt_preflight.py`: Auth/leituras por uma identidade de cada vez; sem login,
  refresh, criação de fixture, decisão humana ou chamada de ação mutável.
- `Invoke-JwtPreflight.ps1`: launcher Windows PowerShell com interrupção em exit
  não zero. O launcher foi analisado com PowerShell 7/Linux; Windows 5.1 ainda
  precisa de validação no computador do founder.

Os scripts 001/002/003 e o kit operacional original permanecem inalterados.
Depois de 003, não executar Audit002, Ledger002, Preflight003 ou Apply003 do kit
anterior: essas etapas já foram concluídas. O novo audit exige a baseline anterior
às fixtures; deve falhar quando dados sintéticos novos forem autorizados/criados.
Não atualizar seus digests apenas para fazer o teste passar.

## Executar somente a auditoria SQL, se necessário no Windows

A partir da raiz do worktree correto, com a CA já validada:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $Nomes = @('PGSSLMODE','PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGOPTIONS','PGPASSWORD','PGCONNECT_TIMEOUT')
    $Anterior = @{}
    foreach ($Nome in $Nomes) { $Anterior[$Nome] = [Environment]::GetEnvironmentVariable($Nome,'Process') }
    try {
        Remove-Item Env:PGSERVICE,Env:PGSERVICEFILE,Env:PGHOSTADDR,Env:PGOPTIONS,Env:PGPASSWORD -ErrorAction SilentlyContinue
        $env:PGSSLMODE = 'verify-full'
        $env:PGCONNECT_TIMEOUT = '10'
        & 'C:\Program Files\PostgreSQL\19\bin\psql.exe' `
            -X -W -v ON_ERROR_STOP=1 `
            -h aws-1-us-west-1.pooler.supabase.com -p 5432 `
            -U postgres.lbklqqqbmeyseeccdqog -d postgres `
            -f '.\ops\vercel-pilot\staging\audit-003-readonly.sql'
        if ($LASTEXITCODE -ne 0) { throw 'Auditoria bloqueada; preservar evidencia e investigar.' }
    } finally {
        foreach ($Nome in $Nomes) { [Environment]::SetEnvironmentVariable($Nome,$Anterior[$Nome],'Process') }
    }
}
```

Conferir que o cliente não herda PGSERVICE/PGHOSTADDR/PGOPTIONS inadequados. O kit
original já trata essas variáveis. Não usar connection strings com senha, `-c`,
SQL colado no shell ou outro projeto. A API SQL desta auditoria usou o ref fixo
staging; os comandos acima são preparação para o operador e não foram executados
contra o banco por este shell.

## Preparação real JWT: isolada por papel

Disponibilidade neste processo: chave publicável e JWTs dos papéis **ausentes**.
Nenhuma requisição real com JWT de usuário foi executada nesta entrega. Não pedir
credenciais pelo chat. Não usar Secret API Key via proxy administrativo nem
substituir JWT real por SET ROLE/claims sintéticas.

Em cada contexto autorizado e isolado, configurar apenas:

| Variável | Uso |
| --- | --- |
| REIVRO_STAGING_REF | Exatamente lbklqqqbmeyseeccdqog |
| REIVRO_PUBLISHABLE_KEY | Chave sb_publishable_ do staging, conferida pelo operador |
| REIVRO_VALIDATION_JWT | Um access token de login normal do sujeito dessa execução |

Usar token já emitido pelo login normal da identidade sintética, de curta duração,
carregado pelo canal seguro do operador apenas no processo correto. O preflight
não cria ou renova sessões. Caso seja necessário emitir um novo token, o operador
faz login em seu cliente/contexto autorizado; nunca retorna o token no relatório.
Não carregar todos os JWTs num mesmo processo nem entregar o token de reviewer ao
agente. O runner bloqueia outras variáveis REIVRO_*_JWT, chave administrativa
conhecida e PGPASSWORD no ambiente. Isso é higiene de execução, **não prova** que
credenciais são inacessíveis por outros meios do SO. Credenciais humanas continuam
fora do ambiente controlado pelo agente.

### Manifesto privado confiável

O operador cria um arquivo UTF-8 fora do repositório, a partir de inventário
somente leitura conferido. Exemplo de forma para Auth (UUID ilustrativo, não fixture
real; substituir pelo sujeito real esperado):

```json
{
  "version": 1,
  "staging": "lbklqqqbmeyseeccdqog",
  "role": "reviewer",
  "user_id": "00000000-0000-4000-8000-000000000001"
}
```

O rótulo role NÃO concede autoridade e o manifesto não substitui memberships.
Mapear user_id/role/projeto em contexto administrativo confiável, fora do agente.
O GET /auth/v1/user verifica o sujeito no servidor; não confiar em claims decodificadas
localmente. Os seis sujeitos e seus tokens devem ser distintos, comprovados pelo
operador a partir do inventário e dos contextos; não há agregador que declare
isolamento global por seis rótulos ou permita empilhar os tokens.

Para `legacy-read`, acrescentar a chave legacy com dois objetos a e b, cada um
com repository_id inteiro positivo e run_id UUID de um run EXISTENTE confirmado.
A/B devem pertencer a projetos distintos. Para `task-read`, acrescentar tasks:

- a_own: repository_id, submission_id, head_sha (40 hex), digest (64 hex).
- a_other: mesmas chaves, outra submissão do mesmo projeto A, de outro agent.
- b: mesmas chaves, submissão existente do projeto B.

Cada manifesto deve fixar resultados de fixtures reais aprovados pelo operador.
Para reviewer/worker/viewer A, a_own/a_other são duas submissões de A; para agent,
a_own deve ser sua e a_other de outro agent. Isso exige um segundo agent de teste
para comprovar isolamento entre agentes dentro de A; hoje não existe nenhum.
Não preencher esses campos com UUIDs aleatórios para obter negativas fáceis.
Ausência de fixture/controle positivo bloqueia a matriz, não permite PASS global.

### Comandos por contexto

Somente depois de carregar o token no ambiente isolado e verificar o manifesto:

```powershell
& '.\ops\vercel-pilot\staging\Invoke-JwtPreflight.ps1' `
    -Role reviewer -Phase auth -Manifest 'C:\REIVRO-private\reviewer.json'
```

Usar `-Phase legacy-read` para duas leituras legadas, ou `-Phase task-read` para
três leituras de tarefas. Alternativa com Python 3.10+ e sem dependências externas:

```powershell
python -I '.\ops\vercel-pilot\staging\jwt_preflight.py' `
    --role reviewer --phase auth --manifest 'C:\REIVRO-private\reviewer.json'
if ($LASTEXITCODE -ne 0) { throw 'Preflight nao aprovado.' }
```

Roles aceitas: agent, reviewer, worker, viewer, other-reviewer, no-membership.
Os modos não chamam approve/confirm/submit/claim/finish/revoke. Task read usa POST
na RPC VOLATILE com action=read; a implementação revisada retorna antes do INSERT
de evento e faz apenas leituras/locks. Não usar GET para fingir que a função
VOLATILE suporta transação PostgREST read-only. É leitura lógica de dados, não
transação SQL READ ONLY no gateway. Interromper/revisar se o código da RPC mudar.

Saída JSON não contém token, user_id, payload, evidência privada nem resposta Auth.
Exit 0 = PASS no escopo declarado; 1 = FAIL; 2 = BLOCKED. Mesmo em PASS, o relatório
mantém full_authorization_matrix=NOT_VALIDATED e private_alpha=BLOCKED.
HTTP 401/404/405/429/5xx, ausência de schema/fixture e erro de transporte não são
negações RLS aprovadas. Task denial exige HTTP 403 com SQLSTATE 42501 após Auth
positivo. Resultados permitidos conferem identidade da fixture, HEAD e digest.

Matriz de leitura fixa, não escolhida pelo manifesto:

| Papel | Legacy A/B | Task A própria / A outro agente / B |
| --- | --- | --- |
| agent A | não/não | sim/não/não |
| reviewer A | sim/não | sim/sim/não |
| worker A | não/não | sim/sim/não |
| viewer A | sim/não | sim/sim/não |
| reviewer B | não/sim | não/não/sim |
| sem membership | não/não | não/não/não |

## Etapa mutável posterior: autorização e fixtures ainda necessárias

O pedido atual autoriza auditoria em leitura e preparação, não executar escritas.
São operações futuras, a autorizar explicitamente:

1. Criar/vincular identidades agent sintéticas sem converter o usuário sem vínculo;
   segundo agent em A permite controle de submissões alheias. Registrar IDs privados.
2. Reviewer aprova contratos sintéticos versionados para A/B; agents submetem
   revisões controladas; worker confiável calcula evidência independente. Não
   inserir resultados como agent e não usar SQL admin para simular login de worker.
3. Confirmar achado, aprovar/exportar política, provocar reincidência entre tarefas,
   autorizar correção limitada e verificar correção; revogar e confirmar inatividade.
4. Negativas de autoaprovação, decisão humana por worker, escritas diretas,
   contrato adulterado, HEAD/digest divergentes, replay conflitante e cross-tenant.
5. Crash/reentrega, lease expirado, fence antigo, claims concorrentes, esgotamento,
   falha de rede e reconciliação sem repetir evidências nem decisões humanas.
6. Revogar membership/política durante execução; usar JWT ainda válido e observar
   bloqueio/inconclusão. Preservar histórico e restaurar associações apenas conforme
   plano aprovado; não enfraquecer permissões. Restauração de dados novos é teste
   separado, com novo snapshot e avaliação do destino/versão.

Cada passo precisa de evidência sanitizada, IDs para limpeza e precondições de
freeze/backup. Parar operações dependentes na primeira violação de segurança.
Não há harness de escritas hospedadas implementado ou executado nesta entrega;
o documento prepara seu escopo, sem afirmar conclusão da matriz adversarial.

## Testes e limites desta entrega

- 40 testes unitários offline do preflight: PASS. HTTP de fixture explicitamente
  identificado; isso não é Auth hospedado. Cobrem seis rótulos, matrizes fixas,
  identidade divergente, erro HTTP não confundido com negação, falta de fixtures,
  contextos misturados, destino incorreto, redirects e bloqueio de ações mutáveis.
- Suíte padrão: 305 passed, 28 skipped em 17,44 s; inclui os 40 novos testes.
  Os skips PostgreSQL/opt-in não foram convertidos em PASS. Não foram reexecutados
  browser, Docker, benchmarks ou testes live GitHub nesta entrega.
- Auditoria SQL independente: PASS nos dois guards registrados acima, sem novas
  migrações, eventos, leases, tasks ou mudanças de memberships.
- JWTs reais, writes adversariais e separação efetiva reviewer/agente: BLOCKED.
- PRIVATE ALPHA: BLOCKED. Sem deploy, produção, Vercel, Checks ou recursos pagos.

Documentação oficial consultada para a preparação: Supabase
[User management/Auth](https://supabase.com/docs/guides/getting-started/tutorials/with-nextjs)
e [RLS e identidade de requisição](https://supabase.com/docs/guides/ai/rag-with-permissions).
Usar auth.uid()/memberships confiáveis; metadados editáveis não conferem autoridade.
