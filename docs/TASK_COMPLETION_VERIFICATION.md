# Task Completion Verification V1

A evidência estática é obtida de objetos em um checkout Git confiável escolhido pelo operador. A entrada do agente usa Agent Integration V1 e é uma declaração alegada de conclusão identificada por tarefa, evento, projeto e HEAD. O verificador nunca executa os arquivos avaliados. O PR é um campo de correlação da entrada existente. Esta regra local não consulta GitHub para comprovar a existência do PR.

## Contrato e autorização

O operador define o contrato antes da execução e faz `approve` quando o checkout confiável ainda está na BASE. O journal SQLite privado existente do Rework Firewall registra o contrato e seu digest canônico. A CLI verifica o digest fornecido pelo operador novamente antes e depois de obter evidências. Alterações ao contrato exigem uma nova tarefa e aprovação. O operador pode revogar a aprovação no journal. O agente não deve ter acesso ao usuário, journal ou ambiente de credenciais do operador.

```json
{
  "version": 1,
  "task_id": "00000000-0000-4000-8000-000000000001",
  "project": "example/task",
  "base_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "objective": "Update the required file and provide the agreed evidence",
  "allowed_paths": ["required.py", "evidence.txt"],
  "protected_paths": ["protected.txt"],
  "criteria": [
    {"kind": "exists", "path": "required.py"},
    {"kind": "changed", "path": "required.py"},
    {"kind": "blob_sha256", "path": "evidence.txt", "digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
  ]
}
```

Escopo usa caminhos exatos e distingue maiúsculas. Inspeciona todas as mudanças rastreadas entre BASE e HEAD com Git plumbing. Renomes aparecem como remoção e adição. `exists` exige arquivo regular no HEAD. `changed` exige novo conteúdo ou arquivo novo regular. `blob_sha256` exige bytes do blob aprovado. Links simbólicos, árvores e submódulos não satisfazem critérios de arquivo. `manual` marca um critério sem evidência verificável nesta versão. Nenhum arquivo não commitado entra na avaliação.

Opcionalmente, o operador fixa um run preexistente de Cloud Memory por `{"kind":"cloud_run","repository_id":123,"run_id":"UUID","outcome":"PASS"}`. A leitura aceita apenas o staging autorizado e um JWT de leitor. O run deve corresponder ao ID, projeto, BASE, HEAD e estado aprovados e conter verificação PASS. Um run OBSERVED só satisfaz um critério explicitamente fixado como OBSERVED e com verificador PASS. Um run indisponível ou invisível é inconclusivo. Nenhuma RPC administrativa ou de escrita é usada. A fronteira de transporte do teste simula somente o provedor. Nenhum JWT real foi exercitado nesta missão.

O relatório separa `agent_declaration` dos critérios observados. Contém SHAs, digest do contrato, resultado por índice de critério, fingerprints de caminhos violados e ID canônico de evidência. Objetivo, caminhos originais, bytes, diagnósticos externos e credenciais ficam fora da resposta. As leituras Git bloqueiam protocolos remotos, substituição de objetos, diff externo e textconv, com prazo e saída limitados por comando. O checkout deve ser controlado pelo operador. Esta interface não tenta verificar segurança do próprio banco SQLite sob um adversário com a mesma conta.

## Resultados e efeito no Firewall

POLICY_VIOLATION se houver alteração protegida ou fora de escopo. INCOMPLETE se um critério verificável falhar. INCONCLUSIVE para HEAD divergente, ancestralidade incerta, critério manual, evidência inacessível ou evento já consumido. ERROR para contrato inválido ou evidência Git indisponível. VERIFIED significa exclusivamente os critérios estáticos aprovados para os commits observados. Cada evento grava no máximo um resultado. A revogação concorrente impede sua gravação. Um evento repetido não devolve verificação favorável em cache.

Um resultado persistido de não conformidade contém o pacote de evidência para futura revisão humana. A reincidência do mesmo critério foi exercitada em outro HEAD e a revogação da autorização local bloqueia novas verificações da tarefa. A promoção para proteção de Firewall permanece bloqueada: é necessário validar um contrato autorizado de persistência no dispatcher, versão/digest do artefato, aprovação e revogação sob fencing. O fluxo de sintaxe e o comparador funcional existente continuam separados. Não há regra de tarefa habilitada no dispatcher nem bloqueio de merge exercitado.

## Reprodução

Preparar o contrato e a submissão de Agent Integration v1 em arquivos distintos. Os comandos abaixo são executados no checkout confiável da REIVRO, em contexto do operador. Usar `scop_firewall init` apenas se o armazenamento ainda não existir.

```bash
python3 -m server.scop_firewall --repository "$REPOSITORY" --store "$PRIVATE_STORE" init
python3 -m server.scop_task_verification --repository "$REPOSITORY" --store "$PRIVATE_STORE" approve --checkout "$TRUSTED_CHECKOUT" < contract.json
python3 -m server.scop_task_verification --repository "$REPOSITORY" --store "$PRIVATE_STORE" verify --checkout "$TRUSTED_CHECKOUT" --digest "$APPROVED_DIGEST" < submission.json

REIVRO_TASK_BENCHMARK_OUTPUT=/tmp/reivro-task-v1.json python3 -m pytest -q tests/test_scop_task_verification.py
```

O benchmark executa três repetições em novos repositórios descartáveis e compara cada linha ao manifesto fixado. A latência mede a avaliação depois da preparação; inclui Git e journal locais. Falsos positivos e negativos usam apenas fixtures com rótulo binário. Inconclusivos, erros e violações de escopo estão no relatório integral. Nenhuma conclusão semântica ou funcional é inferida.
