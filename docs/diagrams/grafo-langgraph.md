# Diagrama do Grafo LangGraph — Banco Ágil

## Topologia completa

```mermaid
stateDiagram-v2
    [*] --> agente_triagem

    agente_triagem --> agente_triagem : autenticado\nresposta_final=None\nagente_ativo="triagem"
    agente_triagem --> agente_credito : agente_ativo="credito"\nresposta_final=None
    agente_triagem --> agente_cambio : agente_ativo="cambio"\nresposta_final=None
    agente_triagem --> agente_entrevista : agente_ativo="entrevista"\nresposta_final=None
    agente_triagem --> salvar_memoria : encerrado=True\nmemoria_salva=False
    agente_triagem --> [*] : resposta_final != None

    agente_credito --> agente_entrevista : agente_ativo="entrevista"\nresposta_final != None
    agente_credito --> salvar_memoria : encerrado=True
    agente_credito --> [*] : resposta_final != None

    agente_cambio --> agente_credito : agente_ativo="credito"\nresposta_final=None
    agente_cambio --> salvar_memoria : encerrado=True
    agente_cambio --> [*] : resposta_final != None

    agente_entrevista --> agente_credito : agente_ativo="credito"\nresposta_final != None
    agente_entrevista --> salvar_memoria : encerrado=True
    agente_entrevista --> [*] : resposta_final != None

    salvar_memoria --> [*] : sempre
```

---

## Lógica do Router

```mermaid
flowchart TD
    START([router chamado após nó]) --> A{encerrado?}

    A -- Sim --> B{memoria_salva?}
    B -- Não --> SAVE[salvar_memoria]
    B -- Sim --> END1([END])
    SAVE --> END2([END])

    A -- Não --> C{resposta_final\nnão é None?}
    C -- Sim --> END3([END])
    C -- Não --> D{cliente\nautenticado?}

    D -- Não --> TRIAGEM[agente_triagem]
    D -- Sim --> E{agente_ativo}

    E -- triagem --> TRIAGEM
    E -- credito --> CREDITO[agente_credito]
    E -- cambio --> CAMBIO[agente_cambio]
    E -- entrevista --> ENTREVISTA[agente_entrevista]
    E -- inválido --> TRIAGEM
```

---

## Código de referência (`src/graph.py`)

```python
def router(state: BancoAgilState) -> str:
    # Encerramento: salva memória semântica antes de terminar
    if state.get("encerrado"):
        if not state.get("memoria_salva"):
            return "salvar_memoria"
        return END

    # Agente sinalizou resposta final → fim do turno
    if state.get("resposta_final") is not None:
        return END

    # Turno em andamento → rotear para o agente correto
    if not state.get("cliente_autenticado"):
        return "agente_triagem"

    agente = state.get("agente_ativo", "triagem")
    destino = f"agente_{agente}"

    mapa_valido = {"agente_triagem", "agente_credito", "agente_entrevista", "agente_cambio"}
    if destino not in mapa_valido:
        logger.warning("agente_ativo inválido '%s', retornando triagem", agente)
        return "agente_triagem"

    return destino
```

```python
# Montagem do grafo
workflow = StateGraph(BancoAgilState)

workflow.add_node("agente_triagem",    no_triagem)
workflow.add_node("agente_credito",    no_credito)
workflow.add_node("agente_entrevista", no_entrevista)
workflow.add_node("agente_cambio",     no_cambio)
workflow.add_node("salvar_memoria",    no_salvar_memoria)

workflow.set_entry_point("agente_triagem")

for agente in ["agente_triagem", "agente_credito", "agente_entrevista", "agente_cambio"]:
    workflow.add_conditional_edges(agente, router)

workflow.add_edge("salvar_memoria", END)   # sempre termina após salvar

checkpointer = criar_checkpointer()        # RedisSaver
graph = workflow.compile(checkpointer=checkpointer)
```

---

## Por que o router não usa LLM

O router é chamado **após cada nó**, potencialmente várias vezes por turno. Usar um LLM ali adicionaria:

- **Latência**: 300–800 ms por chamada adicional ao Gemini
- **Custo**: chamadas extras sem valor de negócio
- **Não-determinismo**: risco de loops ou destinos inesperados

A lógica é 100% baseada em campos de estado (`resposta_final`, `encerrado`, `agente_ativo`, `cliente_autenticado`), tornando-a:

- ✅ Previsível e auditável
- ✅ Testável unitariamente sem mocks de LLM
- ✅ Com tempo de execução constante (~1 ms)

O único uso de LLM no roteamento é o **classificador de intenção** (`intent_classifier.py`), que é chamado **dentro** dos agentes de triagem, não no router. Ele tem cache TTL de 5 min para mensagens repetidas (ADR-011).

---

## Nó `salvar_memoria`

Executado **uma vez** ao final de cada sessão (`encerrado=True`):

1. Gera um resumo da conversa via LLM (prompt interno ao nó)
2. Persiste no Qdrant com filtro por CPF
3. Seta `memoria_salva=True` para evitar execução dupla

```mermaid
sequenceDiagram
    participant Router
    participant SaveMem as salvar_memoria
    participant LLM as Gemini
    participant Qdrant

    Router->>SaveMem: encerrado=True, memoria_salva=False
    SaveMem->>LLM: Gerar resumo da conversa
    LLM-->>SaveMem: "Cliente consultou limite..."
    SaveMem->>Qdrant: salvar_interacao(cpf, resumo, agentes)
    SaveMem-->>Router: {memoria_salva: True}
    Router->>Router: END
```
