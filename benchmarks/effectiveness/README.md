# Benchmark de eficácia REIVRO v1

O conjunto [scenarios-v1.json](scenarios-v1.json) congela os resultados esperados e o diagnóstico sintético antes da execução. Uma linha é emitida por par cenário/fluxo. A integridade requer a matriz completa e ordenada, rótulos iguais aos pré-fixados, resultados esperados e nenhum efeito extra na reentrega. Um resultado desfavorável especificado pode passar no teste de integridade. A integração conserva erros de execução e a agregação conserva falsos positivos, falsos negativos e abstenções.

## Reprodução

Linux com Git, CPython, libseccomp, Docker e pytest. Use o PostgreSQL 17 já disponível localmente se a rede estiver restrita:

```bash
PYTHON=python3 bash scripts/test-firewall-staging.sh --benchmark /tmp/reivro-effectiveness-v1
python3 -m pytest -q tests/test_scop_effectiveness_benchmark.py
```

O primeiro comando cria PostgreSQL descartável sem rede, aplica 001 e 002 e executa o benchmark. O diretório de saída contém `results.json`, `results.csv` e `summary.md`. Para comparação entre máquinas, registre o SHA limpo, a versão PostgreSQL, a versão CPython, os hashes das fixtures e a configuração. A execução é sequencial na ordem A, B, C, com uma observação por cenário/fluxo e sem aleatoriedade. Os tempos variam por máquina, contenda e cache. Com dez observações por fluxo, p95 por posto mais próximo é a maior amostra.

## Metodologia

- **A:** regra sintética que aceita a entrega sem verificação. Modela ausência de gate no ensaio.
- **B:** VERIFY v2 sobre o mesmo PR sintético e SHA esperado, com subprocesso de compilação real e isolado por libseccomp. Nenhuma proteção é consultada.
- **C:** REVIEW e aprovação no PostgreSQL de fixture, proteção aplicada por digest, verificação pelo mesmo compilador, Cloud Memory via o cliente real ligado às RPCs locais e Durable Execution com leases. Agent Integration lê o run concluído e Agent Feedback confere o relatório sanitizado persistido. A reentrega verifica ausência de novas linhas de run, achado ou evento e de alterações no journal do agente. Nenhum Check, merge ou bloqueio foi exercitado.

Os três fluxos recebem os mesmos dados de origem, com transporte GitHub em memória e identidades Auth sintéticas. Só C tem o estado de aprovação, revogação e artefato que caracteriza o tratamento. A falha do executor é injetada antes de compilar. A adulteração preserva o blob Git de fixture e diverge do digest aprovado, exercitando a checagem de autorização do artefato. A divergência de revisão e a reentrega não têm rótulo binário e ficam fora da matriz de confusão, mas permanecem no relatório.

TP e FP exigem detecção, TN e FN exigem decisão negativa, inclusive a aceitação simulada de A. Erro e inconclusão são abstenções, contabilizadas por classe. Precisão usa TP/(TP+FP), recall decidido usa TP/(TP+FN), e o recall sobre todos os positivos também inclui abstenções no denominador. Divisão sem denominador fica nula. A taxa de inconclusivos usa todas as dez linhas e é separada da taxa de erro. DETECÇÃO inclui achado observado sem proteção ativa; apenas `VIOLATION` é violação de proteção. Nenhuma medida de prevenção efetiva ou produtividade comercial é inferida.

Latência ponta a ponta inclui a operação da linha, RPCs locais e journal quando usados. Preparação, aprovação e revogação ficam fora dessa latência. A medição de CPU envolve apenas a chamada VERIFY, com tempo de usuário e sistema do processo e filhos aguardados, incluindo o compilador. O JSON também dá o tempo de parede desse trecho. As colunas de tempo humano de retrabalho, tentativas de correção, reincidência por projeto e tempo até resolução ficam nulas até um ensaio futuro registrar início/fim de retrabalho, IDs de tentativa e evidência de resolução.

A próxima etapa é comparar o mesmo protocolo em PRs autorizados, com observação de decisões de bloqueio e resultados de correção sob política aprovada. Este relatório não estima horas economizadas nem generaliza a regra de sintaxe para outras regressões.

## V2 e profiling

O V1 publicado permanece intacto. O V2 usa [um novo manifesto](scenarios-v2.json) congelado antes da execução, com três repetições dos nove cenários e PRs sintéticos distintos por repetição. Execute:

```bash
PYTHON=python3 bash scripts/test-firewall-staging.sh --benchmark-v2 /tmp/reivro-effectiveness-v2
```

No perfil C, V2 contabiliza a decisão de VERIFY inclusive quando a operação termina INCONCLUSIVE por falha de proteção. A saída preserva independência entre `verification_status`, `protection_state`, `security_decision` e `status`. O benchmark exige achado persistido para as regressões com artefato alterado, ausente e indisponível. Também exige revisão, sem sucesso, para código limpo com artefato alterado.

O profiling registra tempos por fronteira, com relógio monotônico. `database_ms` inclui transporte de fixture e processos Docker/psql por RPC, inclusive leitura para entrega do relatório. `agent_io_ms` exclui a porção DB e inclui processamento local e journal. `verify_wall_ms` inclui startup e compilação, e `verify_cpu_ms` mede CPU do verificador e filhos esperados. O tempo total inclui o restante do worker, como escopo, HMAC e transporte GitHub em memória. O perfil não mede latência de rede hospedada. Não usar a diferença entre amostras publicadas como estimativa de latência de produção.
