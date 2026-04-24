# ADR-019 — Estrutura de Prompts: "Quando Usar / Quando NÃO Usar"

| Campo | Valor |
|---|---|
| **Status** | Aceito |
| **Data** | 2026-04-23 |
| **Decisores** | Equipe de desenvolvimento |

---

## Contexto

Os prompts dos agentes descreviam apenas o **fluxo positivo** — o que fazer quando tudo corre bem. Esse padrão gerou uma série de comportamentos incorretos detectados pelos testes do simulador:

| Bug detectado | Causa raiz |
|---|---|
| Flash diz "Registrei seu pedido" sem chamar `registrar_pedido_aumento` | Prompt não proibia dizer que registrou sem chamar a tool |
| LLM consulta câmbio mas retorna o limite de crédito como cotação | Prompt não alertava sobre a confusão entre tipos de dados |
| `calcular_score_credito` chamada antes de coletar todos os dados | Prompt não dizia quando NÃO chamar a tool |
| Agente pede CPF de cliente já autenticado | Prompt não distinguia contexto pré/pós autenticação claramente |

Em todos os casos, o problema não era falta de instrução positiva — era falta de instrução **negativa com redirecionamento**.

---

## Decisão

Adotar a estrutura **"Quando usar / Quando NÃO usar"** para cada ferramenta e capacidade documentada no prompt, com cada caso negativo acompanhado de um redirecionamento explícito ("em vez disso, faça X").

Esse padrão é adotado diretamente do Claude Code, onde cada ferramenta tem seções `When to use` e `When NOT to use the Tool` com alternativas concretas:

```
When NOT to use the AgentTool:
- If you want to read a specific file path, use the FileReadTool instead
- If you are searching for a specific class definition like "class Foo", use GlobTool instead
```

### Estrutura aplicada nos prompts do projeto

```markdown
## Ferramenta: `nome_da_ferramenta`

### Quando usar
- Condição A que justifica o uso.
- Condição B que justifica o uso.

### Quando NÃO usar
- Condição X → em vez disso, faça Y.
- Condição Z → em vez disso, faça W.
- NUNCA faça P sem antes ter Q.
```

### Exemplo: `registrar_pedido_aumento` (crédito)

```markdown
## Ferramenta: `registrar_pedido_aumento`

### Quando usar
- `verificar_elegibilidade_aumento` foi chamada e retornou um resultado nesta mesma conversa.
- Você conhece o status determinístico: "aprovado" ou "reprovado".

### Quando NÃO usar
- `verificar_elegibilidade_aumento` ainda não foi chamada → chame-a primeiro.
- Você não recebeu o retorno da ferramenta → aguarde, não antecipe o resultado.
- NUNCA diga "registrei" ou "solicitação registrada" sem ter chamado esta ferramenta.
  Afirmar um registro inexistente é uma mentira ao cliente.
```

### Exemplo: `buscar_cotacao_cambio` (câmbio)

```markdown
## Ferramenta: `buscar_cotacao_cambio`

### Quando NÃO usar
- A mensagem não menciona nenhuma moeda → pergunte qual moeda antes de chamar a tool.
- NUNCA use o limite de crédito ou score do cliente como valor de câmbio.
  O limite (ex.: R$ 5.000,00) não é uma taxa de câmbio.
```

### Complemento: `<example>` para casos limítrofes

Para situações onde a fronteira "usar / não usar" é sutil, exemplos concretos são incluídos:

```markdown
<example>
Dados coletados: renda=3000, emprego=formal, dependentes=1, dividas=não
→ Chame calcular_score_credito. ✅

Dados coletados: renda=3000, emprego=formal, dependentes=?
→ Pergunte: "Quantas pessoas dependem de você?" ❌ não chame ainda.
</example>
```

---

## Justificativa

### Por que "Quando NÃO usar" é mais eficaz que só "Quando usar"?

O LLM é um completador de texto: na ausência de restrições explícitas, tende a preencher lacunas com o comportamento que parece mais plausível no contexto da conversa. "Quando usar" ensina o caminho certo; "Quando NÃO usar" fecha os atalhos errados.

A analogia em código: um `if` positivo define o que fazer; o `guard clause` explícito (`if not condition: raise`) previne estados inválidos. Prompts sem "NÃO usar" são equivalentes a funções sem guard clauses.

### Por que incluir o redirecionamento ("em vez disso, X")?

Proibir sem redirecionar força o LLM a improvisar. Com o redirecionamento, o comportamento alternativo correto está explícito — o LLM não precisa inferir o que fazer quando a condição negativa se aplica.

Exemplo do efeito prático:
- **Sem redirecionamento:** "não registre sem tool" → LLM confuso, pode retornar resposta vazia ou inventar outra ação.
- **Com redirecionamento:** "não registre sem tool → chame `verificar_elegibilidade_aumento` primeiro" → comportamento previsível.

### Por que tabelas e `<example>` no prompt?

LLMs processam estrutura visual. Tabelas criam associações explícitas (pergunta → ação); exemplos com `✅/❌` fornecem âncoras de classificação que o modelo usa durante a inferência. O Claude Code usa `<example>` extensivamente por esse motivo.

---

## Alternativas consideradas

### Instrução negativa no início do prompt ("NUNCA faça X")
- Funciona para proibições absolutas, mas sem contexto (quando X se aplica) tem menor precisão.
- Adotado como complemento, não substituto, para violações críticas (ex.: "NUNCA diga 'registrei' sem chamar a tool").

### Validação em código (guarda no `agent.py`)
- Usado paralelamente: guarda de alucinação regex em `agent.py` detecta "registrei" sem tool call.
- Não é substituto do prompt — a guarda de código é a última linha de defesa, não a primeira.

### Few-shot examples no início do prompt
- Eficaz mas aumenta significativamente o número de tokens do system prompt.
- Reservado para casos limítrofes via `<example>` inline nas seções relevantes.

---

## Consequências

**Positivas:**
- Eliminação dos bugs de "alucinação de ação" (LLM declara ter feito algo que não fez).
- Comportamento mais previsível nas fronteiras entre agentes (ex.: crédito → entrevista).
- Prompts auto-documentados: a seção "Quando NÃO usar" serve como especificação de casos de erro esperados.

**Negativas / trade-offs:**
- Prompts mais longos — cada ferramenta adiciona ~8–15 linhas com as seções de uso/não-uso.
- Requer disciplina de manutenção: ao adicionar uma nova tool, as seções devem ser preenchidas.

---

## Referências

- ADR-018: Arquitetura de Prompts Python
- ADR-014: Sistema de Contratos de Resposta (camada complementar de defesa)
- [Claude Code `AgentTool/prompt.ts`](../..): padrão "When NOT to use" de referência
- `src/agents/*/prompt.py`
