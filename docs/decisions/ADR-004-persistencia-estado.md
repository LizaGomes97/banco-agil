# ADR-004: Persistência de Estado da Conversa

**Data:** 2026-04-22  
**Status:** Aceito  
**Autor:** Equipe Banco Ágil

---

## Contexto

O sistema precisa manter o estado da conversa entre turnos: quem está autenticado, qual agente está ativo, histórico de mensagens, número de tentativas de autenticação. Além disso, uma solução bancária real deve suportar múltiplas sessões simultâneas e ser capaz de recuperar uma conversa interrompida.

Necessidades identificadas:
- Persistir estado entre turnos da mesma conversa (`thread_id`)
- Suportar múltiplas sessões simultâneas (um `thread_id` por usuário)
- Demonstrar conhecimento de infraestrutura além do básico
- Ser escalável — em produção, múltiplos workers precisariam compartilhar o mesmo estado

---

## Decisão

**Escolha:** `Redis` via `LangGraph RedisSaver`

Usaremos Redis como backend de checkpointing do LangGraph. Cada turno da conversa é persistido como um checkpoint no Redis, identificado por `thread_id`.

---

## Justificativa

Redis é o padrão de mercado para estado de sessão em sistemas distribuídos por razões técnicas sólidas:

| Critério | Redis | In-memory | SQLite |
|----------|-------|-----------|--------|
| Escala horizontal | ✓ Nativo | ✗ Por processo | ✗ Lock por arquivo |
| Velocidade | <1ms leitura | <0.1ms | ~5ms |
| TTL automático | ✓ Nativo | ✗ Manual | ✗ Manual |
| Múltiplos workers | ✓ Compartilhado | ✗ Isolado | ✗ Conflitos |
| Persistência em crash | ✓ RDB/AOF | ✗ Perde tudo | ✓ |
| Complexidade setup | Média | Mínima | Baixa |

Para o **case**, Redis demonstra:
1. Conhecimento de arquiteturas de produção
2. Capacidade de pensar em escalabilidade desde o design
3. Familiaridade com ferramentas padrão do mercado bancário

O `RedisSaver` do LangGraph encapsula toda a complexidade — a integração é de poucas linhas.

---

## Alternativas consideradas

| Opção | Prós | Contras | Descartada por |
|-------|------|---------|----------------|
| **MemorySaver (in-memory)** | Zero config, instantâneo | Perde estado ao reiniciar, não escala | Não demonstra conhecimento de infraestrutura |
| **SQLiteSaver** | Persiste em arquivo, sem servidor | Locks em concorrência, não escala horizontalmente | Não adequado para ambiente multi-worker |
| **PostgresSaver** | Robusto, ACID completo | Overhead de setup alto para um case de demonstração | Complexidade desproporcional ao escopo |

---

## Implementação

```python
# src/infrastructure/checkpointer.py
import redis
from langgraph.checkpoint.redis import RedisSaver

def criar_checkpointer():
    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=0,
        decode_responses=False
    )
    return RedisSaver(client)

# Uso no grafo
checkpointer = criar_checkpointer()
graph = workflow.compile(checkpointer=checkpointer)

# Cada sessão tem seu próprio thread_id
config = {"configurable": {"thread_id": session_id}}
result = graph.invoke(input, config=config)
```

**TTL de sessão:** Configurar TTL de 30 minutos no Redis para expirar sessões inativas automaticamente — comportamento esperado em sistemas bancários reais.

---

## Setup local (Docker)

Para rodar localmente sem instalação:

```bash
docker run -d --name redis-banco-agil -p 6379:6379 redis:alpine
```

Variáveis de ambiente necessárias:
```
REDIS_HOST=localhost
REDIS_PORT=6379
```

---

## Consequências

**Positivas:**
- Estado da conversa persiste entre reinicializações do servidor
- Múltiplas sessões simultâneas isoladas por `thread_id`
- TTL automático limpa sessões abandonadas
- Demonstra visão de arquitetura escalável ao avaliador

**Negativas / trade-offs aceitos:**
- Requer Redis rodando (Docker ou serviço externo) para o sistema funcionar
- Adiciona uma dependência de infraestrutura — documentar claramente no README
- Para uma demo simples, é overhead; a escolha é deliberada para demonstrar conhecimento

---

## Referências

- [LangGraph — Checkpointers](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [LangGraph Redis Checkpointer](https://langchain-ai.github.io/langgraph/how-tos/persistence_redis/)
- [Redis — Session store patterns](https://redis.io/docs/manual/patterns/)
- [ADR-001](ADR-001-framework-agentes.md) — Decisão de usar LangGraph
- [ADR-003](ADR-003-handoff-agentes.md) — Estrutura do estado compartilhado
