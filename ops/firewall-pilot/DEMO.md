# Demo GitHub da REIVRO

A API do GitHub retornou Forbidden na consulta ao demo. Use uma sessão do founder com acesso a sovereis.

1. Em GitHub → New repository, selecionar o proprietário `sovereis`, nome `reivro-firewall-demo` e visibilidade Public. Inicializar com README. Se o nome já existir, confirmar proprietário e conteúdo antes de usar.
2. Na base main, adicionar somente as fixtures sintéticas com os conteúdos abaixo. Em Settings → Rules → Rulesets, criar uma regra ativa para main que exija pull request e impeça force push e exclusão. Restringir administração a mantenedores e deixar a lista de status checks obrigatórios vazia. Confirmar que não existem workflows com publicação ou deploy.
3. Preparar cada branch com base na main indicada e revisar o diff e o HEAD antes de abrir manualmente cada PR. Parar antes de ativar o webhook ou publicar Checks.

Base de `first.py`:

```python
def value():
    return 1
```

Base de `later.py`:

```python
def total():
    return 2
```

| Branch sugerida | Edição e momento | Aceite |
|---|---|---|
| demo/verify-regression | Na base inicial, trocar `return 1` em first.py por `return )`. | OBSERVED com achado VERIFY. Revisar no staging, confirmar, propor e aprovar o digest com a identidade reviewer. |
| demo/prevent-recurrence | Depois de versionar na main os bytes exatos do manifesto aprovado em `.reivro/protections/python-syntax-regression.json`, criar novo HEAD e trocar `return 2` em later.py por `return ]`. | VIOLATION no HEAD do segundo PR. |
| demo/valid-change | A partir da main com a mesma proteção aprovada, trocar `return 2` por `return 3` em later.py. | PASS no HEAD válido. |
| demo/revoked | Com uma claim ativa, revogar a proteção antes de finish. Em seguida preparar outro HEAD com `return }` em later.py. | A claim em andamento resulta INACTIVE. Um novo run fica sem proteção ativa e a regressão retorna OBSERVED. |

## App e ativação futura

Criar a App privada REIVRO Rework Firewall Pilot com Metadata read, Contents read, Pull requests read e Checks write. Selecionar somente o evento pull_request e somente `sovereis/reivro-firewall-demo` na instalação. Deixar o webhook desativado até existir um HTTPS verificado e autorização de ativação. O endereço planejado é `https://pilot.reivrotools.com/webhooks/github`. Confirmar IDs do repositório e instalação antes de vincular ao staging `lbklqqqbmeyseeccdqog`. Emitir o token de análise com permissões de leitura. Guardar a autorização de escrita exclusivamente para o publicador separado após aprovação explícita.
