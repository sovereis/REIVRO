# REIVRO Firewall no Vercel — DRY RUN

Configuração para um futuro projeto independente chamado `reivro-firewall-pilot`. A base é `feat/reivro-github-pilot-infra` em `d0899647f83a0a9275bda021bb7943b76e2f1957`. A auditoria `536bb4e` acrescentou apenas documentação. O projeto `reivro` da landing fica fora deste pacote.

## Contrato de aplicação

- `POST /webhooks/github` recebe no máximo 512 KiB em bytes originais. Valida HMAC antes do JSON, UUID de entrega, ação, instalação, repositório, base e SHAs. Só responde 202 depois da confirmação da fila ou de duplicidade reconhecida pelo SDK. Falha ou confirmação ausente resulta em 503.
- A fila usa o SDK Python com idempotência por entrega. O segundo controle é a unicidade por revisão na Cloud Memory. O `pyproject.toml` registra um consumidor privado gerado pelo builder Python, sem rota HTTP pública de consumo. Retorno normal confirma a entrega. Falha propagada solicita retry com intervalo inicial de 30 s. O limite de tentativas de análise é persistido no banco, independente da contagem de entregas do provedor.
- O consumidor reautentica os bytes, confirma a revisão no GitHub e chama `analyze` com `StagingMemory` e `GitHubEvidence`. O worker exige `REIVRO_MODE=dry-run`, ref `lbklqqqbmeyseeccdqog`, demo `sovereis/reivro-firewall-demo` e base `main`. Seu fluxo só tem o cliente GitHub de leitura e não chama a API de Checks. A credencial GitHub desse projeto deve ter apenas Metadata, Contents e Pull requests em leitura.
- O adaptador Sandbox abre uma VM efêmera por fonte, com 1 vCPU, política deny-all, sem portas e sem segredos de aplicação. Exige confirmação da política na sessão ativa antes de transferir fonte. O comando fixo limpa o ambiente e executa o compilador existente, que ativa libseccomp, limita CPU, memória e saída e apenas compila bytes. O comando tem até 2 s e a VM até 10 s, subordinados ao prazo de VERIFY. Qualquer falha de isolamento encerra a verificação em ERROR, inclusive após um achado parcial. A versão efetiva do compilador é registrada e deve permanecer constante durante o run. O SDK gerencia a limpeza da VM e o prazo da sessão limita sua vida se a limpeza falhar.
- Logs da aplicação usam mensagens fixas, exceto UUID e estado em casos para revisão. Manter debug de SDKs, dump de headers e logging de corpos desligados. A Queue retém payloads assinados durante a retenção do serviço, por padrão 24 h. Usar apenas PRs públicos e sintéticos do demo.

## Preparar uma árvore local do candidato

Montar em diretório vazio a partir do SHA revisado. Copiar para a raiz desse diretório `app.py`, `worker.py`, `pyproject.toml`, `requirements.txt`, `.python-version` e `vercel.json` deste diretório. Copiar também `server/` preservando o caminho e `tests/pr-source-summary/validate.py` no mesmo caminho relativo, pois o núcleo usa o validador de evidência via `runpy`. Usar apenas arquivos versionados e o mínimo de fonte necessário. Excluir a landing, arquivos de ambiente, fixtures privadas, banco e caches. A configuração desativa deploy automático por Git.

Configuração futura da Function, apenas via cofre/settings:

| Variável | Origem |
| --- | --- |
| `REIVRO_MODE` | Literal `dry-run` |
| `REIVRO_STAGING_REF` | Literal `lbklqqqbmeyseeccdqog` |
| `REIVRO_REPOSITORY_ID`, `REIVRO_INSTALLATION_ID` | IDs do demo e da instalação autorizada, conferidos antes do ensaio |
| `REIVRO_WEBHOOK_SECRET` | Segredo dedicado de pelo menos 32 bytes, configurado no ingresso e no consumidor |
| `REIVRO_PUBLISHABLE_KEY`, `REIVRO_WORKER_JWT` | Chave publicável e JWT real do papel worker, com prazo e rotação |
| `REIVRO_GITHUB_INSTALLATION_TOKEN` | Token efêmero com escopo no demo e permissões somente leitura |
| OIDC Vercel | Identidade do projeto independente para SDKs. Permanece na Function. |

## Recuperação e condição para ensaio

### Causa e migração

Em v1 `runs` era gravado no claim, e `outcome` ficava nulo até finish. O `INSERT ... ON CONFLICT DO NOTHING` retornava `duplicate:true` para a revisão interrompida e para a concluída. O consumidor tratava as duas como sucesso de transporte. A migração incremental `supabase/staging/002_durable_execution.sql` mantém as chaves de entrega e revisão, IDs, achados, histórico e as RPCs públicas da v1. Encapsula o dispatcher anterior e remove acesso direto a ele. A tabela privada de leases tem RLS e não expõe grants aos clientes. A migração foi aplicada apenas no PostgreSQL descartável.

