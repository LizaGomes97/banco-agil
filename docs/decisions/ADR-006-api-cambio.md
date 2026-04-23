# ADR-006: API de Cotação de Câmbio

**Data:** 2026-04-22  
**Status:** Aceito  
**Autor:** Equipe Banco Ágil

---

## Contexto

O Agente de Câmbio precisa buscar cotações de moedas em tempo real. O case sugere APIs como Tavily ou SerpAPI, mas qualquer API externa é válida. A escolha impacta:
- Facilidade de integração com LangGraph como tool
- Necessidade de chave de API
- Confiabilidade e disponibilidade do free tier
- Qualidade e formato dos dados retornados

---

## Decisão

**Escolha:** `Tavily Search API`

Usaremos Tavily como tool de busca para cotações, aproveitando sua integração nativa com LangChain/LangGraph.

---

## Justificativa

| Critério | Tavily | AwesomeAPI | ExchangeRate-API | yfinance |
|----------|--------|------------|------------------|----------|
| Integração LangChain | ✓ Nativa (`TavilySearchResults`) | Manual | Manual | Manual |
| Chave de API necessária | Sim (free tier) | Não | Sim (free tier) | Não |
| Dados em tempo real | ✓ | ✓ | ✓ | ~15min delay |
| Moedas suportadas | Todas (busca web) | BRL focus | 170+ moedas | Limitado |
| Free tier | 1000 buscas/mês | Ilimitado | 1500 req/mês | Ilimitado |
| Manutenção do código | Mínima | Alta (parse manual) | Média | Média |

A principal vantagem do Tavily é a **integração nativa como tool do LangGraph** — o agente pode chamá-la diretamente sem código de plumbing adicional. O agente formula a busca, Tavily retorna o resultado, o LLM interpreta e responde ao cliente.

---

## Alternativas consideradas

| Opção | Prós | Contras | Descartada por |
|-------|------|---------|----------------|
| **AwesomeAPI (BR)** | Sem chave, foco BRL, JSON limpo | Apenas moedas em BRL, sem integração LangChain nativa, pode sair do ar | Escopo limitado a BRL |
| **ExchangeRate-API** | REST simples, confiável, 170+ moedas | Requer parse manual, uma chave a mais para gerenciar | Integração mais trabalhosa que Tavily |
| **yfinance** | Sem chave, biblioteca Python | Delay de 15 minutos, não é "tempo real", dados podem falhar | Não adequado para cotação bancária |
| **SerpAPI** | Busca web geral | Mais caro, menos foco em dados financeiros | Custo e complexidade |

---

## Implementação

```python
# src/tools/exchange_rate.py
from langchain_community.tools.tavily_search import TavilySearchResults

def criar_tool_cambio():
    return TavilySearchResults(
        max_results=1,
        name="buscar_cotacao_cambio",
        description=(
            "Busca a cotação atual de moedas estrangeiras. "
            "Use para consultar o valor do dólar, euro, ou outras moedas."
        )
    )
```

O agente de câmbio recebe esta tool e, quando o cliente solicita uma cotação, o LLM formula a query (`"cotação dólar hoje em reais"`) e interpreta o resultado para o cliente.

---

## Consequências

**Positivas:**
- Integração com LangGraph em poucas linhas
- O LLM cuida da formulação da query e interpretação — sem parse rígido de JSON
- Suporta qualquer moeda (o Tavily busca na web)

**Negativas / trade-offs aceitos:**
- Requer chave de API do Tavily (free tier: 1000 buscas/mês)
- Resultado depende do que o Tavily encontra na web — pode variar em formato
- Em produção real, seria substituída por API financeira dedicada (Bloomberg, Open Exchange Rates)

---

## Referências

- [Tavily API — Documentação](https://docs.tavily.com/)
- [LangChain — TavilySearchResults tool](https://python.langchain.com/docs/integrations/tools/tavily_search/)
- [ADR-003](ADR-003-handoff-agentes.md) — Como as tools são expostas aos agentes
