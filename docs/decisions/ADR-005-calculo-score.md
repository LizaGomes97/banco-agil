# ADR-005: Cálculo do Score de Crédito

**Data:** 2026-04-22  
**Status:** Aceito  
**Autor:** Equipe Banco Ágil

---

## Contexto

O Agente de Entrevista de Crédito precisa calcular um score após coletar dados financeiros do cliente (renda, tipo de emprego, dependentes, dívidas). O case fornece uma fórmula exata com pesos definidos:

```
score = (
    peso_renda(renda_mensal) +
    peso_emprego[tipo_emprego] +
    peso_dependentes[num_dependentes] +
    peso_dividas[tem_dividas]
)
```

A decisão central é: **quem executa esse cálculo** — o LLM ou código Python?

---

## Decisão

**Escolha:** Função Python determinística encapsulada em uma `Tool` do LangGraph

O cálculo é implementado como código Python puro e exposto ao agente como uma ferramenta (`@tool`). O LLM conduz a entrevista e coleta os dados, mas **nunca realiza o cálculo** — ele apenas chama a tool com os parâmetros coletados.

---

## Justificativa

**LLMs não são calculadoras.** Deixar um LLM calcular um score financeiro apresenta riscos sérios:

| Problema | Impacto |
|----------|---------|
| Não determinismo | Mesma entrada pode gerar scores diferentes entre chamadas |
| Alucinação aritmética | LLMs cometem erros em somas simples com frequência |
| Não auditável | Impossível rastrear como o score foi calculado |
| Não testável | Impossível escrever teste unitário para "o LLM calculou certo" |

Um sistema bancário — mesmo fictício — precisa de cálculos **corretos, rastreáveis e idênticos** para a mesma entrada.

**Separação de responsabilidades:**
- LLM faz o que é bom: conversar, coletar dados, contextualizar respostas
- Python faz o que é seguro: calcular, validar, persistir

---

## Alternativas consideradas

| Opção | Prós | Contras | Descartada por |
|-------|------|---------|----------------|
| **LLM calcula no prompt** | Zero código adicional | Não determinístico, erros aritméticos, não auditável | Risco crítico para sistema financeiro |
| **Cálculo inline no nó do agente** | Simples | Lógica de negócio misturada com lógica de agente | Viola separação de responsabilidades |
| **Serviço externo (API)** | Desacoplado | Overhead desnecessário para este escopo | Complexidade desproporcional |

---

## Implementação

```python
# src/tools/score_calculator.py
from langchain_core.tools import tool

PESO_EMPREGO = {"formal": 300, "autônomo": 200, "desempregado": 0}
PESO_DEPENDENTES = {0: 100, 1: 80, 2: 60}
PESO_DEPENDENTES_DEFAULT = 30  # para 3+
PESO_DIVIDAS = {"sim": -100, "não": 100}
PESO_RENDA = 30

@tool
def calcular_score_credito(
    renda_mensal: float,
    tipo_emprego: str,
    num_dependentes: int,
    tem_dividas: str
) -> dict:
    """
    Calcula o score de crédito do cliente com base nos dados da entrevista.
    Retorna o score calculado e o detalhamento dos pesos aplicados.
    """
    peso_dep = PESO_DEPENDENTES.get(num_dependentes, PESO_DEPENDENTES_DEFAULT)
    
    score = (
        min(renda_mensal / 1000 * PESO_RENDA, 900)  # cap em 900 para renda
        + PESO_EMPREGO.get(tipo_emprego.lower(), 0)
        + peso_dep
        + PESO_DIVIDAS.get(tem_dividas.lower(), 0)
    )
    
    return {
        "score": round(score),
        "detalhamento": {
            "renda": round(min(renda_mensal / 1000 * PESO_RENDA, 900)),
            "emprego": PESO_EMPREGO.get(tipo_emprego.lower(), 0),
            "dependentes": peso_dep,
            "dividas": PESO_DIVIDAS.get(tem_dividas.lower(), 0)
        }
    }
```

---

## Limiar de aprovação

O case não define explicitamente o score mínimo para aprovação. Adotaremos **score ≥ 500** como limiar, documentado aqui como decisão de negócio para facilitar ajuste futuro.

```python
# src/tools/score_calculator.py
SCORE_MINIMO_APROVACAO = 500
```

---

## Consequências

**Positivas:**
- Cálculo 100% determinístico — mesma entrada sempre gera mesmo score
- Totalmente testável com pytest (função pura)
- Auditável — detalhamento dos pesos retornado junto com o score
- Separação clara: LLM conversa, Python calcula

**Negativas / trade-offs aceitos:**
- O LLM precisa coletar os dados corretamente antes de chamar a tool — prompt do agente de entrevista precisa ser bem escrito para garantir isso
- Limiar de aprovação (500) é arbitrário e não foi especificado no case — documentado aqui para transparência

---

## Referências

- [Desafio Técnico — Fórmula de score](../Desafio%20Técnico%20para%20Dev%20Agentes%20de%20IA.pdf)
- [LangChain — Custom tools com @tool](https://python.langchain.com/docs/how_to/custom_tools/)
- [ADR-003](ADR-003-handoff-agentes.md) — Estrutura do estado onde o score é armazenado
