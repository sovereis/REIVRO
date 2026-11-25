# Cloud Memory sem dependência da Vercel

Base: `feat/reivro-vercel-dry-run` em `851180a30ba0bc1a4f86db1ef4396f0bdf156393`.

## Evidência do staging

O catálogo da organização identifica o plano Free e o staging ativo `lbklqqqbmeyseeccdqog`. Os refs, hosts PostgreSQL e regiões de staging e produção são distintos. As consultas de dados foram executadas exclusivamente em staging, em transações somente leitura. Isso confirma separação de projetos, sem estabelecer a independência de todos os segredos.

PostgreSQL 17.12, 11.941.555 bytes de banco e dispatcher V1 com hash `7b65dd994ca180ed06312d3c0a7820fe`. O ledger lista somente `20261123210041 reivro_firewall_staging` e a tabela de leases está ausente. A preparação da 002 existente se aplica ao hash observado. Use o procedimento já versionado em [ops/vercel-pilot](../ops/vercel-pilot/README.md) somente com autorização específica. Verificar acesso PostgreSQL ao host direto de staging, CA, backup e janela antes da aplicação.

Há cinco usuários Auth confirmados, não anônimos e sem banimento vigente. O projeto A tem reviewer, viewer e worker e quatro runs finalizados. O projeto B tem um reviewer e um run finalizado. O quinto usuário está sem vínculo. O tamanho observado está abaixo dos 500 MB incluídos no Free. O consumo restante de egress e outras quotas exige a tela Usage da organização. [Franquia Supabase Free](https://supabase.com/pricing)

## Matriz somente leitura com JWTs reais

Carregar no processo, via Cofre pessoal vinculado à tarefa, `REIVRO_PUBLISHABLE_KEY` e os tokens de login normal de cada fixture: `REIVRO_REVIEWER_JWT`, `REIVRO_VIEWER_JWT`, `REIVRO_WORKER_JWT`, `REIVRO_OTHER_REVIEWER_JWT` e `REIVRO_NO_MEMBERSHIP_JWT`. Vincular como variáveis de ambiente diretas se o processo for executado no Cloud. Permitir apenas `lbklqqqbmeyseeccdqog.supabase.co` para o tráfego Supabase. A execução não usa a API Admin.

Configurar `REIVRO_STAGING_REF=lbklqqqbmeyseeccdqog`, `REIVRO_WORKER_USER_ID` e as referências sintéticas do manifesto privado: `REIVRO_FIXTURE_A_REPOSITORY_ID`, `REIVRO_FIXTURE_A_RUN_ID`, `REIVRO_FIXTURE_B_REPOSITORY_ID` e `REIVRO_FIXTURE_B_RUN_ID`. Para cada projeto, escolher um run existente e finalizado. Nenhum desses valores precisa aparecer no relatório.

```bash
PYTHONPATH=. python3 ops/vercel-pilot/staging/check_memberships.py
```

O harness autentica cinco sujeitos distintos em `GET /auth/v1/user`. Depois verifica duas leituras `read_run` por sujeito, usando uma RPC somente leitura apesar de o transporte ser HTTP POST.

| Papel da fixture | Projeto A | Projeto B |
| --- | --- | --- |
| Reviewer A | lê | nulo |
| Viewer A | lê | nulo |
| Worker A | nulo | nulo |
| Reviewer B | nulo | lê |
| Sem vínculo | nulo | nulo |

O resultado distingue leitura permitida de leitura bloqueada. Confirmar papel e associação exatos pelo inventário autorizado de memberships. Permissões de escrita e revogação hospedadas ficam fora desta sondagem. Após uma remoção de membership expressamente autorizada, usar o mesmo JWT ainda válido com `--reviewer-revoked` para confirmar perda de leitura e preservar a leitura positiva do viewer. A tabela de memberships não é alterada pelo harness.

Nesta sessão não havia vínculos de segredos, chave publicável nem JWTs. O host de staging também estava fora da política Cloud. As queries de catálogo usaram o conector Supabase com identidade administrativa. A matriz por JWT não foi executada no ambiente hospedado.

## Ciclo local reproduzível

```bash
PYTHON=python3 bash scripts/test-firewall-staging.sh
```

O caso `test_isolated_cloud_and_checks_lifecycle[True]` roda o modo análise com Durable Execution e sem Vercel. Um PR sintético introduz erro de sintaxe em Python existente. O verificador usa conteúdos e patches GitHub de fixture, validando blobs e revisão. O compilador CPython usa subprocesso real com libseccomp e limites existentes. O PostgreSQL 17 descartável e sem rede aplica 001 e 002, executa as RPCs com sujeitos Auth definidos pelo harness e persiste a evidência.

O reviewer confirma a evidência e aprova o digest. O manifesto é escrito e recuperado byte a byte de um índice Git descartável. A nova revisão com regressão retorna `VIOLATION`; reentregas retornam `COMPLETED`; revisão válida retorna `PASS`; artefato divergente retorna `INCONCLUSIVE`. Revogar antes de finish resulta em `INACTIVE`. Uma nova revisão após revogação retorna `OBSERVED`, sem proteção aplicada. O teste remove temporariamente o membership do reviewer no PostgreSQL descartável e confirma que a leitura e a revisão são negadas. Nenhuma requisição de publicação ocorre no modo análise.

O cenário original de publicação simulada continua sendo testado separadamente. Todos os IDs de instalação usados pelo harness são fixtures locais, nunca vínculos hospedados.
