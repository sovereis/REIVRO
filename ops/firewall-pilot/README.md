# Operação do ensaio REIVRO

Este pacote usa exclusivamente o staging `lbklqqqbmeyseeccdqog` e o demo público `sovereis/reivro-firewall-demo`. O worker do pacote passa `publish=False` e persiste o resultado do ensaio. A CLI anterior de publicação fica fora dos serviços. A criação da VM, a ativação do webhook e a primeira publicação real exigem autorização posterior.

## Instalação após aprovação financeira

Usar Ubuntu 24.04 LTS x86-64 em Lightsail com Python 3.12, SQLite com RETURNING, libseccomp e Caddy com suporte a request_body. Copiar o checkout revisado para /opt/reivro-pilot, com escrita reservada a root. Criar os usuários de sistema reivro-receive e reivro-work e o grupo reivro-pilot. Instalar os dois units e o arquivo tmpfiles. Aplicar tmpfiles antes de ligar os serviços. Preencher os IDs reais no arquivo pilot.env sem valores secretos. Configurar o host DNS aprovado no ambiente do Caddy e liberar TCP 80 e 443 para certificado e HTTPS. Restringir SSH a operadores e aplicar regra de egress para GitHub API e staging no worker. Testar a versão do Caddy, os units e todos os controles no host antes de ativar o webhook.

O diretório de credenciais deve ficar sob root com arquivos 0600, abastecidos por um operador a partir do Vault. O systemd entrega apenas os arquivos listados para cada serviço. O receptor recebe webhook. O worker recebe webhook, publishable-key, worker-jwt e github-installation-token. Manter a chave privada da App e a chave administrativa do staging fora da VM. O token da instalação deve ser emitido externamente com escopo de um repositório e as quatro permissões aprovadas. Emitir um JWT de worker por login normal no staging. Provisionar rotação antes da ativação. LoadCredential é carregado no início do serviço. Atualizar arquivos atomicamente e reiniciar o worker entre jobs antes da expiração. Rotacionar o segredo de webhook com a fila drenada e o ingresso sob controle.

## Fila, acompanhamento e recuperação

Executar `REIVRO_QUEUE=/var/lib/reivro-pilot/queue.sqlite3 python3 -m server.scop_firewall_pilot status` com uma conta operacional que possa acessar a fila. Monitorar contagem e idade em pending e review, falhas dos serviços e espaço livre. Usar um coletor local com alertas ao operador. Conservar logs do piloto por 14 dias e limitar seu tamanho. A fila elimina registros expirados após 14 dias, remove corpo e assinatura de entregas concluídas e conserva somente o resultado operacional. Exportar separadamente registros mínimos de auditoria necessários antes do vencimento do prazo. Preservar as fixtures e o manifesto anteriores.

Após reinício, pending continua automaticamente e running passa para review. Para review, confirmar o ID e a revisão no staging e verificar se há claim ou finish registrados antes de qualquer reprocessamento. Um resultado DUPLICATE pode indicar uma claim anterior interrompida. Em uma futura fase com publicação, consultar o Check por HEAD, App, nome, external_id e conclusão antes de autorizar nova tentativa. Sem confirmação conclusiva, manter em revisão. Nenhum retry de publicação é feito por este pacote.

Para backup, executar `backup.sh /var/lib/reivro-pilot/queue.sqlite3 /caminho/privado/backup.sqlite3` e transferir o arquivo para armazenamento criptografado, com acesso operacional e expiração compatível. Para testar restauração, abrir a cópia em diretório isolado e verificar integridade e estado. Antes de restaurar na VM, parar receptor e worker, preservar uma cópia consistente do estado atual, restaurar em diretório limpo com proprietário e grupo corretos, sem reaproveitar arquivos WAL antigos, e iniciar primeiro o worker. A VM única preserva a fila após reinício, mas a perda do disco exige restauração e reconciliação.

## GitHub e staging

Criar o demo público com README e dois arquivos Python sintéticos válidos. Proteger main com escrita de mantenedores, sem Check obrigatório. Preparar branches e PRs de regressão inicial, reincidência e alteração válida. Registrar a App privada REIVRO Rework Firewall Pilot com Metadata read, Pull requests read, Contents read e Checks write, evento pull_request e somente o demo selecionado. Usar apenas a URL pública aprovada. Conferir o ID do repositório, da instalação e a seleção exclusiva antes de criar o vínculo e a identidade de worker com acesso limitado no staging.

### Fixtures propostas para os PRs do demo

Na base, colocar `def value(): return 1` em `first.py` e `def total(): return 2` em `later.py`. Usar branches independentes a partir da base correspondente.

| PR | Alteração sintética | Resultado esperado após autorização |
|---|---|---|
| Regressão inicial | Trocar a função de first.py por `def value(: return 1` | OBSERVED com evidência, seguido de confirmação humana e aprovação pelo digest |
| Reincidência | Após versionar o manifesto aprovado na base, trocar a função de later.py por `def total(): return )` | VIOLATION no HEAD da reincidência |
| Alteração válida | Após versionar o manifesto aprovado, trocar o retorno de later.py por 3 | PASS no HEAD válido |
| Após revogação | Abrir PR com novo HEAD e nova falha sintática após a revogação | Sem proteção ativa e sem resultado VIOLATION pela regra revogada |
