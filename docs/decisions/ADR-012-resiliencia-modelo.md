# ADR-012 — Resiliência de Modelo: Retry Exponencial e Fallback entre Tiers

**Status:** ✅ Aceito  
**Data:** 2026-04-22  
**Relacionado:** ADR-002 (escolha do Gemini)

---

## Contexto

O case exige explicitamente:

> "Cada agente deve ser capaz de lidar com erros esperados (ex: falha na leitura de CSV, API indisponível, entrada inválida do usuário) de forma controlada, informando o cliente sobre o problema de maneira clara e, se possível, oferecendo alternativas ou registrando o erro para análise técnica posterior **sem interromper abruptamente a interação**."

A implementação inicial chamava `llm.invoke()` diretamente em cada agente. Qualquer erro de API (429 — quota excedida, 503 — serviço indisponível, timeout) propagava como exceção não tratada, quebrando a conversa.

Erros comuns em free tier do Gemini:
- `429 Resource Exhausted` — limite de requisições por minuto atingido
- `503 Service Unavailable` — sobrecarga temporária do servidor
- Timeouts em horários de pico

---

## Decisão

Centralizar toda invocação de LLM em `src/infrastructure/model_provider.py` com:

**Tiers de modelo:**
```
fast  → gemini-2.5-flash      (padrão — rápido, estável, ativo em 2026)
pro   → gemini-2.5-pro        (análises complexas — Fase 2 do crédito)
lite  → gemini-2.5-flash-lite (fallback final — menor custo)
```

> **Migração 23/04/2026:** Os modelos `gemini-2.0-flash` e `gemini-2.0-flash-lite` foram substituídos pelas versões 2.5 equivalentes após diagnóstico de erros `429 Resource Exhausted` sistemáticos. Ver ADR-002.

**Cadeia de fallback:**
```
fast → lite → [falha definitiva]
pro  → fast → lite → [falha definitiva]
```

**Retry por tier:** até 3 tentativas com backoff exponencial (2s, 4s, 8s) para erros transitórios (429, 503, timeout). Erros permanentes (401, chave inválida) não fazem retry.

**Todos os agentes** substituíram `ChatGoogleGenerativeAI(...).invoke()` por `invocar_com_fallback(messages, tier="fast")`.

---

## Justificativa

**Por que backoff exponencial e não linear?**

Erros 429 indicam que o serviço está sobrecarregado. Retentativas imediatas pioram a situação. O backoff exponencial dá tempo ao serviço de se recuperar entre tentativas.

**Por que fallback para `lite` em vez de outro provider (OpenAI, Groq)?**

- Mantém a homogeneidade: mesmo formato de mensagens, mesma API, sem chaves adicionais
- O `lite` é significativamente mais barato e tem quota maior que o `flash`
- Adicionar providers externos exigiria normalização de erros e formatos diferentes

**Por que centralizar em `model_provider.py`?**

- DRY: lógica de retry e fallback em um único lugar
- Testabilidade: fácil mockar para testes
- Observabilidade: logs centralizados informam quantas tentativas foram necessárias

---

## Alternativas descartadas

- **Try/except em cada agente**: duplicação de código; cada agente precisaria implementar sua própria lógica de retry.
- **LangChain RetryWithErrorOutputParser**: focado em erros de parsing de output, não em erros de API.
- **Fallback para OpenAI**: requer nova chave de API e normalização de formatos de mensagem.

---

## Consequências

- **Positivas**: conversa não quebra em erros transitórios; requisito explícito do case atendido
- **Negativas**: latência máxima aumenta em casos de falha (até 14s com 3 tentativas de backoff)
- **Observabilidade**: log `WARNING` em cada retry, `INFO` quando recuperado, `ERROR` em falha definitiva
- **RuntimeError**: se todos os tiers e tentativas falharem, o erro se propaga e o Streamlit exibe mensagem de indisponibilidade ao usuário
