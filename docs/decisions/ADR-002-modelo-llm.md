# ADR-002: Modelo de Linguagem (LLM)

**Data:** 2026-04-22  
**Atualizado:** 2026-04-23  
**Status:** Aceito (atualizado — migração Gemini 2.0 → 2.5)  
**Autor:** Equipe Banco Ágil

---

## Contexto

O sistema requer um LLM para alimentar os 4 agentes conversacionais. O modelo precisa:
- Suportar **tool calling** (chamada de ferramentas estruturadas)
- Gerar **respostas em português** com fluência e tom profissional bancário
- Ter **latência aceitável** para conversas em tempo real
- Ser compatível com LangGraph/LangChain via integração nativa

---

## Decisão

**Escolha atual:** `Gemini 2.5 Flash (Google AI)`

Usaremos o modelo `gemini-2.5-flash` como LLM primário para todos os agentes, acessado via API do Google AI Studio.

> **Migração em 23/04/2026:** O modelo original `gemini-2.0-flash` foi substituído pelo `gemini-2.5-flash` após diagnóstico de erros 429 persistentes. Veja seção "Histórico de Migração" abaixo.

---

## Justificativa

| Critério | Avaliação |
|----------|-----------|
| Tool calling | Suporte nativo e robusto a function calling |
| Qualidade em português | Excelente — treinado com grande corpus em PT-BR |
| Latência | Flash é otimizado para velocidade (~1–2s por resposta) |
| Integração LangChain | `langchain-google-genai` com suporte nativo |
| Estabilidade | Modelo ativo e mantido pelo Google em 2026 |
| Custo | Mais barato que GPT-4o para o mesmo nível de qualidade |

---

## Histórico de Migração: Gemini 2.0 → 2.5

### Problema identificado (23/04/2026)

Durante testes com o simulador automatizado, o modelo `gemini-2.0-flash` retornava erros `429 Resource Exhausted` de forma sistemática, mesmo com chave de API com billing ativo.

**Diagnóstico via HTTP direto:**
```
gemini-2.0-flash     → 429 RESOURCE_EXHAUSTED (em toda chamada)
gemini-2.0-flash-lite → 404 "no longer available to new users"
gemini-2.5-flash     → 200 OK (0.9s)
```

**Causa:** O Google está restringindo progressivamente a quota do `gemini-2.0-flash` em 2026 para incentivar migração para a série 2.5. Os modelos `2.0-flash-lite` e `2.0-flash-001` foram descontinuados para novos usuários.

### Solução

Migração para `gemini-2.5-flash` como modelo principal. Todas as referências foram atualizadas:
- `src/config.py` — default do `GEMINI_MODEL`
- `.env` e `.env.example`
- `src/infrastructure/model_provider.py` — tier `fast` e `lite`

---

## Alternativas consideradas

| Opção | Prós | Contras | Decisão |
|-------|------|---------|---------|
| **Gemini 2.5 Flash** ✅ | Modelo ativo, rápido, estável em 2026 | — | **Escolhido** |
| **Gemini 2.5 Pro** | Raciocínio superior | Mais lento e caro; reservado para análise de crédito (tier `pro`) | Usado apenas no pipeline Pro |
| **GPT-4o Mini** | Confiável, amplamente documentado | Free tier limitado; custo para demonstração | Descartado |
| **Groq + LLaMA 3** | Latência ultra-baixa | Tool calling inferior, português menos fluente | Descartado |
| **Gemini 2.0 Flash** | — | 429 sistemático em 2026; descontinuação em curso | **Substituído** |

---

## Configuração adotada

```python
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",   # configurável via GEMINI_MODEL no .env
    temperature=0.3,            # baixo para respostas consistentes e profissionais
    google_api_key=os.getenv("GEMINI_API_KEY")
)
```

**Temperatura 0.3:** Baixa o suficiente para respostas consistentes, alta o suficiente para não parecer robótico. Temperatura 0.0 foi descartada para evitar rigidez nas respostas conversacionais.

---

## Consequências

**Positivas:**
- Respostas em português com qualidade bancária
- Tool calling confiável para integração com ferramentas Python
- Modelo ativo e com suporte garantido em 2026
- Latência equivalente ou melhor que o 2.0-flash

**Negativas / trade-offs aceitos:**
- Dependência de conectividade com a API do Google
- Possível degradação de qualidade se o modelo for atualizado sem aviso

---

## Referências

- [Google AI Studio — Modelos disponíveis](https://ai.google.dev/gemini-api/docs/models)
- [LangChain Google GenAI integration](https://python.langchain.com/docs/integrations/chat/google_generative_ai/)
- [Gemini 2.5 Flash — Release notes](https://deepmind.google/technologies/gemini/flash/)
- ADR-012 — Resiliência com Fallback de Modelo (tiers atualizados)
