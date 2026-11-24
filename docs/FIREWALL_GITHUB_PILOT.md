# Primeiro GitHub Check do Rework Firewall

Use o Supabase staging `lbklqqqbmeyseeccdqog`. A execução local parte de `2d847e2`, na linha de integração que contém o worker e a Cloud Memory. O projeto de produção `hnlmnswotenppgdqxvkv` está fora do piloto.

## Evidência hospedada preservada

A rodada hospedada anterior criou cinco usuários sintéticos, dois projetos e quatro vínculos. Todos os logins por senha retornaram HTTP 200 e os JWTs tinham os sujeitos e o emissor esperados. Com JWTs reais, reviewer e viewer leram A, o reviewer de B leu B, leituras cruzadas e sem vínculo retornaram JSON nulo, e alterações indevidas retornaram HTTP 403. O worker executou claim e finish. Acesso anônimo e JWT inválido receberam HTTP 401. Acesso direto ao schema privado e escrita direta de proteção receberam HTTP 406. O reviewer confirmou, aprovou pelo digest e revogou. Os resultados observados foram OBSERVED, VIOLATION, INACTIVE e OBSERVED. Duas claims concorrentes tiveram um vencedor e uma duplicata. A auditoria confirmou 12 eventos atribuídos aos atores esperados. O run de B para a leitura positiva foi inserido administrativamente como fixture.

O primeiro finish recebeu HTTP 400 devido a `pr_url` ausente. A auditoria confirmou ausência de transição parcial. A mesma claim foi concluída após corrigir a fixture. O worker já envia a URL do PR junto dos SHAs e dos demais campos de identidade. O candidato SQL local foi alinhado ao dispatcher hospedado consultado em somente leitura, incluindo URL e compilador em relatórios conclusivos, arquivo Python em resultados PASS e rejeição de identidade Auth anônima. A assinatura de `dispatch` e `read_run` ficou compatível com o adaptador existente. A regressão local cobre URL ausente, PR divergente e URL com a caixa canônica do GitHub.

O manifesto privado da rodada anterior tem modo `0600` e permanece fora do Git. Preserve as fixtures até o founder decidir se elas ainda são necessárias. A rodada usou fixtures de GitHub.

## App e repositório propostos

| Campo | Valor proposto |
|---|---|
| Nome | REIVRO Rework Firewall Pilot, sujeito à disponibilidade |
| Proprietário | `sovereis` |
| Página inicial | `https://github.com/sovereis/reivro-firewall-demo` |
| Visibilidade da App | Privada, instalável apenas pelo proprietário |
| Instalação | Only select repositories → `sovereis/reivro-firewall-demo` |
| Permissões de repositório | Metadata read, Pull requests read, Contents read, Checks write |
| Outras permissões | Nenhuma de organização ou conta |
| Webhook | Ativo, HTTPS, verificação TLS habilitada, segredo aleatório dedicado de pelo menos 32 bytes no Vault |
| URL de webhook | `https://<host-piloto-aprovado>/webhooks/github` |
| Evento | Pull request, com processamento de opened, reopened e synchronize |
| OAuth de usuário | Sem callback ou autorização de usuário |
| Branch base | `main`, com escrita limitada aos mantenedores e sem Check obrigatório |

Recomendo um repositório público separado, com README e dois arquivos Python sintéticos já presentes na base. O nome e a disponibilidade precisam ser confirmados pelo proprietário. A integração GitHub visível nesta sessão abrange todos os repositórios da conta, portanto a proposta usa uma App dedicada. O checkout oferece um worker de entrega única e configuração Vercel do landing, sem receptor dedicado ao piloto.

## Webhook e worker

1. Endpoint HTTPS público com limite de corpo de 512 KiB (`MAX_WEBHOOK`) e HMAC SHA-256 sobre os bytes originais. Validar `X-Hub-Signature-256` com comparação em tempo constante antes de interpretar JSON ou enfileirar. Preservar corpo e cabeçalhos GitHub no transporte. Confirmar IDs de instalação e repositório, evento, ação, base e revisão. O worker repete a validação.
2. Como hospedagem, usar um serviço HTTPS pequeno, fila durável e worker Linux/CPython com libseccomp. Responder sucesso após persistir a entrega autenticada. Executar o worker a partir da revisão revisada da REIVRO. A compilação de arquivos do PR usa subprocesso isolado, ambiente vazio, limites de tempo, memória e saída. O worker não faz checkout do PR nem executa seus workflows, dependências ou código.
3. Emitir token de instalação efêmero com a chave privada da App no Vault e limitar o token ao ID do demo e às permissões listadas. Obter JWT do worker emitido pelo Auth do staging. Configurar IDs e branch esperados no servidor. Redigir cabeçalhos, payloads, variáveis e credenciais nos logs. Fixar o ref de staging na configuração do serviço. Restringir o egress do worker à API do GitHub e ao host `lbklqqqbmeyseeccdqog.supabase.co`. O leitor público de evidências também consulta a API GitHub e está sujeito à limitação de requisições.
4. Deduplicar pelo UUID de entrega e pela revisão no banco. Em `PUBLICATION_UNCERTAIN`, consultar os Checks do HEAD e reconciliar App, nome, `external_id` do run e conclusão. Tratar claims interrompidas e publicações ausentes manualmente antes de qualquer nova tentativa. Registrar somente IDs e resultados operacionais necessários.

## Sequência e aceite

| Etapa | Evidência exigida |
|---|---|
| Primeiro PR | Alterar um Python existente para introduzir falha sintática. VERIFY coleta evidência reprodutível. O Check no HEAD exato conclui neutral e o run fica OBSERVED. |
| Revisão e proteção | Reviewer autenticado confirma o achado. Aprovar o digest e versionar o manifesto byte a byte no caminho `.reivro/protections/python-syntax-regression.json`, em commit revisado na base confiável. |
| Segundo PR | Usar outra revisão e outra regressão da mesma categoria. PREVENT produz VIOLATION, com Check failure no HEAD exato do segundo PR. |
| PR válido | Alterar Python sem regressão. Obter PASS e Check success no HEAD correspondente. |
| Revogação | Revogar com reviewer e digest corretos. Uma claim finalizada depois da revogação resulta INACTIVE quando vinculada à proteção revogada. Um novo PR fica sem proteção ativa e sem conclusão failure por essa regra. |

Para cada Check real, comparar o HEAD retornado pelo GitHub com o HEAD verificado, e o `external_id` com o run persistido. Verificar ID da App, conclusão, eventos de auditoria e unicidade do Check após redelivery. Uma entrega adulterada deve falhar antes do claim. Validar os estados separadamente do merge, que permanece manual.

## Aprovação e orçamento

O founder deve aprovar a criação do repositório e da App dedicada, a instalação somente no demo, a hospedagem e o teto de gastos, os segredos e operadores autorizados, o vínculo do repositório real no staging, a estratégia para as fixtures anteriores e a primeira publicação real. Registrar o ID real do repositório, ID da instalação e branch confiável antes de provisionar a associação no staging.

Estimativa de cenário, sem cotação. Com mil entregas e 30 s de worker por entrega, são cerca de 8,3 horas de execução por mês, ou US$ 0,42–1,25 a US$ 0,05–0,15 por hora de computação. O endpoint sempre ativo, fila, Vault, armazenamento e tráfego podem dominar o custo. Validar os preços e franquias do provedor escolhido. O orçamento do Supabase staging depende do plano já contratado.
