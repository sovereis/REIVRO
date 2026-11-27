# Checkpoint Auth e próximo gate do Control Plane

27/11/2026, America/Sao_Paulo. Staging `lbklqqqbmeyseeccdqog`. **Private Alpha bloqueada.**

O founder reportou PASS em login, Auth e RLS legada no Windows para reviewer A, reviewer B, viewer A, worker A e a conta sem vínculo. Reportou também a redefinição das cinco senhas. A evidência de Auth e RLS reais é operacional e foi reportada pelo founder.

A auditoria administrativa independente, em transação somente leitura, confirmou os cinco UUIDs correspondentes aos papéis anteriores. São cinco contas confirmadas com senha configurada, quatro memberships idênticas à linha de base anterior (dois reviewers, um viewer, um worker) e uma conta sem vínculo. Seis hashes das tabelas de aplicação, sequência 12/true, ledger 001–003, ACLs, RLS e fingerprints no escopo do guard pós-003 foram conferidos. As tabelas de tarefas e leases continuam vazias.

SHA256 do inventário sanitizado do Auth: `5427ee4bafee7ae297c834518f5780043b974d57a57c91bdb9843fb606350c8c`. A projeção usa UUID, papel de teste e indicadores de confirmação, presença de senha, anonimato e bloqueio. O digest histórico integral de `auth.users` pertence ao checkpoint anterior às redefinições. A consulta atual reproduz o novo checkpoint e interrompe se a linha de base mudar. [SQL somente leitura](audit_post_jwt_read_only.sql)

[Comandos Windows para backup, ensaio de restauração e Agent A](WINDOWS_CONTROL_PLANE_GATE.md)

## Ordem de execução após autorização

1. Reconfirme escopo sintético A/B, suspensão de writers, backup recuperável que cubra o estado pós-redefinição e separação do terminal dos reviewers. Execute `audit_post_jwt_read_only.sql` antes da primeira nova escrita. Confirme com o founder as ações e o escopo autorizados.
2. Crie a conta Auth sintética dedicada de Agent A. Execute `provision_staging_agent.sql` com o novo UUID, janela autorizada e repositório A. Confirme que o usuário tem exatamente uma associação `agent` no projeto A, que a conta sem vínculo continua separada e que os quatro vínculos anteriores foram preservados. Faça login normal no contexto do Agent A. [Comandos Windows](WINDOWS_CONTROL_PLANE_GATE.md#agent-a-após-autorização-específica)
3. Use o planejador somente leitura para gerar os IDs e o digest do contrato com commits Git sintéticos fixados. Sob autorização para a fixture, reviewer A aprova o contrato em seu contexto próprio e Agent A submete no seu. Inspecione contrato, submissão e eventos antes de avançar. Para os controles de propriedade em A e a leitura positiva de tarefa em B, confirme escopo separado para os agents sintéticos adicionais descritos no guia. [Plano e inspeção das fixtures](WINDOWS_STAGING_JWT.md#plano-somente-leitura-e-criação-autorizada-da-fixture)
4. Exercite a matriz pelos JWTs reais com fixtures isoladas. Comece pelas leituras positivas/negativas, prossiga para claim, renew, fail e finish, decisão humana e proteção, e depois para reentrega, leases/fencing, revogação concorrente e remoção de membership com JWT ainda válido. Reserve uma fixture nova por cenário destrutivo de teste e reconcilie efeitos e eventos antes do ACK. [Matriz e critérios](POST_003_VALIDATION.md#matriz-do-control-plane)

Registre somente revisão, papel, cenário, resultado e referências sanitizadas. Em acesso indevido, divergência de baseline ou resultado incerto, pare e reconcilie por leitura. A autorização para redefinir senhas não cobre a criação de contas, memberships ou fixtures desta fase. Liberação da alpha depende de decisão separada após a validação da fronteira humana e operacional.
