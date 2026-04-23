# ADR-003: Estratégia de Handoff entre Agentes

**Data:** 2026-04-22  
**Status:** Aceito  
**Autor:** Equipe Banco Ágil

---

## Contexto

O case exige explicitamente que as transições entre os 4 agentes sejam **imperceptíveis ao cliente**:

> *"Os redirecionamentos entre agentes devem ser realizados de maneira implícita, de modo que o cliente não perceba a transição. Ou seja, para o cliente ele está conversando com um único agente com habilidades diferentes."*

Isso significa que não pode haver mensagens como *"Estou te transferindo para o Agente de Crédito"*. A experiência deve ser de uma conversa fluida e contínua.

---

## Decisão

**Escolha:** Grafo único LangGraph com nós especializados e estado compartilhado

Todos os agentes são nós dentro de um único `StateGraph`. O estado da conversa (`BancoAgilState`) é passado por referência entre os nós. O roteamento é feito por **edges condicionais** que decidem qual nó ativar com base no estado atual.

---

## Justificativa

Em LangGraph, o handoff implícito é resolvido pelo próprio design do framework:

1. **Estado compartilhado:** Todos os nós leem e escrevem no mesmo objeto `state`. O histórico de mensagens, o cliente autenticado e o agente ativo são visíveis para todos os nós sem passagem explícita.

2. **Edge condicional:** Após cada resposta, uma função `router` analisa o estado e decide o próximo nó — sem o LLM precisar "anunciar" a transferência.

3. **Contexto preservado:** O nó de destino recebe o histórico completo e continua a conversa naturalmente, como se sempre tivesse sido ele.

```python
# Estrutura do estado compartilhado
class BancoAgilState(TypedDict):
    messages: Annotated[list, add_messages]   # histórico completo
    cliente_autenticado: Optional[dict]        # dados do cliente após auth
    agente_ativo: str                          # triagem | credito | entrevista | cambio
    tentativas_auth: int                       # contador para limite de 3
    encerrado: bool                            # sinaliza fim da conversa
```

```python
# Roteamento sem o cliente perceber
def router(state: BancoAgilState) -> str:
    if state["encerrado"]:
        return END
    if not state["cliente_autenticado"]:
        return "agente_triagem"
    return state["agente_ativo"]  # definido pelo agente de triagem após auth
```

---

## Alternativas consideradas

| Opção | Prós | Contras | Descartada por |
|-------|------|---------|----------------|
| **Orquestrador central (meta-agente)** | Flexível, dinâmico | +1 chamada LLM por turno, latência maior, ponto extra de falha | Overhead desnecessário para fluxo fixo |
| **Agentes independentes com passagem de contexto** | Isolamento total | Serialização manual de estado, difícil manter histórico coerente, verbose | Complexidade alta sem benefício |
| **Subgrafos por agente** | Encapsulamento | Comunicação entre subgrafos mais complexa, documentação escassa | Curva de aprendizado alto para o prazo |

---

## Fluxo de transição (exemplo: Triagem → Crédito)

```
Cliente: "quero consultar meu crédito"
    ↓
Nó: agente_triagem
    → Autentica cliente ✓
    → state["cliente_autenticado"] = {cpf: ..., nome: ...}
    → state["agente_ativo"] = "credito"
    ↓
router() → retorna "agente_credito"
    ↓
Nó: agente_credito
    → Recebe histórico completo
    → Responde: "Seu limite atual é R$ 5.000. Posso ajudar com mais alguma coisa?"
    ↓
Cliente percebe: conversa contínua com o mesmo "atendente"
```

---

## Consequências

**Positivas:**
- Handoff completamente imperceptível — requisito do case atendido nativamente
- Estado centralizado facilita debugging e auditoria
- Lógica de retry (3 tentativas de auth) implementada com um simples contador no estado
- Encerramento de conversa (`encerrado: true`) funciona de qualquer nó

**Negativas / trade-offs aceitos:**
- Grafo único pode crescer em complexidade se novos agentes forem adicionados no futuro (mitigável com subgrafos)
- Acoplamento entre agentes via estado compartilhado — mudança no schema afeta todos os nós

---

## Referências

- [LangGraph — Multi-agent handoffs](https://langchain-ai.github.io/langgraph/how-tos/agent-handoffs/)
- [LangGraph — StateGraph e TypedDict](https://langchain-ai.github.io/langgraph/concepts/low_level/)
- [ADR-001](ADR-001-framework-agentes.md) — Decisão de usar LangGraph