| Estado persistido | Transição e efeito |
| --- | --- |
| `pending` | Reserva opcional via `reserve_durable`. O claim normal cria a reserva e adquire a posse na mesma transação. Runs legados sem outcome são adotados sob o mesmo ID. |
| `running` | Claim atômico gera UUID de tentativa e incrementa `fence`. Outra entrega recebe `busy` enquanto a posse está ativa. |
| `retryable` | Falha explícita fecha a tentativa e libera a posse para reentrega. Após crash, uma posse expirada pode ser retomada diretamente. |
| `completed` | Finish com posse válida grava resultado, achados e eventos atomicamente. A reentrega retorna o estado persistido sem repetir a análise. |
| `terminal` | Na terceira falha explícita, ou numa reentrega após a terceira posse expirar, grava `ERROR` e evento de auditoria. Runs legados concluídos com `ERROR` entram nessa categoria histórica. |

A posse inicial é de 60 s no relógio do PostgreSQL. A renovação exige identidade do worker, UUID, fencing e lease ainda vigente. Cada renovação concede até 60 s, limitada a 120 s desde o claim inicial. O consumidor renova antes da verificação. Adotar um run expirado substitui o worker da execução e incrementa o fencing. Mesmo com o mesmo JWT, um processo anterior não consegue renovar, falhar ou completar com a posse antiga. A autorização valida membership, projeto, instalação e base, usando a ordem de locks já usada para review e revogação. Finish legado continua disponível para runs sem lease. O dispatcher anterior é reutilizado no finish para preservar validação de revisão, evidência e revogação.

### ACK, falha de rede e reconciliação

Para entregas válidas, o consumidor retorna ao SDK somente com conclusão ou estado terminal persistido e confirmado. Mensagem inválida é rejeitada sem criar execução. `busy`, `retryable`, resposta RPC inválida e transporte indisponível propagam erro para reentrega. Uma resposta de claim perdida aguarda a expiração. Uma resposta de finish perdida é reconciliada pelo próximo claim, sem repetir a verificação. O fluxo tem entrega ao menos uma vez com efeitos persistidos idempotentes.

Se o provedor expirar a mensagem ou a indisponibilidade durar mais que a retenção, reconcile por projeto, ID da entrega original ou revisão, run e eventos `lease_*`. Um operador autorizado pode solicitar reentrega da mesma revisão assinada pelo canal original. Não remover runs para reiniciar o contador. Um terminal exige investigação pelo operador. A publicação continua fora da capacidade do consumidor.

Reproduzir com `python -m pytest -q`, `bash scripts/test-firewall-staging.sh` e `node --test tests/ui/*.test.cjs`. O harness usa PostgreSQL real sem rede e sujeitos Auth sintéticos. Os casos de crash usam commits reais e simulam perda de resposta no transporte ou avanço do relógio por expiração da fixture. Nenhum token hospedado é usado.

Antes de autorizar uso hospedado, confirmar na equipe SCOP o plano, saldo efetivo e direitos dos dois serviços. Com autorização específica, testar o build, a geração da assinatura privada, o ACK/redelivery de Queues, o readback de rede, a disponibilidade de libseccomp e a limpeza do Sandbox, e a chamada de StagingMemory com JWT de worker real. Começar com uma entrega sintética controlada. O código e os testes de SDK em fronteiras substituídas são evidência local. Nesta fase nenhum recurso hospedado foi criado.

## Estimativa

A API autenticada confirmou a equipe SCOP (`scop4`). A resposta da equipe não exibiu plano ou entitlements e a consulta de custos retornou `404 costs_not_found`. Saldo, plano e disponibilidade real de Queues e Sandbox continuam sem confirmação.

Exemplo ilustrativo em `iad1`, nas tarifas Pro antes de créditos, com 100 entregas, mensagem total de até 4 KiB, cinco unidades de fila por entrega (incluindo o dobro no envio idempotente), um arquivo por PR e duas compilações por entrega. Queues fica em cerca de US$ 0,00030 a US$ 0,60 por milhão, sem retries ou extensões de lease. Para 200 criações de Sandbox, 2 GB por VM, mínimo faturável de 1 minuto de memória e 2 s ativos por VM, a estimativa de Sandbox é cerca de US$ 0,156. O total parcial é cerca de US$ 0,16, mais Functions, eventuais retries, tráfego, plano e impostos. Cargas maiores são tarifadas por fatias de 4 KiB, e o custo cresce com o número de arquivos. O crédito Pro público de US$ 20/mês não estabelece saldo da equipe.

Referências: [Queues Python](https://vercel.com/docs/queues/python-sdk), [preços e limites de Queues](https://vercel.com/docs/queues/pricing), [tarifa regional](https://vercel.com/docs/pricing/regional-pricing/iad1), [quotas de Sandbox](https://vercel.com/docs/sandbox/pricing).
