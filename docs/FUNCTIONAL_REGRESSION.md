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
