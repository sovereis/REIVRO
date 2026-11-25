# Contrato proposto de regressão funcional

**BLOCKED.** O executor atual compila bytes em processo isolado e não executa o resultado. Ainda não existe evidência de um executor adequado, disponível sem custo, para rodar código arbitrário de PR ou suas dependências. A fixture [functional-regression-v1.json](fixtures/functional-regression-v1.json) fixa resultados conceituais do comparador. Não executa código nem demonstra um Sandbox.

## Entrada e fronteiras de confiança

- A política aprovada referencia um pacote de teste mantido por humanos, proveniente de uma revisão confiável ou repositório segregado. Vincula hash do pacote, identidade/IDs dos testes, comando fixo, versão da regra, imagem imutável, arquitetura e lockfile com hashes. Verificar os bytes no executor. O HEAD nunca fornece teste, configuração, plugins, fixtures, arquivos de inicialização ou comando.
- Resolver BASE e HEAD em Git e fixar os SHAs completos, repositório e checksums das árvores. Revalidar a revisão do PR antes de usar o resultado. Montar testes e configuração confiáveis em leitura e separar da árvore avaliada. Iniciar processos com caminho de importação definido e captura de casos executados independente do stdout do PR. Testes que dependam de um runner importável pelo código avaliado precisam de um desenho que impeça o código de falsificar seu próprio resultado.
- Rodar as duas revisões em VMs limpas, efêmeras e equivalentes, sem rede, credenciais, sockets de host ou mounts graváveis compartilhados. Fixar dependências em imagem ou cache verificado antes de receber o PR. Usar usuário sem privilégios, limitar CPU, memória, processos, disco, saída e tempo de parede. Invalidar o resultado se o provedor não comprovar o isolamento. Encerrar e destruir a VM mesmo após timeout.
- O orquestrador confiável guarda identidade da execução, revisão, versão do executor, política aplicada, hashes, status de cada teste e digest da evidência. Logs limitados e sanitizados recebem distribuição restrita. Um processo do PR pode imprimir dados arbitrários. Seu stdout não constitui atestado.

## Decisão

Executar BASE e HEAD duas vezes em ambientes limpos. BASE deve passar em ambas e HEAD precisa falhar em ambas com o mesmo teste esperado e uma falha de asserção verificável. Falha na BASE, teste omitido, resultado instável ou inputs confiáveis divergentes resultam em INCONCLUSIVE. Falha de infraestrutura, timeout ou capacidade de isolamento ausente resultam em ERROR. PASS vale apenas para os testes e revisões fixados.

A evidência candidata liga os dois SHAs, digest do teste, falha e ambiente. Pode virar proteção após confirmação e aprovação explícita de um humano, vinculada ao digest da regra e escopo. Revogação e fencing continuam no caminho de finalização. Antes de habilitar, comprovar isolamento ativo, ausência de rede e credenciais, integridade dos inputs, limites, detecção de adulteração e impossibilidade de falsificar resultados pelo HEAD, usando somente probes benignos autorizados.

## Missão 5.3: comparador e preflight

`server/scop_verify_functional.py` é uma função pura. O adaptador futuro deverá autenticar e validar observações do controlador, fora da VM avaliada, antes de criar os objetos tipados. Não há endpoint, parser genérico de resultados do convidado ou seletor de executor funcional. Um teste de fixture tenta injetar stdout e exit code como se compusessem uma observação e recebe ERROR. Objetos Python sozinhos não são atestado.

O comparador exige dois registros distintos de BASE e de HEAD com SHAs completos, os mesmos digests de teste, dependências e ambiente e cobertura exata dos IDs de teste. Uma falha de asserção precisa de um digest verificável pelo controlador, idêntico nas duas observações. Resultados conclusivos incluem os pinpoints, o ID e digest da evidência de cada execução, os testes e as asserções, com um identificador determinístico do conjunto. Uma falha de execução ou registro inválido resulta em ERROR. Divergência de revisão, entradas, cobertura, falha já presente e instabilidade resultam em INCONCLUSIVE. Os digests das fixtures são sintéticos.

### Probe local

Executar `bash scripts/probe-functional-runner.sh` somente em ambiente que já tenha Docker, `runsc` registrado e imagem `postgres:17` local. O script não baixa imagens, não monta checkout ou credenciais e roda somente comandos fixos. A sessão observada usou gVisor systrap registrado com `--ignore-cgroups`, sem dispositivo KVM disponível. `unshare -Ur true` foi recusado ao abrir o mapa de UID.

| Controle | Evidência observada |
| --- | --- |
| Separação do host | Caminho de workspace e socket Docker ausentes no contêiner do probe. O probe não cobre fugas nem todos os recursos do host. |
| Rede e credenciais | `--network none`, nenhuma rota IPv4, nenhuma das quatro variáveis de credencial verificadas. Não houve tráfego de teste, montagem de credenciais ou acesso a credenciais do host. |
| Privilégio | UID 65534 e capacidades efetivas zeradas. O status `NoNewPrivs` não pôde ser confirmado. |
| Recursos | CPU, memória e processos não observáveis pelos arquivos de cgroup. A raiz rejeitou escrita e o tmpfs reportou 1 MiB. A política efetiva de armazenamento de toda a execução segue sem comprovação. |
| Timeout e descarte | O comando benigno registrou timeout interno 124. O controlador removeu o contêiner, e a inspeção posterior não o encontrou. |
| Integridade e isolamento do controlador de testes | Sem executor que comprove a origem do resultado fora do guest. Montagem confiável, atestado, dependências e proteção contra falsificação continuam pendentes. |

O sucesso do script significa que o probe alcançou o timeout e verificou remoção. O runner funcional continua **BLOCKED**.

### Integração futura sem segundo Firewall

1. O controlador isolado autenticado alimenta o comparador. Um registro conclusivo de regressão produz a evidência identificada. O operador deve conseguir abrir a evidência protegida e confirmar as observações.
2. Somente após validar essa fronteira, registrar a regra no dispatcher existente e submeter o resultado pelo mesmo finish com lease e fencing. O esquema atual recusa a regra funcional. Um teste real em PostgreSQL confirma essa rejeição e a preservação do caminho de sintaxe.
3. Reusar confirmação humana, aprovação de digest, exportação e revogação. O artefato futuro deve fixar regra, pacote de testes, ambiente e dependências da mesma maneira que a evidência. Usar a aprovação transacional e a revogação já verificadas para sintaxe.
4. Reincidência após aprovação e correção após novo HEAD têm casos declarativos no benchmark, sem aplicação de uma proteção funcional. Com revogação, a decisão de proteção deverá ficar inativa mesmo diante de achado independente. A suíte existente de sintaxe continua exercitando a revogação e as corridas de finalização.

### Benchmark declarativo

```bash
python -m benchmarks.functional.run --output /tmp/reivro-functional.json
python -m pytest -q tests/test_scop_verify_functional.py
```

Os perfis anteriores V1/V2 não são alterados. O JSON funcional conta comparações de fixtures e registra zero execuções de código avaliado.
