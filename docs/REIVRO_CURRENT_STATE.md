# Estado atual da REIVRO

**Veredito da auditoria: BASE CONSOLIDADA para a próxima implementação.** A base do piloto é reproduzível localmente. A operação hospedada do receptor, da fila e do worker ainda precisa ser demonstrada.

## Referências verificadas no GitHub

| Referência | HEAD observado |
| --- | --- |
| `sovereis/REIVRO:main` e HEAD padrão | `77f6cccf3482e5e440e9c2d148715844b5fc4a80` |
| `feat/reivro-integrated-core` | `2d847e2abada78d73e417301e3abcd7f7b7891b5` |
| `feat/reivro-github-pilot` | `4fe019ff4e96f6976fa554362e57c02aabd68ece` |
| `feat/reivro-github-pilot-infra` | `d0899647f83a0a9275bda021bb7943b76e2f1957` |
| `feat/landing-page-v01` | `92290d47b4d43746438e70678f7c25b5e4d5df7c` |
| `sovereis/reivro-firewall-demo:main` | `f4915e9c8d44dc7b5d918045d2ae4cdb85114ac9` |

Use **`feat/reivro-github-pilot-infra`** como única base de implementação. Ela contém integralmente o núcleo integrado (três commits adiante) e a primeira branch do piloto (dois commits adiante). A landing diverge da base comum `cae5ffaccc1a14bca8c77e21c7e59484ce18062f`, com um commit exclusivo de copy e testes e quatro commits exclusivos no piloto. O helper HTTP de testes tem conteúdo equivalente nas duas linhas. O restante do delta da landing cobre documentação, copy pública e asserções de navegador. Esta auditoria foi isolada em `docs/reivro-current-state`.

## Matriz de componentes

| Componente | Implementação e evidência | Última referência relevante |
| --- | --- | --- |
| VERIFY | `server/scop_verify.py` verifica whitespace em PR público. `server/scop_verify_syntax.py` compara BASE e HEAD por SHA e usa `_syntax_worker.py` para compilação limitada em Linux/CPython/libseccomp. Há injeção de executor. | Piloto infra `d089964` para a interface e `28ebe84` para VERIFY v2 |
| LEARN | `scop_firewall.py` e `scop_firewall_memory.py` registram achados, decisões humanas e artefatos em SQLite. A Cloud Memory tem transições equivalentes de confirmação, rejeição e proposta. | Ancestral das duas linhas `49ebb4d`; SQL do piloto `4fe019f` |
| PREVENT | Aprovação por digest, manifesto no caminho fixo da BASE confiável e revogação reavaliada antes da finalização. A cobertura implementada é regressão sintática em Python existente. | Local `49ebb4d`; piloto infra `d089964` e SQL `4fe019f` |
| Cloud Memory | `supabase/staging/001_firewall.sql` e `StagingMemory` em `scop_firewall_checks.py`. Projetos, memberships, runs, findings, protections e events. RPCs `dispatch` e `read_run`, escopo por JWT e RLS. | Piloto `4fe019f`; cliente presente em `d089964` |
| Webhook | `accept_delivery` valida corpo bruto, assinatura e escopo antes de persistir. O handler HTTP local aceita em loopback, aplica limite de corpo e confirma após gravação. Há configuração Caddy e systemd para um ensaio em VM. | Piloto infra `770ee48` e `d089964` |
| Fila | Protocolo `DeliveryQueue` e SQLite WAL. Deduplicação por entrega, claim atômica, retenção e recuperação de running como review. A memória também deduplica revisões. | Piloto infra `d089964` |
| Worker e Checks | `process` usa `analyze`, repete validação, lê evidência GitHub, verifica com executor, persiste claim/finish e finaliza a fila. `publish_result` e a CLI legada ficam fora do ensaio. `reconcile_publication` compara candidatos fornecidos pelo operador. | Piloto infra `d089964` |
| Vercel ASGI, Queues, Sandbox | Procura nas árvores das referências remotas e nos worktrees encontrou apenas a proposta em `ops/firewall-pilot/README.md`. As fronteiras são `accept_delivery`, `DeliveryQueue` e o parâmetro `executor`. A configuração Vercel existente pertence à landing. | Proposta e interfaces em `d089964` |

