# REIVRO Firewall no Vercel — DRY RUN

Configuração para um futuro projeto independente chamado `reivro-firewall-pilot`. A base é `feat/reivro-github-pilot-infra` em `d0899647f83a0a9275bda021bb7943b76e2f1957`. A auditoria `536bb4e` acrescentou apenas documentação. O projeto `reivro` da landing fica fora deste pacote.

## Contrato de aplicação

- `POST /webhooks/github` recebe no máximo 512 KiB em bytes originais. Valida HMAC antes do JSON, UUID de entrega, ação, instalação, repositório, base e SHAs. Só responde 202 depois da confirmação da fila ou de duplicidade reconhecida pelo SDK. Falha ou confirmação ausente resulta em 503.
- A fila usa o SDK Python com idempotência por entrega. O segundo controle é a unicidade por revisão na Cloud Memory. O `pyproject.toml` registra um consumidor privado gerado pelo builder Python, sem rota HTTP pública de consumo. Retorno normal confirma a entrega. Falha propagada gera retry com intervalo de 30 s e até cinco tentativas configuradas no subscriber.
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

Falhas antes de claim podem ser recuperadas por redelivery. Se a claim ou finish já tiver sido persistida, a Cloud Memory v1 retorna `DUPLICATE`, sem distinguir claim incompleta de execução finalizada. O consumidor evita reexecução automática e registra o UUID para reconciliação. Um operador de staging deve confrontar `runs.delivery`, a revisão e os eventos correspondentes. Se o run estiver incompleto, evitar alterar ou apagar a claim sem uma operação de recuperação auditável. Ainda falta um contrato de recuperação com propriedade/lease, estado persistido e proteção contra concorrência. Falhas de compilação já registradas como ERROR são terminais para a revisão.

Antes de autorizar uso hospedado, confirmar na equipe SCOP o plano, saldo efetivo e direitos dos dois serviços. Com autorização específica, testar o build, a geração da assinatura privada, o ACK/redelivery de Queues, o readback de rede, a disponibilidade de libseccomp e a limpeza do Sandbox, e a chamada de StagingMemory com JWT de worker real. Começar com uma entrega sintética controlada. O código e os testes de SDK em fronteiras substituídas são evidência local. Nesta fase nenhum recurso hospedado foi criado.

## Estimativa

A API autenticada confirmou a equipe SCOP (`scop4`). A resposta da equipe não exibiu plano ou entitlements e a consulta de custos retornou `404 costs_not_found`. Saldo, plano e disponibilidade real de Queues e Sandbox continuam sem confirmação.

Exemplo ilustrativo em `iad1`, nas tarifas Pro antes de créditos, com 100 entregas, mensagem total de até 4 KiB, cinco unidades de fila por entrega (incluindo o dobro no envio idempotente), um arquivo por PR e duas compilações por entrega. Queues fica em cerca de US$ 0,00030 a US$ 0,60 por milhão, sem retries ou extensões de lease. Para 200 criações de Sandbox, 2 GB por VM, mínimo faturável de 1 minuto de memória e 2 s ativos por VM, a estimativa de Sandbox é cerca de US$ 0,156. O total parcial é cerca de US$ 0,16, mais Functions, eventuais retries, tráfego, plano e impostos. Cargas maiores são tarifadas por fatias de 4 KiB, e o custo cresce com o número de arquivos. O crédito Pro público de US$ 20/mês não estabelece saldo da equipe.

Referências: [Queues Python](https://vercel.com/docs/queues/python-sdk), [preços e limites de Queues](https://vercel.com/docs/queues/pricing), [tarifa regional](https://vercel.com/docs/pricing/regional-pricing/iad1), [quotas de Sandbox](https://vercel.com/docs/sandbox/pricing).
