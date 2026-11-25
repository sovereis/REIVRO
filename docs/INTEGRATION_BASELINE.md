# Base de integração REIVRO

Auditoria da branch `feat/reivro-integrated-core` a partir de
`cae5ffaccc1a14bca8c77e21c7e59484ce18062f`.

## Inventário

| Estado | Componente | Evidência e limite |
| --- | --- | --- |
| EXISTENTE | VERIFY | [CLI e verificador sintático](../server/VERIFY.md). A regra padrão verifica espaços no diff. VERIFY v2 compara fontes Python BASE e HEAD por SHA e retorna evidência, cobertura e diagnóstico. |
| EXISTENTE | Rework Firewall local | [CLI e memória SQLite](FIREWALL_ALPHA.md). Registra análise, decisão humana e proteção. Exporta manifesto e verifica aprovação, conteúdo e escopo antes da execução. |
| EXISTENTE | Cloud Memory candidata | [SQL staging](../supabase/staging/001_firewall.sql). Projetos, memberships, runs, findings, protections e events. Chaves compostas por projeto, RLS de leitura e transições transacionais no dispatcher. O SQL em `FIREWALL_CLOUD_DRAFT.sql` é histórico. |
| EXISTENTE | Cliente staging e GitHub Checks | [Worker](../server/scop_firewall_checks.py) com `StagingMemory`, validação de webhook, confirmação da revisão, leitura do manifesto pela BASE e publicação com HEAD e run ID. |
| INCOMPLETO | Secure Runner | O compilador isolado de VERIFY v2 é a capacidade disponível. `scop_runtime` tem contratos de execução e evidência próprios. Falta interface comum de execução por capacidade e relatório integrado. |
| INCOMPLETO | Adaptadores Codex, Claude Code e Cursor | Há CLIs Python e fronteiras JSON para reutilizar. A branch não contém adaptadores dedicados aos três clientes. |
| INCOMPLETO | Operação Checks | O worker trata uma entrega. Faltam ingresso hospedado, gestão do ciclo de vida do token e recuperação de execução interrompida. Um erro após o POST requer reconciliação por HEAD, App e external ID. |
| NÃO VALIDADO | Supabase hospedado | Login real, JWT no gateway, exposição dos schemas, permissões e RLS remotas, persistência e auditoria ainda precisam de evidência. |
| NÃO VALIDADO | Checks hospedado | Instalação, token e permissões efetivas, entrega real e publicação em GitHub não exercitados nesta etapa. |

## Contratos e fluxo propostos

1. Adaptadores independentes traduzem entrada do cliente para um pedido JSON versionado em stdin e devolvem JSON em stdout. O pedido contém operação, repositório canônico, PR e permissões solicitadas. A identidade vem da sessão do operador e os segredos da configuração do processo. Cada adaptador reutiliza o mesmo núcleo e devolve estado operacional, evidência sanitizada e ID de correlação. Pedidos de confirmação ou aprovação exigem contexto humano explícito. Nenhum cliente pode promover a si mesmo a reviewer ou worker.
2. No fluxo Checks, o ingresso preserva o corpo bruto e valida HMAC e escopo de instalação. O worker comprova repositório, PR, BASE e HEAD no provedor, solicita `claim` e recebe run ID, proteção e digest ou indicação de duplicata. O Firewall continua dono das decisões e da interpretação dos resultados. A memória local continua atendendo sua CLI existente.
3. O Secure Runner expõe uma capacidade tipada para a inspeção sintática de fontes limitadas e identificadas por SHA. Reutiliza o compilador VERIFY v2 em Linux/CPython com libseccomp. Seu resultado inclui versão, regra, revisões, evidência por arquivo e estado `PASS`, `REGRESSION_DETECTED`, `INCONCLUSIVE` ou `ERROR`. Setup ou evidência insuficiente encerram a avaliação com erro ou inconclusão. Compilação sem isolamento e execução de comandos do PR ficam fora do contrato.
4. O worker passa o relatório a `finish`. Cloud Memory valida identidade, escopo, transição e digest na mesma transação que registra a auditoria. Um reviewer confirma ou rejeita achados, propõe uma proteção e aprova ou revoga o manifesto pelo digest exato. O artefato em Git fornece os bytes, enquanto o banco autoriza o uso. O Checkout de PR e seu conteúdo são entrada não confiável.
5. Checks consome o resultado finalizado. `PASS` vira sucesso, `VIOLATION` vira falha, a decisão `review_required` exige ação (incluindo `ERROR` e `INCONCLUSIVE`), e `OBSERVED` e `INACTIVE` são neutros. O payload público contém resumo fixo, HEAD e external ID do run. A evidência detalhada fica sob controle de acesso na memória.

## Limites de confiança

- O gateway valida JWT. O banco decide pelo `auth.uid()`, membership e projeto em cada chamada. Claims editáveis, parâmetros de repositório e respostas de clientes são dados de entrada.
- Expor somente `reivro_checks_api` para este recurso. Manter `reivro_cloud` privado. O dispatcher privilegiado usa search path vazio e verifica escopo antes de executar mutações. Administradores de banco provisionam fixtures por canal separado.
- O worker atesta o resultado do verificador e pode claim/finish no escopo instalado. O isolamento de administração, runner e reviewer é condição de segurança. O token de instalação do GitHub tem escopo próprio e nunca integra o contrato com agentes.
- A chave publicável e o JWT de usuário autenticado são o caminho de dados. A Secret API Key administrativa por proxy Codex fica fora do fluxo. Auditar identidade, run e transição sem imprimir tokens, senhas ou corpo bruto de respostas com credenciais.
- Preservar o lock por projeto, a unicidade de entregas/revisões, a revogação terminal e a verificação do digest. Antes de repetir publicação incerta, reconciliar pelo external ID e HEAD no GitHub.

