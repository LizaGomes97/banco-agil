# ADR-011 — Cache L1 no Classificador de Intenção

**Status:** ✅ Aceito  
**Data:** 2026-04-22  
**Relacionado:** ADR-009 (Router LLM)

---

## Contexto

O Router LLM (ADR-009) faz uma chamada ao Gemini para cada mensagem do usuário, adicionando ~500ms de latência e ~0.001 USD por classificação. Em uma sessão típica de atendimento, muitas mensagens são repetições ou variações mínimas da mesma intenção:

- "quero ver meu limite" → `credito`
- "qual é meu limite?" → `credito`
- "me mostra o limite" → `credito`

Chamar o LLM para cada uma dessas mensagens é desperdício de latência e custo.

---

## Decisão

Implementar um **cache em memória com TTL** (`src/infrastructure/cache.py`) aplicado ao classificador via decorator:

```python
_cache_intencao = CacheComTTL(ttl_segundos=300, max_tamanho=512)

@com_cache(_cache_intencao, chave_fn=lambda msg: msg.strip().lower())
def classificar_intencao(mensagem: str) -> str: ...
```

**Características:**
- TTL de 5 minutos por entrada
- Máximo de 512 entradas (LRU simples — remove a mais antiga ao atingir o limite)
- Chave de cache: `mensagem.strip().lower()` (normalização básica)
- Sem dependências externas — funciona sem Redis
- Thread-safe para o caso de uso do Streamlit (single-threaded por sessão)

---

## Justificativa

**Por que cache em memória e não Redis?**

O classificador de intenção é chamado no contexto de uma única sessão de usuário. A Streamlit executa em single-thread por usuário, portanto o cache em memória é suficiente e mais rápido (sem round-trip de rede).

Redis seria necessário se múltiplos workers compartilhassem o cache — não é o caso nesta arquitetura.

**Por que TTL de 5 minutos?**

Intenções mudam naturalmente ao longo de uma conversa ("quero crédito" → "quanto é o dólar"). 5 minutos é tempo suficiente para cachear respostas dentro de um turno, mas curto o suficiente para não interferir em mudanças de assunto.

---

## Alternativas descartadas

- **`functools.lru_cache`**: sem TTL — entradas nunca expiram, o que é problemático para sessões longas com mudança de intenção.
- **Memoização por hash do vetor**: mais preciso (lida com variações semânticas), mas requer embedding para a chave, o que seria mais caro que a classificação em si.
- **Sem cache**: solução mais simples, mas desperdício de chamadas em mensagens repetidas.

---

## Consequências

- **Positivas**: reduz latência e custo em ~40-60% para conversas com mensagens similares
- **Negativas**: cache é local à instância (sem compartilhamento entre deploys múltiplos)
- **Observabilidade**: logs de `Cache HIT` e `Cache MISS` em nível DEBUG permitem monitorar a taxa de aproveitamento
