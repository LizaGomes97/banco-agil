# ADR-002: Modelo de Linguagem (LLM)

**Data:** 2026-04-22  
**Status:** Aceito  
**Autor:** Equipe Banco Ágil

---

## Contexto

O sistema requer um LLM para alimentar os 4 agentes conversacionais. O modelo precisa:
- Suportar **tool calling** (chamada de ferramentas estruturadas)
- Gerar **respostas em português** com fluência e tom profissional bancário
- Ter **free tier viável** para desenvolvimento e demonstração do case
- Ter **latência aceitável** para conversas em tempo real via Streamlit
- Ser compatível com LangGraph/LangChain via integração nativa ou LiteLLM

---

## Decisão

**Escolha:** `Gemini 2.0 Flash (Google AI)`

Usaremos o modelo `gemini-2.0-flash` como LLM primário para todos os agentes, acessado via API do Google AI Studio.

---

## Justificativa

| Critério | Avaliação |
|----------|-----------|
| Free tier | Generoso: 15 RPM, 1M tokens/dia — suficiente para desenvolvimento e demo |
| Tool calling | Suporte nativo e robusto a function calling |
| Qualidade em português | Excelente — treinado com grande corpus em PT-BR |
| Latência | Flash é otimizado para velocidade (~1s por resposta) |
| Integração LangChain | `langchain-google-genai` com suporte nativo |
| Custo em produção | Mais barato que GPT-4o para o mesmo nível de qualidade |

O Gemini 2.0 Flash oferece o melhor equilíbrio entre **qualidade**, **velocidade** e **custo zero** para demonstração. Sua performance em português é superior ao LLaMA e comparável ao GPT-4o Mini, com free tier significativamente mais generoso.

---

## Alternativas consideradas

| Opção | Prós | Contras | Descartada por |
|-------|------|---------|----------------|
| **GPT-4o Mini** | Confiável, amplamente documentado | Free tier limitado ($5 crédito inicial), pode esgotar durante demo | Risco de custo durante apresentação |
| **Groq + LLaMA 3** | Latência ultra-baixa (<0.5s), free tier | Qualidade de tool calling inferior, português menos fluente | Tool calling menos robusto para agentes complexos |
| **Gemini 2.5 Flash** | Capacidade de raciocínio superior | Mais lento, maior custo, thinking tokens desnecessários para este caso | Overhead desnecessário — 2.0 Flash resolve bem |
| **TogetherAI** | Múltiplos modelos open source | Free tier instável, latência variável, menos documentação LangChain | Confiabilidade para demo |

---

## Configuração adotada

```python
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    temperature=0.3,       # baixo para respostas consistentes e profissionais
    google_api_key=os.getenv("GEMINI_API_KEY")
)
```

**Temperatura 0.3:** Baixa o suficiente para respostas consistentes e profissionais, alta o suficiente para não parecer robótico. Temperatura 0.0 foi descartada para evitar rigidez nas respostas conversacionais.

---

## Consequências

**Positivas:**
- Desenvolvimento sem custo com o free tier
- Respostas em português com qualidade bancária
- Tool calling confiável para integração com ferramentas Python

**Negativas / trade-offs aceitos:**
- Dependência de conectividade com a API do Google
- Rate limit pode ser atingido em testes massivos (15 RPM no free tier)
- Possível degradação de qualidade se o modelo for atualizado sem aviso

---

## Referências

- [Google AI Studio — Free tier limits](https://ai.google.dev/pricing)
- [LangChain Google GenAI integration](https://python.langchain.com/docs/integrations/chat/google_generative_ai/)
- [Gemini 2.0 Flash release notes](https://deepmind.google/technologies/gemini/flash/)
