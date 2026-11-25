# Task policies no Rework Firewall existente

A integração local parte de `3f03d05d8408d372f965ff3b254342f75e243556`. Foram revisados os três commits da missão anterior: expectativas `f86a140`, verificador `18a1fc4` e relatório `3f03d05`. O contrato de tarefa e o benchmark publicado foram mantidos.

O operador escolhe uma observação verificável de um relatório registrado, que é ligada por digest a projeto, contrato, tarefa e revisão. O comando `finding` cria um achado no mesmo journal SQLite do Firewall. Os comandos existentes `review`, `propose`, `decide` e `export` controlam confirmação explícita, aprovação, revogação e artefato. Somente o operador tem esse acesso. Ausência de confirmação impede proposta, e a verificação do agente não cria proteção automaticamente.

## Contrato reutilizável

A categoria `task-policy` usa `task-policy-v1`, o mesmo formato versionado de proteção, ID `p-` derivado do digest canônico, estados e o mesmo caminho de artefato do Firewall. Para o artefato de tarefa, `export` também retorna `artifact_sha256`, que vincula os bytes exportados. O verificador exige a correspondência byte a byte com o manifesto aprovado antes e depois de avaliar Git.

| Predicado reutilizável | Condição avaliada |
| --- | --- |
| `exists` | Arquivo regular obrigatório no HEAD |
| `blob_sha256` | Arquivo regular com conteúdo autorizado por digest |
| `protected_path` | Caminho exato não pode mudar entre BASE e HEAD |
| `allowed_paths` | Toda mudança rastreada deve pertencer ao conjunto aprovado |

Uma alteração de conteúdo requerida para uma tarefa, uma avaliação manual ou um run Cloud específico são critérios daquela tarefa. Eles não são promovidos automaticamente. Políticas de sintaxe continuam no caminho VERIFY existente. O caminho de sintaxe recusa aplicar um manifesto de política de tarefa. O funcional permanece desabilitado. O operador seleciona uma política por execução. Uma exigência de conteúdo contraditória ou uma mudança requerida em caminho vedado pela política é reportada como conflito. Não há linguagem de políticas adicional nem despacho de código.

A identidade da falha combina projeto, versão e predicado normalizado com o fingerprint do caminho violado. Reincidência exige um novo ID de tarefa e um novo HEAD, além de coincidência com a identidade da evidência original. O rótulo do agente não participa da identidade. Uma alteração em outro caminho pode violar a mesma allowlist e continua sendo uma falha nova. O journal correlaciona a evidência original, a proteção, cada resultado e a correção autorizada. Não há inferência semântica de similaridade.

## Experiência do operador

O relatório separa declaração do agente, estado da tarefa e estado da política. Inclui índices dos critérios, fingerprints de caminhos, BASE e HEAD observados, evidência, indicação de reincidência e próxima ação do operador. O contrato privado correlaciona índices com caminhos. Credenciais, objetivos livres e bytes dos arquivos não entram no relatório. Se a política estiver revogada, adulterada, em conflito ou sem evidência, um resultado de tarefa favorável por si só não vira sucesso final.

Com o contrato já aprovado e uma submissão de Agent Integration disponível:

```bash
python3 -m server.scop_task_verification --repository "$REPOSITORY" --store "$PRIVATE_STORE" \
  verify --checkout "$TRUSTED_CHECKOUT" --digest "$TASK_DIGEST" < submission.json

python3 -m server.scop_task_verification --repository "$REPOSITORY" --store "$PRIVATE_STORE" \
  finding --event-id "$EVENT_UUID" --criterion-index 0
```

Para uma violação de caminho, use `--violation-index` no lugar de `--criterion-index`. Depois o operador executa `scop_firewall review ID confirm --reason ...`, `propose ID`, `decide PROTECTION_ID approve --reason ...` e `export PROTECTION_ID --checkout CHECKOUT`, com as opções de repositório e journal. O checkout do artefato deve ser mantido pelo operador.

Na tarefa seguinte, acrescente `--protection "$PROTECTION_ID" --artifact-checkout "$ARTIFACT_CHECKOUT"` à verificação. Para autorizar correção de uma política violada, o operador usa `scop_agent_integration authorize-correction` com o JSON registrado. A nova verificação recebe `--after-correction "$VIOLATION_EVENT_UUID"`, a mesma proteção e um novo HEAD. Usa as autorizações com limite já existentes e grava o consumo no mesmo commit SQLite do resultado. O agente corrige somente com permissão. Para desativar, use `scop_firewall decide PROTECTION_ID revoke --reason ...`.

O finalizador revalida contrato e política sob a transação de escrita. Reentregas concorrentes podem ler evidências mais de uma vez, com no máximo um resultado persistido por evento. O relatório não declara sucesso quando um evento consumido é repetido. RLS, grants, dispatcher, leases, fencing e DRY RUN hospedados continuam nas implementações existentes, sem migration ou deploy. A política de tarefa não foi habilitada na Cloud Memory. O teste local não exerceu bloqueio de merge.

## Testes e benchmark

```bash
python3 -m pytest -q tests/test_scop_task_firewall.py
REIVRO_TASK_FIREWALL_OUTPUT=/tmp/reivro-task-firewall.json python3 -m pytest -q tests/test_scop_task_firewall.py
```

O manifesto de expectativas foi congelado antes da execução. São três repetições em repositórios Git e journals SQLite descartáveis. A latência mede verificação, não a aprovação humana nem a preparação do fixture. Os agentes são rótulos sintéticos. As métricas de falsos positivos e negativos se limitam às linhas com rótulo binário. Os resultados de escopo, recorrência e inconclusão são separados. Nenhuma prevenção efetiva foi medida.