## Primeiro incremento implementável da Cloud Memory

Entregar um harness de staging opt-in para exercitar o cliente existente `StagingMemory` com Auth real e um relatório redigido. O alvo é exclusivamente `https://lbklqqqbmeyseeccdqog.supabase.co`. Rejeitar qualquer outro ref antes de chamadas. Não chamar GitHub Checks. Provisionar por canal administrativo aprovado e separado do proxy Codex. Confirmar a versão da migração, os grants e a exposição de `reivro_checks_api` antes do teste.

1. Preparar um namespace de fixtures por execução com dois projetos sintéticos A e B, IDs de repositório/instalação exclusivos e cinco usuários Auth sintéticos. A recebe reviewer, viewer e worker. B recebe outro reviewer. O quinto usuário fica sem membership. Guardar IDs de usuários, projetos e runs em manifesto privado de limpeza, sem credenciais.
2. Usar `POST /auth/v1/token?grant_type=password` com a chave publicável e as credenciais de cada fixture. Conferir os sujeitos contra os IDs provisionados e a origem contra o emissor de staging. Os JWTs ficam em memória. Confirmar que o Data API rejeita JWT ausente, inválido ou expirado. A autorização positiva e negativa é comprovada pela resposta do gateway/banco.
3. Instanciar `StagingMemory(ref, publishable_key, access_token)` por identidade. Chamadas RPC usam `Content-Profile: reivro_checks_api`. `dispatch` recebe `{action, request}`. `read_run` recebe `{p_repository_id, p_run_id}` e retorna `{run, findings}` para leitura autorizada ou JSON nulo quando não há linha acessível.
4. Com o worker A, chamar `claim` com repository_id, installation_id, repository, base_ref, delivery UUID, pr, base_sha e head_sha. Repetir com mesma revisão e verificar duplicata. Chamar `finish` com repository_id, installation_id, run_id, report e artifact_digest. Usar relatórios sintéticos coerentes com `verify-v2` e com a identidade do claim. Criar dois achados em runs distintos, um para confirmação e outro para rejeição. Worker sem claim próprio, instalação errada, reviewer e viewer recebem negação para operações de worker.
5. Reviewer A confirma e rejeita os respectivos achados. Para o confirmado, chamar `propose` e conferir SHA-256 dos bytes UTF-8 do manifesto retornado. Usar `subject` e `reason` nas chamadas de revisão, e `digest` em `approve` e `revoke`. Verificar digest incorreto recusado, aprovação com digest correto, revogação e impossibilidade de reaprovar a mesma proteção revogada. Viewer e worker não revisam. Reviewer B e usuário sem associação não leem nem alteram A, mesmo recebendo os IDs. Reviewer e viewer de A conseguem ler o run A. Worker não lê evidência por `read_run`. Verificar a leitura positiva do reviewer no projeto B com fixture própria provisionada.
6. Conferir `events` por sessão de auditoria de staging com acesso autorizado. Vincular ator, projeto, assunto e tipo à operação bem-sucedida. Confirmar que tentativas negadas não mudam o estado nem produzem eventos de transição. Registrar resultado por caso, status sanitizado e IDs. Interromper etapas dependentes diante de acesso indevido ou mutação não autorizada.

Aceite do incremento: todos os casos de Auth real, RLS, autorização, transições, isolamento e auditoria passam no staging com evidência redigida e sem publicação. Aceite posterior da integração: os três adaptadores passam a mesma suíte de contrato e comunicam falhas sem ampliar permissões. O runner mantém os limites de VERIFY v2. A publicação em piloto exige um teste independente em repositório controlado, que compare conclusão, HEAD, run e resultado de revogação, com autorização própria.

## Evidência da auditoria

| Execução | Resultado |
| --- | --- |
| `python -m pytest -q -rs` no SHA inicial | 184 passaram, 2 falharam, 6 foram pulados. Os testes HTTP sequenciais podiam observar a resposta antes de o servidor liberar o lock. |
| `python -m pytest -q -rs` com sincronização do helper HTTP | 186 passaram, 6 foram pulados. O teste explícito de 409 por operação concorrente continua ativo. |
| `PYTHON=<venv>/bin/python bash scripts/test-firewall-staging.sh` | 21 passaram. PostgreSQL 17 descartável e sem rede, esquema Auth simulado e GitHub substituído por fixtures. Inclui ciclo de vida com RLS, deduplicação, concorrência e revogação. |
| `PYTHON=<venv>/bin/python SCOP_CHROMIUM=/usr/bin/chromium node --test tests/ui/*.test.cjs` | 10 passaram com Chromium do sistema. O download do Chromium empacotado pelo Playwright foi bloqueado por HTTP 403. |
| `SCOP_LIVE_TESTS=1 python -m pytest -q -rs` | 186 passaram, 5 falharam, 1 foi pulado. As cinco falhas reportaram GitHub indisponível. A verificação direta de `api.github.com` retornou HTTP 403 do túnel CONNECT. |

A instância Cloud observada não tinha vínculos de segredos ou variáveis de runtime. A política de rede ativa não incluía o host do staging. Para o próximo incremento, usar uma execução com acesso explícito ao host, chave publicável e credenciais sintéticas de login. Provisionamento e inspeção administrativa dependem de um canal aprovado em staging. A etapa de auditoria não tentou autenticação administrativa, aplicou migrações somente no PostgreSQL descartável e não publicou Checks.
