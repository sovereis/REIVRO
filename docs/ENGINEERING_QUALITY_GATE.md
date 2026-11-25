# Quality gate do núcleo

Base revisada: `314f9277a652c9eee7dd1be02ea37fe867b44428`.

| Severidade | Evidência e impacto | Tratamento |
| --- | --- | --- |
| Alta se Checks forem obrigatórios | GitHub pode aceitar conclusão neutral em uma regra de status obrigatório. Uma falha de verificação ou de integridade de proteção resultava em INCONCLUSIVE neutral no caminho legado. | Decisão de revisão explícita no worker. A tradução de Check usa action_required para essa decisão. Reconciliation compara a conclusão efetivamente solicitada. Exercitado com cliente de fixture. |
| Média | `_inspect` retornava antes de VERIFY quando o artefato aprovado faltava ou divergia. O V1 perdeu uma detecção nesse caso. | Verificação da revisão continua independentemente, preservando achados confirmados. O digest entregue ao banco continua nulo se a proteção falhar. O dispatcher mantém INCONCLUSIVE para uma conclusão sem digest válido e revalida revogação. |
| Média | O compilador restringe execução do verificador de sintaxe, mas não há evidência de executor apto para código arbitrário de PR, plugins e dependências. | [Regra funcional bloqueada](FUNCTIONAL_REGRESSION.md). Contrato e fixtures sem execução. |
| Média | A integração pública GitHub e os provedores Vercel não foram verificados nesta instância. A varredura externa Python também depende de acesso a uma base de avisos. | Manter teste opt-in e resultados negativos. `pip check` passou, o acesso a OSV e GitHub recebeu 403 no túnel. `npm audit` reportou zero vulnerabilidades no lockfile de testes UI. Esse resultado tem escopo próprio. |
| Baixa | SQLite de operação e Cloud Memory armazenam decisões por contratos diferentes. Há sobreposição de regra e verificações de repositório, mas seus papéis, clocks, persistência e mecanismos de autorização divergem. | Reusar VERIFY e o dispatcher, sem unificar os armazenamentos nem retirar validações independentes. O agente consulta runs com sessão de leitura e não ganha autoridade de reviewer. |
| Baixa | O harness abre Docker/psql para cada RPC. O custo do subprocesso mistura-se ao custo do banco no V1. | V2 registra DB, execução de VERIFY e journal separadamente. O perfil é de ambiente local, sem transporte HTTP real. |

## Fronteiras preservadas

A revisão pública é revalidada pelo worker e pelo verificador. A leitura de fonte verifica blob, revisão e alinhamento do diff. A autorização de proteção exige o manifesto da BASE com o digest aprovado. Um achado independente não ativa a proteção. O resultado do worker separa a observação do verificador, a evidência sobre o artefato, a decisão de segurança e o estado operacional. PASS só é aceito quando o banco o reconhece e a análise tem digest e resultado coerentes. Runs sem proteção permanecem observações. Uma mudança de HEAD durante a verificação invalida a evidência. Uma falha transitória do provedor de artefato continua recuperável quando não há regressão verificada a preservar.

A modificação não altera a migration, a ordem de locks, o lease nem o fencing. O worker ainda só conclui na posse válida e a transação de finish persiste achados e auditoria. O PostgreSQL descartável cobre claim concorrente, revogação entre análise e finish e retomada. O modo DRY RUN segue no cliente GitHub somente leitura. A CLI local de proteção mantém sua rejeição antecipada de artefato inválido. Um operador pode executar VERIFY independente pelo comando analyze.

Referência para conclusões aceitas pelo gate: [GitHub Docs](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks).
