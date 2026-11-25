# Integração local com agentes

A interface `python3 -m server.scop_agent_integration` usa VERIFY v2 para comparar sintaxe Python em PRs públicos, o Firewall SQLite para persistir achados e executar uma proteção selecionada e `StagingMemory.read_run` para importar evidência já registrada. A integração funciona sem iniciar um cliente de IA e sem computação hospedada da REIVRO.

## Contrato JSON v1

O agente fornece uma referência de revisão. O operador confere a tarefa e escolhe a fonte de verificação fora do payload.

| Campo de entrada | Contrato |
| --- | --- |
| `version` | Inteiro 1 |
| `agent` | `codex`, `claude-code`, `cursor` ou `independent`. Rótulo declarado, sem prova de identidade |
| `project` | GitHub owner/repository, confirmado pelo argumento do operador |
| `task_id`, `event_id` | UUIDs canônicos. O primeiro correlaciona a tarefa e o segundo identifica a entrega |
| `pr`, `head_sha` | Número do PR público e SHA completo em minúsculas |

Campos extras e duplicados, entrada acima de 4 KiB e versões desconhecidas são erros. A requisição não aceita relatos livres, evidência, caminhos de arquivo, comandos, papéis ou decisões. O journal privado reserva o ID do evento antes da verificação. Uma repetição exata retorna `INCONCLUSIVE` com `duplicate_event`; uma repetição com conteúdo ou seleção de evidência diferente retorna erro. Um processo interrompido pode deixar uma reserva sem resultado. Nesse caso, o operador reconcilia o journal e usa um novo evento quando a reexecução for apropriada.

A resposta inclui a correlação de entrada, o resultado `status`, o resultado de sintaxe em `verifier_status`, os achados por ID, a proteção selecionada (quando houver) e a evidência da revisão. A revisão confirmada vem dos SHAs BASE e HEAD da análise e do PR canônico. Um HEAD divergente produz `INCONCLUSIVE` sem achado daquela submissão. O campo `modified_files` contém apenas os arquivos cobertos por VERIFY, com SHA-256 do caminho, estado e número de linha quando disponível. O operador pode correlacionar caminhos comparando seus hashes. Trechos, caminhos originais, diagnósticos, tokens e exceções de provedor ficam fora do relatório para agentes. O journal privado do Firewall mantém a evidência técnica para o revisor.

A proteção local só produz `violation` ou `checked` quando o Firewall confirma uma aprovação ativa e confere os bytes exportados. `inactive` ou `unconfirmed` indicam que a execução não confirmou aplicação. No modo Cloud, o identificador de proteção é histórico. A RPC de leitura não comprova seu estado atual. A CLI sai com 2 em regressão ou violação, 1 em erro, inconclusão, proteção inativa ou observação sem violação conclusiva, e 0 em submissão válida ou verificação conclusiva favorável.

## Adaptadores opt-in

| Cliente | Instalação local | Entrega de feedback |
| --- | --- | --- |
| Codex | Incorporar o trecho de `ops/agent-integration/AGENTS.md` ao `AGENTS.md` do projeto | Sob instrução do operador, gerar JSON pelo terminal. O operador devolve o resultado à sessão. [AGENTS.md no Codex](https://developers.openai.com/codex/guides/agents-md) |
| Claude Code | Incorporar `ops/agent-integration/CLAUDE.md` ao `CLAUDE.md` do projeto | Usar o terminal com as permissões do usuário e receber a resposta do operador no contexto da sessão. [Memória no Claude Code](https://code.claude.com/docs/en/memory) |
| Cursor | Instalar `ops/agent-integration/reivro.mdc` em `.cursor/rules/reivro.mdc` e invocar a regra quando necessário | Usar o terminal do Agent com a aprovação do operador e incluir o relatório explicitamente na sessão. [Regras do Cursor](https://cursor.com/docs/rules) · [Cursor CLI](https://cursor.com/docs/cli/using) |

Esses adaptadores usam instruções de projeto e uma CLI comum. A entrega é manual e opt-in. As instruções não são uma barreira de segurança, e uma sessão com acesso à conta do operador poderia usar suas permissões. Manter o checkout de ferramentas confiável, o armazenamento privado e as credenciais fora do ambiente acessível ao agente. Somente o operador executa `review` e a CLI de aprovação do Firewall em seu contexto de confiança. Nenhuma API de modelo, instalação automática, alteração de código, hook ou publicação de Checks faz parte deste fluxo.

## Reprodução

Do checkout confiável da REIVRO, com as variáveis de referência já definidas pelo operador:

```bash
python3 -m server.scop_agent_integration submit --agent independent \
  --project "$REPOSITORY" --task-id "$TASK_UUID" --event-id "$EVENT_UUID" \
  --pr "$PR_NUMBER" --head-sha "$HEAD_SHA" > request.json

python3 -m server.scop_firewall --repository "$REPOSITORY" --store "$PRIVATE_STORE" init
python3 -m server.scop_agent_integration review --repository "$REPOSITORY" \
  --store "$PRIVATE_STORE" --github-read < request.json
```

O operador pode inspecionar o achado com `scop_firewall show`, confirmar com `review`, propor com `propose`, aprovar com `decide` e exportar com `export`. Os comandos humanos existentes continuam separados do adaptador. Para verificar uma nova revisão com a proteção, gerar outro evento e repetir o segundo comando com `--protection "$PROTECTION_ID" --checkout "$TRUSTED_ARTIFACT_CHECKOUT"`. Devolver o JSON sanitizado ao agente para comunicar proteção e violação. O agente aguarda autorização antes de qualquer correção.

Para ler um run que já existe no staging, usar o filtro de repositório e run escolhido pelo operador. Carregar `REIVRO_PUBLISHABLE_KEY` e `REIVRO_AGENT_READER_JWT` de um viewer autorizado no contexto privado do operador:

```bash
REIVRO_STAGING_REF=lbklqqqbmeyseeccdqog python3 -m server.scop_agent_integration review \
  --repository "$REPOSITORY" --store "$PRIVATE_STORE" \
  --repository-id "$REPOSITORY_ID" --cloud-run "$RUN_UUID" < request.json
```

Esse modo só lê. O harness local verifica o contrato de transporte com fixtures e não pressupõe JWT real disponível.

```bash
python -m pytest -q tests/test_scop_agent_integration.py tests/test_scop_firewall.py
PYTHON=python3 bash scripts/test-firewall-staging.sh
```

O teste de integração local percorre submissão sintética, blobs e patch GitHub de fixture, compilador isolado real, revisão humana simulada pelas operações do Firewall, artefato aprovado, nova regressão, alteração do artefato e revogação. O harness PostgreSQL valida o núcleo Durable Execution separadamente. O binário Codex local foi identificado e sua ajuda consultada sem rodar inferência. Claude Code e Cursor não estavam disponíveis como CLIs nesta sessão. Os três adaptadores estão em nível LOCAL ONLY. Nenhuma sessão real de agente foi exercitada.

Próxima missão: rodar um teste opt-in com uma sessão real por cliente já disponível, um PR de teste autorizado e um operador separado, comparando o JSON com HEAD e evidência verificados e observando a reação a uma violação. Nenhuma assinatura nova é necessária para continuar os testes locais.
