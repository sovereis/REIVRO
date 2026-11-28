# REIVRO — handoff de engenharia e operação

Checkpoint documental: **27/11/2026, America/Sao_Paulo**. Repositório correto:
**[sovereis/REIVRO](https://github.com/sovereis/REIVRO)**. Não usar `sovereigns/REIVRO`.

Este documento transfere contexto para outra conversa do Codex. Não autoriza
migrations, escritas hospedadas, deploy, despesas ou liberação da alpha. A revisão pós-003 inspecionou Git e staging em transação somente leitura. O founder reportou a execução dos cinco JWTs para Auth e RLS legada. A matriz de tarefas e as suítes do produto permanecem sem nova execução.

## 1. Leia primeiro: situação operacional

- O núcleo integrado mais recente confirmado está em
  `feat/reivro-hosted-control-plane`, **e280fa4f096ff7aa4d6d190d678982d3ea26fe49**.
- O kit operacional legível está publicado em `ops/migration-003-staging`,
  **e274c8248d56b2d155df8f30d7d5dc8e74d604a6**, filho direto de e280fa4.
  Esse commit acrescenta somente o script e suas instruções.
- O handoff original d642490 deriva de e274c82. A revisão pós-003 acrescenta scripts de auditoria e preparação JWT.
  O próprio SHA do handoff deve ser obtido por `git rev-parse HEAD` ou pelo remoto;
  ele não pode ser incluído no próprio conteúdo do commit sem circularidade.
- **001, 002 e 003 aplicadas no staging e registradas no ledger.** A auditoria independente somente leitura confirmou o estado pós-003. Não reaplicar migrations.
- **Cinco JWTs reais aprovados para Auth e RLS legada, conforme relato do founder no Windows.** A auditoria independente conferiu o inventário e a preservação dos vínculos. A matriz de tarefas do Control Plane ainda requer Agent, fixtures e autorização específica.
- Writers foram reportados suspensos pelo founder. Isso é um checkpoint histórico,
  não uma garantia permanente: reconfirmar antes de qualquer nova escrita.
- **PRIVATE ALPHA: BLOCKED. HOSTED SECURITY BOUNDARY: NOT VALIDATED.**

### Linguagem de evidência

| Termo | Significado neste handoff |
| --- | --- |
| Implementado | Código/contrato existe no Git; não implica execução real hospedada |
| Validado localmente | Há execução registrada em ambiente local/descartável, no escopo indicado |
| Observado no staging | Há inspeção administrativa somente leitura ou aplicação reportada/auditada; não implica teste com JWT de usuário |
| Reportado pelo operador | Founder executou e informou; arquivos privados não foram auditados diretamente pelo Codex |
| Pendente/bloqueado | Não há evidência suficiente; não transformar ausência de prova em PASS |

## 2. Visão do produto e arquitetura

REIVRO verifica trabalho de agentes de programação por critérios e evidências
independentes, aprende com falhas confirmadas por humanos e identifica sua
reincidência. Público inicial: desenvolvedores/equipes dos Estados Unidos.

**VERIFY → LEARN → PREVENT**, com memória híbrida:

1. Um operador aprova critérios verificáveis antes do trabalho do agente.
2. O agente entrega uma declaração e referências Git; essas entradas são não
   confiáveis. Nome do agente, stdout, exit code ou declaração de conclusão não
   são evidência autoritativa por si só.
3. VERIFY fixa BASE/HEAD, lê dados Git e avalia regras suportadas. A verificação de
   tarefas atual é estática. O compilador sintático não é um executor geral.
4. LEARN registra evidência e achados no journal. O humano confirma/rejeita e
   escolhe se uma falha deve originar política reutilizável.
5. PREVENT/Rework Firewall usa proteções aprovadas, vinculadas por digest,
   versionáveis e revogáveis. Reincidência exige identidade determinística da
   falha, tarefa/revisão distintas e evidência; sem similaridade semântica presumida.
6. Um relatório diferencia declaração, verificação, estado da proteção, decisão
   de segurança e resultado operacional. Inconclusão nunca equivale a sucesso.

**Hoje:** CLI local, SQLite privado, contratos/evidências Git e SQL Cloud Memory.
**Decisão futura consolidada (alternativa B):** CLI local com plano de controle
hospedado para autoridade humana independente; manter evolução para execução
integralmente hospedada. Não criar dependência operacional de WSL, VM local ou
computador permanentemente ligado. A Developer Preview local permanece disponível;
essa decisão não significa que o transporte remoto já foi implementado.

Fluxo remoto pretendido: CLI/agente → HTTPS autenticado → submissão persistida →
fila → worker confiável → VERIFY → Cloud Memory → revisão humana independente →
proteções. API/CLI remota/fila de tarefas ainda são contratos futuros. Adaptadores
Vercel preparados anteriormente não constituem esse fluxo hospedado validado.

## 3. Decisões e limites de confiança consolidados

- Reutilizar VERIFY, memória e Rework Firewall existentes; não criar outro Firewall.
- SQLite local e PostgreSQL hospedado têm autoridades e persistência diferentes;
  preservar ambos, sem retirar verificações independentes para reduzir duplicação.
- Contratos locais e contratos hospedados têm codificações de digest diferentes.
  No hospedado, o digest é SHA256 do texto JSONB do PostgreSQL; o futuro cliente
  deve obter/comparar o digest aprovado no servidor, não reutilizar o digest local.
- Autorização hospedada deriva de `auth.uid()` e memberships confiáveis consultados
  a cada RPC; não de metadados editáveis pelo usuário ou papel declarado pelo agente.
- Agente não aprova critérios, confirma achados, aprova/revoga políticas, produz
  resultados autoritativos ou finaliza verificações. Worker não decide como humano.
- Credenciais de reviewer ficam em contexto inacessível ao processo do agente.
  Mesmo usuário de SO, mesmo armazenamento de tokens ou perfil controlado pelo
  agente não estabelecem separação. Uma conta/browser separado só ajuda se o agente
  também não puder ler seu perfil, depurar seu processo ou controlar sua sessão.
- Administradores de PostgreSQL/hosting e o worker autoritativo são confiáveis.
  RLS não prova a verdade semântica da evidência produzida por um worker comprometido.
- Durable Execution é entrega **ao menos uma vez com efeitos idempotentes**, nunca
  promessa de execução exatamente uma vez. Claim atômico, tentativa UUID, fence,
  lease de 60 s, janela máxima da tentativa de 120 s e até três claims.
- Estados persistentes: pending, running, completed, retryable, terminal. Worker
  antigo/lease expirado não finaliza; ACK exige estado persistido que o justifique;
  falha de transporte pede reconciliação, não descarte nem aprovação.
- `one_active_guard` continua protegendo sintaxe. Políticas de tarefa múltiplas usam
  `task_policies`, sob a mesma autoridade/projeto; não relaxar o índice de sintaxe.
- Revogação e finish compartilham lock de projeto. Mudança no conjunto aprovado
  durante a execução resulta em INCONCLUSIVE.
- DRY RUN não publica GitHub Checks. Detecção sem mecanismo de bloqueio exercitado
  não deve ser chamada de prevenção efetiva.
- Execução funcional arbitrária permanece **desabilitada**. Docker/libseccomp
  isoladamente não certificam uma fronteira segura para executar PRs arbitrários.

## 4. Branches, ancestralidade e referências

HEADs remotos foram conferidos durante este handoff. Todos os itens de evolução
abaixo, até alpha e control plane, são ancestrais de e274c82, conforme
`git merge-base --is-ancestor`. Não é necessário juntá-los novamente por merge.

| Branch | SHA remoto confirmado | Conteúdo principal |
| --- | --- | --- |
| feat/reivro-integrated-core | 2d847e2abada78d73e417301e3abcd7f7b7891b5 | Base integrada e auditoria |
| feat/reivro-github-pilot-infra | d0899647f83a0a9275bda021bb7943b76e2f1957 | Preparação do piloto |
| feat/reivro-vercel-dry-run | 851180a30ba0bc1a4f86db1ef4396f0bdf156393 | Adaptadores, recuperação, configuração |
| feat/reivro-zero-cost-validation | aac34951c2936b9926f7c2e186e40dcaad101e88 | Ciclo local sem Vercel |
| feat/reivro-agent-integration | 20a9408faabf9a1425ac1f1bd1fef88fc9e72c03 | Contrato Agent Integration v1 |
| feat/reivro-agent-feedback | 3c621d0e7c1dee2b151f252c9018b861e20633e2 | Feedback e recuperação do journal |
| feat/reivro-effectiveness-benchmark | 314f9277a652c9eee7dd1be02ea37fe867b44428 | Benchmark V1 |
| feat/reivro-core-quality | 0ab1c200d012f82bebd28839558f3e37dcba44a6 | Achados independentes e benchmark V2 |
| feat/reivro-functional-regression | 5af68632565d88ab508e410f879d47b6f8ea8ba5 | Comparador funcional declarativo |
| feat/reivro-task-verification | 3f03d05d8408d372f965ff3b254342f75e243556 | Critérios estáticos de tarefas |
| feat/reivro-task-firewall | 247e78ff295337d1f53c610057167f8a7b0d80fa | Políticas e reincidência entre tarefas |
| feat/reivro-developer-preview | 40c389d35fa896dc22d8da31ef7806a645f7576d | CLI integrada e demo |
| feat/reivro-alpha-readiness | 9444d213be0907ad77ee6a2d77c3bf17101cd1e6 | Kit alpha e recuperação local |
| feat/reivro-hosted-control-plane | e280fa4f096ff7aa4d6d190d678982d3ea26fe49 | Fundação e correção de identidade da execução |
| ops/migration-003-staging | e274c8248d56b2d155df8f30d7d5dc8e74d604a6 | Script operacional e instruções |

A landing `feat/landing-page-v01`, SHA
`92290d47b4d43746438e70678f7c25b5e4d5df7c`, **não é ancestral** de e274c82.
Não alterá-la nem tentar consolidá-la nesta missão. O HEAD remoto de main observado
é `3e36dbdb76bd859a0f039a156d9e9a6ef8b0b6ae`; main não é a base deste handoff.

Commit `b45872befab5b771f7b80ae8c8db054848a53ca6` contém a primeira 003, com colisão
entre execução de tarefa/sintaxe. **Não aplicar essa versão antiga.** A correção
aprovada está em e280fa4. SHAs antigos das missões são referências históricas, não
um pedido para reiniciar o desenvolvimento a partir delas.

## 5. Inventário de capacidades e arquivos

| Capacidade | Implementação principal | Evidência disponível | Limite atual |
| --- | --- | --- | --- |
| VERIFY sintático | server/scop_verify.py; server/scop_verify_syntax.py | BASE/HEAD, fonte/blob e compilação isolada em testes locais | Não comprova semântica funcional geral |
| Secure Runner sintático | server/scop_firewall_sandbox.py; server/scop_verify_syntax.py | Subprocesso/limites/libseccomp no caminho sintático | Não habilita execução arbitrária |
| Memória/Firewall local | server/scop_firewall.py; server/scop_firewall_memory.py | Journal, revisão, aprovação, artefato, revogação e ciclo local | Autoridade local depende da separação real de contas |
| Cloud Memory/Checks worker | server/scop_firewall_checks.py; supabase/staging/001_firewall.sql | SQL/worker locais e inspeção administrativa do staging | Leitura legada com cinco JWTs aprovada conforme relato do founder |
| Durable Execution | supabase/staging/002_durable_execution.sql; testes de recovery | Testes PostgreSQL locais; 002 aplicada/auditada no staging | Recuperação via fila hospedada não validada |
| Vercel ASGI/Queues/Sandbox | server/scop_firewall_vercel.py; ops/vercel-pilot/app.py; worker.py; vercel.json | Adaptadores e testes locais, configuração preparada | Sem ensaio hospedado; plano/custos/disponibilidade não confirmados |
| Agent Integration/Feedback | server/scop_agent_integration.py; server/scop_agent_feedback.py; ops/agent-integration/ | Contratos, CLI, feedback sanitizado, retry/correção limitada | Ciclo completo com cliente real e operador separado pendente |
| Comparador funcional | server/scop_verify_functional.py; docs/FUNCTIONAL_REGRESSION.md | 17 observações declarativas esperadas | Zero execuções funcionais reais; executor bloqueado |
| Task Verification v1 | server/scop_task_verification.py; docs/TASK_COMPLETION_VERIFICATION.md | Arquivo obrigatório, mudança requerida, escopo, proteção, evidência e revisão | VERIFIED cobre critérios estáticos aprovados, não objetivo semântico completo |
| Task Firewall | server/scop_task_policy.py; docs/TASK_FIREWALL.md | Reincidência, aprovação, correção e revogação locais | Não habilitar regra remota sem matriz hospedada |
| Developer Preview | reivro; server/scop_preview.py; server/scop_preview_demo.py | CLI humana/JSON, instalação/demo locais | WSL/segunda máquina/alpha externa não validados |
| Hosted control plane | supabase/staging/003_control_plane.sql; docs/HOSTED_CONTROL_PLANE.md | RLS/RPCs/roles, concorrência e restore em PostgreSQL descartável | 003 confirmada no staging; matriz JWT de tarefas e transporte remoto pendentes |

Documentos de entrada: `docs/DEVELOPER_PREVIEW.md`, `docs/alpha/README.md`,
`docs/alpha/VALIDATION.md`, `docs/HOSTED_CONTROL_PLANE.md`,
`docs/ENGINEERING_QUALITY_GATE.md`, `docs/AGENT_INTEGRATION.md`,
`docs/CLOUD_MEMORY_ZERO_COST.md`, `ops/vercel-pilot/README.md` e
`ops/vercel-pilot/staging/CONTROL_PLANE_003_LOCAL.md`.

Atenção a documentos históricos: `docs/PRODUCT.md` e `docs/INTEGRATION_BASELINE.md`
contêm inventários de fases anteriores; alguns itens então planejados já foram
implementados. `docs/HOSTED_CONTROL_PLANE.md` ainda menciona backup pendente e
nenhuma migration aplicada na época de sua escrita. O checkpoint operacional
mais recente é a seção seguinte; não tratar frases históricas como estado atual.

## 6. Missão 6.4: recuperação, staging e migrations

### Destinos

- Único staging permitido: **lbklqqqbmeyseeccdqog**.
- Produção proibida: **hnlmnswotenppgdqxvkv**. Nunca conectar para operar/testar.
- Session Pooler validado pelo founder: `aws-1-us-west-1.pooler.supabase.com`,
  porta `5432`, usuário `postgres.lbklqqqbmeyseeccdqog`, banco `postgres`,
  SSL `verify-full`. Não confundir esse acesso SQL com JWTs de usuários.
- Plano Free e tamanho abaixo da franquia foram observados em missão anterior.
  Quotas, egress e custos atuais não foram revalidados; não assumir gratuidade
  ilimitada. Ativação Vercel foi adiada por orçamento zero.

### Recuperação aceita — evidência reportada pelo founder

Backup CUSTOM de 432353 bytes, 664 entradas TOC, origem PostgreSQL 17.12.
Restauração seletiva para PostgreSQL 19 local e isolado, porta 55464, exit 0.
Abrange Auth necessário e o escopo SQL REIVRO, não recuperação integral Supabase.

O founder reportou: sete tabelas com SHA256 equivalentes (auth.users e as seis
originais de reivro_cloud), histórico de decisões preservado; papéis/memberships,
owners, privilégios padrão, ACLs normalizadas, privilégios efetivos de sequência,
corpos de funções, SECURITY DEFINER, search_path, metadados estruturais e RLS
comparados; 36 colunas NOT NULL equivalentes; zero constraints não validadas;
sequência `12/true`. Testes SQL reportados negaram escrita direta em protections,
acesso cross-project e identidade desconhecida, e permitiram reviewer/viewer.

Também reportou manifesto de 23 arquivos validado por SHA256, permissões NTFS e
BitLocker. Evidências originais permanecem exclusivamente no computador do founder;
não solicitar upload. Codex não auditou diretamente backup/arquivos privados.
As identidades SQL desses testes não são JWTs reais. Diferença PostgreSQL 17→19
não comprova restauração reversa em Supabase 17 ou recuperação de sessões Auth.

Em 26/11/2026 o founder informou nova consulta somente leitura, SSL verify-full,
exit 0 e zero diferenças integrais entre os relatórios de origem e atualização.
Isso fechou as pendências da recuperação seletiva e permitiu GO técnico
condicionado à manutenção do congelamento e ao preflight imediato. Não foi
uma autorização permanente para qualquer operação futura.

### Congelamento e preflight reportados

Inventário acessível não identificou processo local explícito de staging, webhooks
nos dois repositórios ou Actions ativas; demo sem workflows. Apps instalados
observados incluíam ChatGPT Codex Connector e Vercel; não foram desativados.
Ausência observada não prova ausência de writers fora das fontes acessíveis.

Founder confirmou outras escritas suspensas, duas amostras estáveis, zero runs
pendentes, 12 eventos, sequência `12/true` e relatórios integrais de 213 linhas,
sem divergências. Reconfirmar freeze e frescor antes de novo passo.

### Estado pós-003 confirmado em auditoria independente

| Migration | Estado e evidência | Ação pendente |
| --- | --- | --- |
| 001_firewall.sql | Aplicada; ledger `20261123210041`, nome `reivro_firewall_staging` | Preservar schema, dados e decisões |
| 002_durable_execution.sql | Founder aplicou; inspeção independente somente leitura e postcheck/data guard passaram | Ledger 002 reconciliado e conferido |
| 003_control_plane.sql de e280fa4 | Aplicada pelo founder, Postcheck003 aprovado conforme seu relato e linha de base confirmada independentemente | Validar JWTs reais da RPC de tarefas |

A 003 corrigida cria `task_contracts`, `task_submissions`, `task_policies` e
`task_corrections`; amplia o contrato de memberships para agent e expõe a RPC
restrita `reivro_checks_api.task_dispatch`, com helper privado
`reivro_cloud.execution_dispatch`. As tabelas novas têm RLS e não recebem grants
de acesso direto dos clientes. Grants de execução não substituem a autorização
interna por identidade e membership.

A correção e280fa4 acrescenta `runs.task_submission_id`: histórico de sintaxe mantém
NULL; índices parciais `syntax_delivery`/`syntax_revision` preservam deduplicação
de sintaxe, e `task_execution` identifica tarefa por projeto/submissão imutável.
Dessa forma, sintaxe concluída não faz uma tarefa nova parecer concluída, e dois
contratos no mesmo PR/BASE/HEAD não compartilham resultado. `dispatch` legado não
pode renovar/finalizar um task run. Os testes acrescentados cobrem ambas as ordens
de execução, histórico anterior à migration e reentregas concorrentes.

Pós-002 conhecido: 2 projetos, 4 memberships, 5 usuários Auth, 5 runs/0 pendentes,
4 findings, 1 protection revogada, 12 eventos, sequência `12/true`.
`execution_leases` presente/vazia, RLS ativo, ACL apenas do owner, sete colunas
esperadas e oito constraints validadas. Dados originais preservados; comparação
Auth antes/depois é conclusão reportada pelo operador, com hash atual registrado
independentemente. A auditoria pós-003 confirmou igualdade dos sete hashes da linha de base e sequência 12/true, sem leases nem registros de tarefas. Memberships: dois reviewers, um viewer e um worker.

Fingerprints MD5 relevantes confirmados após 003:

| Função | MD5 |
| --- | --- |
| reivro_cloud.dispatch(text,jsonb) V3 | 5789d2beb5926fbfe2006973dd66d337 |
| reivro_cloud.dispatch_v1(text,jsonb) | 7b65dd994ca180ed06312d3c0a7820fe |
| reivro_checks_api.dispatch(text,jsonb) | 33ebec2c2d3ac3c64b6955369778fc61 |
| reivro_checks_api.read_run(bigint,uuid) | 8815aa0cb0ee1f7b6c1d64315bd019d1 |

Owner/security/search_path e ACLs foram inspecionados. Não confundir MD5 de prosrc
com SHA256 dos arquivos SQL. O kit verifica ambos nos seus respectivos contextos.

### Ledger reconciliado e kit histórico

A aplicação manual da 002 não atualizou o ledger CLI automaticamente. O ledger atual contém as três entradas aprovadas. Os corpos SQL e as chaves de idempotência de 002 e 003 coincidem com o kit.

- 002 reconciliada: `20261126000200`, `reivro_durable_execution_002`.
- 003 registrada: `20261126000300`, `reivro_control_plane_003`.
- São identificadores de bookkeeping, não horários reais de aplicação.
- Ledger002 grava o SQL aprovado como texto inerte e chave de idempotência após
  guards; não executa o texto armazenado. Colisão de ledger deve interromper.
- Apply003 engloba corpo aprovado, guards e ledger 003 na mesma transação.

Kit publicado e fonte autoritativa das instruções operacionais:

- `ops/vercel-pilot/staging/control-plane-003-local.ps1`
- `ops/vercel-pilot/staging/CONTROL_PLANE_003_LOCAL.md`
- Commit e274c8248d56b2d155df8f30d7d5dc8e74d604a6.
- SHA256 do script: `d98931ca01de7a3a37229230c2aef6ad302689bdd4ed495b69e83760f8d128a0`.
- SHA256 SQL 002: `2ea6824530ffed52a33f6ac449f0b396f19b24d511eef092fc713bea10c39fb4`.
- SHA256 SQL 003: `6ffe1673191eac4335c3798daf9d3c34cb01551f9f674dd9ebdfa31215c88c19`.

O script usa blobs Git do commit e280fa4, não os SQLs alteráveis do working tree.
Formato UTF-8 sem BOM/LF. Modos separados: Prepare (offline), Audit002/Inspect,
Ledger002 (confirmação explícita), Preflight003, Apply003 (confirmação explícita),
Postcheck003. SQL somente por `psql -f`, `-X`, `-W`, ON_ERROR_STOP e exit code.
SSL verify-full; não incluir senha em argumento, log, chat ou Git.

O envio anterior por artefato falhou; reconstrução Base64/GZip também falhou CRC.
**Abandonar esses métodos e o antigo control-plane-003.ps1.** Usar somente o arquivo
legível publicado acima. O download raw pelo commit e274c82 foi testado e seu hash
conferido. PowerShell 7.4.6/Linux passou preparação e controles de interrupção;
Windows PowerShell 5.1 ainda não tem confirmação de execução pelo founder.

## 7. Próxima missão operacional: autenticação real com pré-condições

O founder reportou login, Auth e leituras legadas aprovados para reviewer A/B, viewer A, worker A e a conta sem vínculo no Windows. As cinco senhas foram redefinidas de acordo com o founder. A auditoria administrativa de 27/11/2026 confirmou os cinco UUIDs com os mesmos papéis, quatro memberships preservadas e zero submissões. O founder reportou `SELECTIVE_RESTORE_PASS` pós-JWT em PostgreSQL 19, com auditorias Cloud/Auth antes e depois e na restauração local. O caminho e os artefatos do backup permanecem privados no computador do founder; não os publicar. O arquivo privado não foi lido pelo Codex; o kit 0974242 inclui reconciliação local de SHA256, tamanho, TOC e versões. [Gate Windows](ops/vercel-pilot/staging/WINDOWS_CONTROL_PLANE_GATE.md).

Em 28/11/2026, o founder reportou `AGENT_A_MEMBERSHIP_RECOVERED` no Windows. Auditoria independente imediatamente posterior, somente leitura, confirmou seis usuários Auth, cinco memberships com papéis 2 reviewer/1 viewer/1 worker/1 agent, Agent A confirmado e associado exclusivamente ao projeto A. O UUID e o caminho do receipt permanecem privados; não publicá-los.

A mesma auditoria confirmou dispatcher V3, ledger 001–003, dois projetos, cinco runs legados sem pendências, quatro findings, uma protection, 12 eventos e sequência `12/true`. Não havia contratos, submissões, políticas, correções, leases, transações preparadas ou transações concorrentes. As quatro tabelas de tarefas mantêm RLS e nenhum grant direto para `anon` ou `authenticated`. Estado do Agent permanece `AGENT_A_PROVISIONED`. Em 28/11/2026, o founder reportou `FIRST_CONTRACT_APPROVED_NO_SUBMISSION`. Auditoria independente somente leitura confirmou exatamente um contrato sintético version 1 no projeto A, digest recomposto a partir do JSONB, BASE vinculada ao commit fixture aprovado, critério `exists: guide.md`, um evento `task_approve_contract` pelo reviewer A e nenhuma submissão. O journal avançou de forma coerente para 13 eventos/sequência `13/true`; continuam inexistentes task runs, leases, policies, corrections e runs pendentes.

O gate JWT somente leitura do Agent está em `ops/vercel-pilot/staging/Test-ReivroAgentControlPlaneJwt.ps1`. Ele obtém JWT por login normal, confere o UUID do receipt privado e testa negação de papel humano, submissão inexistente e projeto B sem imprimir o token. O planejador `Prepare-ReivroControlPlaneFixture.ps1` usa PostgreSQL 19/SSL verify-full e `plan_staging_task_fixture.sql` em transação read-only para gerar IDs/digest apenas na pasta privada. Nenhum deles aprova contrato ou cria submissão. Em 28/11/2026, o founder reportou `FIRST_AGENT_SUBMISSION_CREATED_NO_EXECUTION`. Auditoria independente somente leitura confirmou uma submissão raiz do Agent A vinculada ao contrato/digest, BASE e HEAD sintéticos aprovados, verifier `task-completion-v1`, `run_id`/resultado/parent nulos, um evento `task_submit` pelo Agent e o evento anterior de aprovação pelo reviewer. O journal avançou coerentemente para 14 eventos/sequência `14/true`; continuavam inexistentes task runs, leases, policies, corrections e runs pendentes.

O founder reportou `SUBMISSION_JWT_MATRIX_READ_ONLY_PASS` em execução real no Windows para as seis identidades. A auditoria administrativa posterior reconfirmou contrato, digest, submissão, identidades e journal `14/true`, ainda sem task run ou lease. O script corrigido em `Test-ReivroSubmissionJwtMatrix.ps1` normaliza coleções vazias sob StrictMode e mantém diagnósticos sanitizados. O próximo gate está preparado em `Claim-ReivroFirstAgentTask.ps1`. O claim permanece não autorizado: quando especificamente autorizado, ele cria um task run, um lease com fence 1/attempt UUID/janelas 60–120 s, vincula `run_id`/policy_set à submissão e grava `lease_claim` mais `task_claim`. Não executa trabalho, renew, finish ou fail. O freeze permanente depende da confirmação do operador.

### Papéis a comprovar com JWTs reais

| Sujeito | Deve permitir | Deve negar |
| --- | --- | --- |
| agent A | Submeter contrato aprovado e ler submissões próprias | Aprovar/alterar contrato, confirmar, aprovar/revogar política, finalizar, ler submissões alheias |
| reviewer A | Aprovar versões, confirmar/rejeitar pelos contratos suportados, aprovar/revogar políticas, autorizar correção, ler projeto A | Resultado autoritativo de worker e acesso ao projeto B |
| worker A | Claim, renew, fail, finish e leitura de tarefa no escopo autorizado | Decisão humana, finalização sem posse, fence antigo ou lease expirado |
| viewer A | Leituras de tarefas do projeto | Toda escrita e outro projeto |
| reviewer B | Operações autorizadas no próprio projeto | Dados/decisões do projeto A |
| sem vínculo | Login válido, quando existente | Todas as operações de projeto |

A RPC de tarefas `reivro_checks_api.task_dispatch` não tem a mesma matriz da
RPC legada `read_run`: no harness existente `check_memberships.py`, worker não
lê runs legados (retorna nulo em A/B), enquanto reviewer/viewer A leem A e
reviewer B lê B. Não mudar permissões para fazer um harness passar.

Identidades em PostgreSQL descartável usam claims sintéticas; autenticação Auth,
JWT e gateway PostgREST reais precisam de execução própria. Conferir schemas
expostos e grants sem ampliar exposição indevidamente.

### Critérios de aceite da matriz hospedada

- Login real distingue todos os sujeitos; memberships confiáveis coincidem com o
  inventário. Agent/reviewer não compartilham credenciais/processo controlável.
- Leituras/escritas positivas funcionam somente para os papéis/escopos previstos.
  Agent/worker não exercem decisões humanas; escrita direta nas tabelas é negada.
- Contrato aprovado é imutável; digest/revisões/verifier/policy_set vinculam a
  execução. Falsificação, replay conflitante e HEAD divergente são negados.
- Reentrega e concorrência preservam um efeito por identidade; leases expirados e
  fences antigos não gravam. Recuperação não repete decisões nem evidências.
- Remoção de membership e revogação de política valem também com JWT ainda válido;
  finish concorrente não produz VERIFIED indevido após mudança de policy_set.
- Estado persistido é reconciliado antes do ACK. Sintaxe continua compatível com
  one_active_guard e seu namespace separado dos task runs.
- Nenhuma credencial humana chega ao agente, worker payload ou sandbox. Apenas
  dados sintéticos novos, IDs registrados e limpeza revisada separadamente.
- Falha de autorização/cross-tenant/escrita direta interrompe operações dependentes,
  preserva evidência e mantém PRIVATE ALPHA bloqueada.

Variáveis existentes documentadas: `REIVRO_STAGING_REF`, `REIVRO_PUBLISHABLE_KEY`,
`REIVRO_REVIEWER_JWT`, `REIVRO_VIEWER_JWT`, `REIVRO_WORKER_JWT`,
`REIVRO_OTHER_REVIEWER_JWT`, `REIVRO_NO_MEMBERSHIP_JWT`,
`REIVRO_WORKER_USER_ID` e referências privadas `REIVRO_FIXTURE_A_REPOSITORY_ID`,
`REIVRO_FIXTURE_A_RUN_ID`, `REIVRO_FIXTURE_B_REPOSITORY_ID`,
`REIVRO_FIXTURE_B_RUN_ID`. O harness legado não contempla agent; a adaptação para
controle de tarefas precisa de revisão explícita e token de agent em processo próprio.
Não entregar tokens de todos os papéis ao processo do agente.

`REIVRO_STAGING_AUTH_ADMIN_KEY` esteve ausente no processo; a integração Secret API
Key via proxy Codex teve HTTP 401. Segredo de rede não é necessariamente variável
ambiente. Cadastro no Cofre não prova vínculo com a tarefa. Conferir bindings e
rede desta nova sessão sem revelar valores; não contornar proxy. Essas observações
históricas não provam que a chave continua ausente nem habilitam seu uso administrativo.

## 8. Testes e benchmarks: resultados registrados, não reexecutados agora

Último checkpoint técnico de e280fa4, conforme `docs/HOSTED_CONTROL_PLANE.md`:

| Execução | Resultado registrado | Escopo |
| --- | --- | --- |
| Pytest padrão após correção | 265 passed, 28 skipped; 18,64 s | Local; skips opt-in, não valida staging |
| Harness PostgreSQL corrigido | 40 passed; 36,40 s | Inclui 29 anteriores de sintaxe/recovery; claims Auth sintéticas |
| Fundação 6.3 anterior | 35 passed PostgreSQL; 265 passed/23 skipped padrão | Histórico anterior à correção, não somar a 40 |
| Task/task Firewall opt-in | 21 passed | Local |
| Chromium UI | 10 passed | Local/fixture |
| Effectiveness V1/V2 | 2 passed por suíte no relatório 6.3 | Comparações sintéticas |
| Funcional declarativo | 17 observações esperadas coincidentes | 0 execuções funcionais reais |
| Benchmark tarefas | 30 observações esperadas coincidentes | Git/SQLite locais |
| Benchmark Task Firewall | 15 observações esperadas coincidentes | Sem bloqueio de merge exercitado |
| Live GitHub, checkpoint 6.3 | 265 passed, 18 skipped, 5 failed | Falhas em measurement, PR summary, web HTTP, workflow e workspace |

Não declarar os cinco testes GitHub corrigidos: indisponibilidade/acesso externos
foram apontados em fases anteriores, mas causa/solução atuais não foram novamente
validadas. Não desabilitar testes para obter sucesso. Contagens de checkpoints
anteriores diferem por novos testes e opt-ins; não misturar em um único resultado.

### Benchmark observado

A = aceitação simulada sem REIVRO; B = VERIFY; C = VERIFY + Firewall.
A não é comportamento real observado de cliente IA. V1 e V2 têm conjuntos e
repetições diferentes; não atribuir toda diferença de latência a otimização.

| Benchmark/modo | TP/FP/TN/FN | Positivos sem decisão | Mediana / p95 ms |
| --- | --- | ---: | --- |
| V1 B | 4/0/2/0 | 1 | 205,553 / 324,731 |
| V1 C | 3/0/2/0 | 2 | 1917,014 / 3337,317 |
| V2 B | 15/0/9/0 | 3 | 138,408 / 297,190 |
| V2 C | 15/0/9/0 | 3 | 1390,372 / 2543,133 |

Na V1, cobertura de detecção dos cinco positivos: B 80%, C 60%, incluindo
abstenções no denominador. A melhoria preserva achados independentes de VERIFY
mesmo com proteção adulterada/indisponível; o resultado operacional pode continuar
INCONCLUSIVE. Não chamar abstenções de sucessos nem esconder falhas de proteção.
V2 mantém esse desacoplamento; o Firewall continua adicionando latência local.

Task benchmark: 12 tarefas incompletas detectadas, 6 inconclusões, 6 violações de
escopo, FP=0/FN=0 no subconjunto binário; mediana 26,761 ms, p95 31,221 ms.
Task Firewall: 3 incompletudes, 3 violações, 3 reincidências confirmadas,
3 inconclusões, FP=0/FN=0 no subconjunto aplicável; mediana 81,677 ms,
p95 104,813 ms. Evidências completas e resultados adversos permanecem em
`benchmarks/**/reference*`, JSON/CSV/Markdown e manifests de cenários versionados.

Não há validação de eficácia comercial, horas economizadas ou produtividade real.
Nenhum benchmark acima comprova prevenção efetiva de merge.

Comandos de reprodução local (não executar testes contra staging):

```bash
python3 -m pytest -q
PYTHON=python3 bash scripts/test-control-plane.sh
PYTHON=python3 bash scripts/test-firewall-staging.sh
REIVRO_TASK_BENCHMARK_OUTPUT=/tmp/reivro-task-v1.json python3 -m pytest -q tests/test_scop_task_verification.py
REIVRO_TASK_FIREWALL_OUTPUT=/tmp/reivro-task-firewall.json python3 -m pytest -q tests/test_scop_task_firewall.py
node --test tests/ui/*.test.cjs
```

Ler scripts/READMEs e preparar dependências locais antes de executá-los. Harnesses
PostgreSQL usam Docker descartável sem rede; isso não demonstra isolamento geral
de código arbitrário nem requer usar credenciais de Supabase. Não presumir Docker
ou navegadores disponíveis na nova conversa.

## 9. Alpha, clientes reais e roadmap restante

CLI disponível: init, task approve, verify, review, protect, status, history,
authorize-correction, revoke, doctor, demo; relatórios humanos em inglês e JSON.
Instalação Linux limpa, launcher, remoção e demo foram exercitados no mesmo host.
Duas extrações Git não equivalem a duas máquinas. WSL e participante externo
permanecem não validados. Demo usa agentes/tarefas sintéticos e decisões roteirizadas.

Na missão 4.2, a sessão Codex ativa produziu commits sintéticos reais e VERIFY
verificou os bytes. O restante do ciclo de aprovação/reincidência/correção usou
fixtures em exercício separado. Isso não é o protocolo completo 6.2 validado.
Cliente instalado/autenticado não comprova entitlement para nova inferência sem
custo. Codex, Claude Code e Cursor não têm validação E2E completa certificada;
preservar status LOCAL ONLY/BLOCKED conforme disponibilidade real, sem inventar hooks.

Probes de dois UIDs em container negaram acessos a arquivos sintéticos; não
comprovaram contas host independentes ou proteção contra o próprio agente Cloud,
que tinha acesso Docker. Não repetir isso como substituto da fronteira real.
A fundação hospedada é a alternativa incremental a essa lacuna, mas não a fecha
sem JWTs, transporte e separação de credenciais comprovados.

Ordem do roadmap, sem expansão periférica:

1. **Provisionar o Agent e executar a matriz de tarefas com JWTs reais** conforme os gates acima.
2. **Demonstrar fronteira humana hospedada:** reviewer independente do processo do
   agente, proteção de credenciais e impossibilidade real de autoaprovação/revogação.
3. **Implementar incremento mínimo de transporte remoto**, em missão separada:
   CLI/API/worker estáticos reutilizando task_dispatch e Durable Execution,
   sem execução funcional, com reconciliação e tratamento de inconclusão.
   Não depender de computador sempre ligado; orçamento/hosting precisam ser resolvidos
   antes de ativação. Não confundir fundação SQL com produto remoto pronto.
4. **Executar protocolo Codex real** de docs/alpha/README.md, com entitlement
   confirmado pelo founder: incompletude → evidência → decisão humana → proteção →
   reincidência → correção autorizada → verificação → revogação → recuperação.
   Registrar sessões, SHAs/digests/eventos e decisões sanitizadas.
5. **Validar segunda máquina/participante:** instalação, integridade/atualização,
   permissões, remoção, recuperação e clareza dos relatórios. Resolver cinco testes
   GitHub ou documentar a causa externa com evidência reproduzível atual.
6. **Revisão de alpha:** restauração das novas decisões pós-003, isolamento real,
   incidentes/rollback, escopo suportado, custos/quotas e consentimento local de
   feedback. Aprovação do founder é separada; nunca liberar automaticamente.

Vercel Queues/Sandbox/Functions permanecem preservados para eventual ensaio
HTTPS → Queue → Worker → Sandbox → Cloud Memory, mas adiados. Plano SCOP, créditos,
gastos, quotas e disponibilidade efetiva não estão confirmados neste checkpoint.
Compatibilidade de duração da Function, lease/janela 60/120 s, três tentativas
Cloud Memory, cinco da fila e inicialização do Sandbox exige evidência antes de
ativar; evitar esgotar entregas durante lease ativo. Sem deploy para descobrir isso.

Execução funcional segura é trilha futura separada e bloqueada, não requisito
para afirmar que critérios estáticos funcionam. Não ampliar a alpha para código
arbitrário até comprovar executor e verificador independentes, sem rede/segredos,
com limites, integridade e destruição adequados.

## 10. Restrições e critérios de interrupção

- Orçamento adicional ZERO; nenhuma contratação, inferência paga separada ou recurso pago.
- Sem produção, deploy, merge em main, modificação Vercel existente/landing/ruleset,
  instalação de GitHub App, ativação de webhooks ou publicação de GitHub Checks.
- Não publicar pacotes, criar PRs remotos ou transmitir telemetria automaticamente.
- Sem executar código arbitrário/PR, desabilitar RLS, ampliar grants ou retirar
  isolamento para fazer teste passar. Não permitir agente decidir como reviewer.
- Sem credenciais, senhas, JWTs, backups, dados privados ou arquivos de evidência
  sensíveis em chat/Git/logs. Usar dados sintéticos e registrar IDs para limpeza.
- Sem reaplicar migrations ou reverter schema com
  DROP/destruição após novos dados. Preferir reconciliação e correção forward
  revisada; restore é operação independente com destino/versão conferidos.
- Parar em alvo incorreto, drift, hash/ACL/RLS divergente, timeout, resultado de
  commit incerto, falso VERIFIED, acesso cross-tenant ou escrita indevida.
  Preservar evidência, suspender operações dependentes e manter writers congelados.
- Não declarar mocks/fixtures como integração hospedada, segundo ambiente local
  como segunda máquina, relatório do founder como auditoria independente, ou
  detecção como prevenção efetiva.

## 11. Trabalhos locais e recuperação de contexto

No Cloud desta conversa há worktrees separados para as fases históricas. Não
apagar ou sobrescrever worktrees/branches existentes. O checkout
`/workspace/reivro-control` permaneceu em e280fa4, com arquivos **não commitados**:

- docs/RECOVERY_VALIDATION_6_4.md
- docs/STAGING_EXECUTION_6_4.md
- docs/CONTROL_PLANE_003_OPERATIONS.md
- ops/vercel-pilot/staging/control-plane-003.ps1 (kit anterior substituído)
- ops/vercel-pilot/staging/control-plane-003-local.ps1 (cópia do arquivo publicado)

Esses arquivos não devem ser presumidos presentes em um clone novo. O conteúdo
operacional relevante foi consolidado aqui e no guia publicado em e274c82;
não publicar automaticamente o kit substituído nem todo o workspace. Evidências
originais de backup/restauração estão só com o founder, não nestes worktrees.

Para a nova conversa, usar a branch deste handoff, ler o documento e confirmar
Git/estado operacional. Não reconstruir componentes já existentes. Antes de
trabalho futuro em outra branch, preservar o histórico e criar worktree a partir
da referência efetivamente aprovada; nenhum merge é necessário para ler este kit.

## 12. Retomada

> Retome pela branch docs/reivro-handoff-6-4. Ledger 001–003, dispatcher V3 e
> alias V1 confirmados por auditoria em staging somente leitura. Preserve a
> arquitetura, mantenha Private Alpha bloqueada e use o guia pós-003 para
> preparar a matriz de tarefas com identidades separadas. Auth e RLS legada foram
> aprovados conforme relato do founder. A fronteira de tarefas permanece pendente.