O fluxo é ingresso → fila durável → análise com evidência em revisão fixa → claim/finish e auditoria no staging. O reviewer autoriza proteções por digest. O compilador recebe fonte limitada, sem executar código ou workflows do PR. SQLite de fila e SQLite de memória local têm responsabilidades distintas. Há sobreposição intencional da regra e da revisão humana entre Firewall local e Cloud Memory, com contratos de persistência diferentes. Reutilizar `analyze`, `StagingMemory` e o contrato de compilação evita uma terceira implementação. Os caminhos HTTP do piloto e da landing atendem propósitos diferentes.

## Recursos verificáveis e evidência anterior

- A Vercel informou o projeto existente `reivro`, domínio `reivrotools.vercel.app` associado e deployment `dpl_Ho37WsmbxaFXkyjTt26XgcAWtJCK` em Production READY. O deployment é da landing.
- O HEAD do demo foi consultado no GitHub. A proteção ativa de `main` foi informada pelo solicitante. Os detalhes das regras não foram reinspecionados.
- [Registro do piloto](FIREWALL_GITHUB_PILOT.md) documenta uma rodada anterior com cinco logins reais, dois projetos, RLS, separação de papéis, isolamento, aprovação/revogação, concorrência e 12 eventos atribuídos. A evidência é histórica, com respostas GitHub de fixture. A condição atual das fixtures e do manifesto privado não foi confirmada.
- Na instância Cloud atual, a rede restrita exclui o host de staging e `api.github.com`, e o status lista zero vínculos de segredos. Nenhum piloto hospedado de webhook, fila, worker, ASGI, Queues ou Sandbox foi validado nesta rodada.

## Worktrees e preservação

| Worktree anterior | HEAD | Estado antes da auditoria |
| --- | --- | --- |
| `/workspace/REIVRO` | `77f6ccf` em `work` | Limpo, conteúdo alcançável em `origin/main` |
| `/workspace/reivro-integrated` | `2d847e2` | Limpo, coincide com remoto |
| `/workspace/reivro-landing` | `92290d4` | Limpo, coincide com remoto |

O status incluiu arquivos não rastreados. A comparação de commits locais e reflogs com as referências remotas atualizadas não mostrou commits exclusivos. As buscas por nome no workspace não localizaram implementações locais adicionais nem um manifesto de fixtures. Artefatos ignorados de dependências e build não fazem parte da auditoria de código. A revisão de padrões de credenciais nas cinco árvores relevantes não acusou chaves, JWTs ou tokens, e nenhum valor de credencial foi exibido.

## Testes e lacunas

| Execução em `d089964` | Resultado |
| --- | --- |
| `python -m pytest -q -rs` | 189 passaram, 7 pulados. Dois casos de PostgreSQL exigem o harness. Cinco casos dependem de GitHub público opt-in. |
| `bash scripts/test-firewall-staging.sh` | 22 passaram em PostgreSQL 17 descartável, com Auth simulada e transporte GitHub de fixture. |
| `node --test tests/ui/*.test.cjs` | 10 passaram em Chromium do sistema, incluindo landing, Workspace e bootstrap Vercel locais. |

Dependências do ensaio local incluem CPython, libseccomp, SQLite com RETURNING e Docker para o harness. A opção VM exige validação real de Caddy, TLS, DNS, permissões, restart, backup/restauração e rotação dos tokens. A fila de disco único precisa de reconciliação após interrupção entre claim e finish. Configurações de produção, credenciais e App são fronteiras operacionais próprias. O comportamento de ACK e redelivery de Queues, isolamento e limites do Sandbox, entrega GitHub real e recuperação hospedada continuam pendentes. A existência do demo e a evidência histórica de Auth não validam essas fronteiras.

## Única próxima tarefa de implementação

Implementar o adaptador de ingresso **ASGI** na base `feat/reivro-github-pilot-infra`, exercitado localmente com uma implementação injetada de `DeliveryQueue`. Reutilizar `accept_delivery` com os bytes originais, limitar corpo e preservar cabeçalhos necessários. Aceite: entrega válida recebe 202 somente após confirmação durável, assinatura ou escopo inválidos ficam fora da fila, indisponibilidade da fila gera resposta de erro e redelivery mantém deduplicação. Usar fixtures sintéticas e testes ASGI. A tarefa termina na fronteira da fila, sem provisionamento ou publicação de Checks.
