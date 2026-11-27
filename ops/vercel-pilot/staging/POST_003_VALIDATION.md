# Validação de staging após a 003

**Private Alpha bloqueada. Auth e RLS legada com cinco JWTs reais aprovados conforme relato do founder. A fronteira de tarefas ainda está pendente.**

## Auditoria administrativa

A leitura independente pelo Supabase, no projeto `lbklqqqbmeyseeccdqog`, passou em transação somente leitura. Confirmou os sete fingerprints de funções do kit, owners, SECURITY DEFINER e search_path, ACLs e RLS no escopo do guard, índices/FK de identidade de execução, ausência de leases e tarefas, integridade dos registros 001–003 e igualdade dos sete hashes da linha de base anterior à 003. A sequência permaneceu em 12/true. A contagem de memberships foi de dois reviewers, um viewer e um worker, sem agent. A execução do Postcheck003 pelo founder é um registro separado. Freeze operacional, frescor da cópia de recuperação e exposição efetiva pelo gateway dependem de confirmação própria.

Para reproduzir o checkpoint atual, use o Session Pooler de staging descrito no HANDOFF com SSL verify-full. O SQL abaixo confere o inventário sanitizado pós-redefinição e a linha de base das tabelas de aplicação. Execute antes de provisionar Agent ou fixtures. [Checkpoint e ordem operacional](CONTROL_PLANE_OPERATIONAL_GATE.md)

```bash
psql -X -W -v ON_ERROR_STOP=1 \
  "host=aws-1-us-west-1.pooler.supabase.com port=5432 user=postgres.lbklqqqbmeyseeccdqog dbname=postgres sslmode=verify-full" \
  -f ops/vercel-pilot/staging/audit_post_jwt_read_only.sql
```

## JWT real e RLS legada

Para Windows PowerShell 5.1 ou PowerShell 7, use os [comandos para as cinco identidades e o provisionamento controlado](WINDOWS_STAGING_JWT.md).

Use Python 3 e duas fixtures sintéticas legadas, uma por projeto. Confirme com o operador os dois pares repositório/run, as associações e os UUIDs das identidades por canal privado. Execute primeiro reviewer A e reviewer B para estabelecer que os dois runs existem e são visíveis no escopo legítimo. Sem esses controles positivos, os retornos nulos dos outros sujeitos são inconclusivos.

Cada operador obtém seu access token pela sessão Auth normal e usa uma execução própria, com chave publicável `sb_publishable_…` do staging. O script recebe credenciais por prompt oculto e fixa o domínio de staging. O processo do agente deve ficar isolado do terminal, perfil, arquivos e credenciais do reviewer.

```bash
python3 ops/vercel-pilot/staging/check_staging_jwt.py reviewer-a \
  --user-id UUID_DO_REVIEWER_A --repo-a ID_A --run-a UUID_RUN_A \
  --repo-b ID_B --run-b UUID_RUN_B
```

Repita para `reviewer-b`, `viewer-a`, `worker-a` e `sem-vinculo`, cada qual com UUID próprio. `agent-a` fica pendente de provisionamento autorizado e associação real. A matriz legada espera A para reviewer/viewer A, B para reviewer B e JSON nulo nos demais acessos. O script valida a identidade em `GET /auth/v1/user` e faz somente a RPC estável `read_run` via POST. HTTP inesperado, corpo incompatível ou UUID divergente produzem FAIL e saída 1. O relatório imprime apenas o papel, a etapa e o resultado. Registre revisões, respostas sanitizadas e lacunas. Preserve tokens, IDs privados e corpos fora do Git e do chat.

## Matriz do control plane

A linha de base está sem submissões e sem membership agent. A leitura de tarefas adquire `FOR SHARE` e `FOR UPDATE` na 003. Reserve toda chamada de `task_dispatch` para a fase autorizada em staging com fixtures, inclusive o caminho `read`. Use o mesmo projeto e Auth apenas se o freeze, o backup atual e a autorização para as alterações sintéticas forem confirmados. Mantenha seis sujeitos distintos conforme o HANDOFF.

| Exercício | Evidência esperada |
| --- | --- |
| Reviewer A e B aprovam nos projetos próprios | Versão e digest vinculados, negação entre projetos |
| Agent A submete e relê a própria tarefa | Leitura alheia e decisões humanas negadas, replay conflitante e HEAD divergente rejeitados |
| Viewer A lê tarefa A e reviewer B lê tarefa B | Escrita do viewer, acesso cruzado e operações do sujeito sem vínculo negados |
| Worker A faz claim, renew, fail e finish | Posse obrigatória, fence expirado sem efeito, decisões humanas negadas |
| Reviewer confirma, aprova/revoga e autoriza correção | Revogação e remoção de membership efetivas com JWT ainda válido |
| Reentrega concorrente e revogação durante execução | Efeito único, policy_set alterado gera INCONCLUSIVE, ACK após reconciliação e sintaxe legada preservada |
| Escrita direta nas tabelas | Bloqueada para papéis cliente |

Use controles positivos para cada fixture antes de interpretar negações. Compare estado persistido após cada transição e preserve IDs em registro privado para revisão da limpeza. Interrompa em acesso cruzado, efeito fora do escopo, drift ou resultado incerto. O aceite operacional exige a matriz real completa e evidência da independência do reviewer. A liberação da alpha é decisão separada.
