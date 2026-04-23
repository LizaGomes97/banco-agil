# Fluxo de Handoff Completo — Banco Ágil

O cliente sempre percebe que fala com **um único assistente**. Os handoffs entre agentes são completamente invisíveis — internos ao grafo LangGraph.

---

## O que o cliente vê

```
[AuthCard] → Saudação → Perguntas → Respostas → Encerramento
                                    ↑
                     (agentes trocam silenciosamente por baixo)
```

Não há mensagens como "vou te transferir" ou "aguarde enquanto conecto com um especialista".

---

## Por baixo dos panos — diagrama de sequência

```mermaid
sequenceDiagram
    participant U as Usuário
    participant FE as React Frontend
    participant API as FastAPI
    participant Router as router()
    participant T as Triagem
    participant C as Crédito
    participant E as Entrevista
    participant CAM as Câmbio
    participant Redis as Redis
    participant Qdrant as Qdrant

    %% Autenticação (resumida)
    U->>FE: AuthCard (CPF + data)
    FE->>API: POST /api/chat
    API->>Router: graph.invoke
    Router->>T: Autenticar
    T-->>Router: autenticado, resposta_final=None
    Router->>T: Saudar cliente
    T-->>Router: resposta_final="Olá Ana!"
    Router->>Redis: salvar checkpoint
    Router-->>API: END
    API-->>FE: {reply, authenticated:true}

    %% Consulta de crédito
    U->>FE: "quero saber meu limite"
    FE->>API: POST /api/chat
    API->>Router: graph.invoke (carrega state do Redis)
    Router->>T: classificar intenção
    T-->>Router: agente_ativo="credito", resposta_final=None
    Router->>C: no_credito
    C-->>Router: resposta_final="Seu limite é R$ 5.000,00"
    Router->>Redis: salvar
    Router-->>API: END
    API-->>FE: {reply}

    %% Solicitação de aumento (Flash→Pro)
    U->>FE: "quero aumentar meu limite"
    FE->>API: POST /api/chat
    API->>Router: graph.invoke
    Router->>T: passthrough (agente_ativo="credito")
    T-->>Router: resposta_final=None
    Router->>C: no_credito (Flash)
    Note over C: Flash chama tools\nverificar_elegibilidade\nregistrar_pedido
    C-->>Router: resposta_final=None (tool calls pendentes)
    Note over C: Pro sintetiza decisão\ncontrato valida limite+score
    C-->>Router: resposta_final="Aprovado! Novo limite: R$ 7.000,00"
    Router->>Redis: salvar
    Router-->>API: END

    %% Entrevista de crédito
    U->>FE: "quero melhorar meu score"
    FE->>API: POST /api/chat
    API->>Router: graph.invoke
    Router->>T: classificar intenção="entrevista"
    T-->>Router: agente_ativo="entrevista", resposta_final=None
    Router->>E: no_entrevista (coleta dados)
    E-->>Router: resposta_final="Qual é sua renda mensal?"
    Note over E,Router: múltiplos turnos de coleta...
    E-->>Router: tool calcular_score_credito()
    E-->>Router: agente_ativo="credito", resposta_final="Score: 520!"
    Router->>C: no_credito (reavalia com score novo)
    C-->>Router: resposta_final="Com o novo score, aprovamos..."
    Router->>Redis: salvar

    %% Câmbio
    U->>FE: "quanto está o dólar?"
    FE->>API: POST /api/chat
    API->>Router: graph.invoke
    Router->>T: classificar intenção="cambio"
    T-->>Router: agente_ativo="cambio", resposta_final=None
    Router->>CAM: no_cambio
    Note over CAM: Chama Tavily API
    CAM-->>Router: resposta_final="USD está a R$ 5,87"
    Router-->>API: END

    %% Encerramento
    U->>FE: "obrigado, tchau"
    FE->>API: POST /api/chat
    API->>Router: graph.invoke
    Router->>T: detecta intenção encerrar
    T-->>Router: encerrado=True, resposta_final=None
    Router->>Router: salvar_memoria?
    Router->>Qdrant: Resumo semântico da sessão
    Qdrant-->>Router: OK
    Router-->>API: END (encerrado=True)
    API-->>FE: {reply, encerrado:true}
    FE->>U: Mensagem de encerramento
```

---

## Encerramento e salvamento de memória

```mermaid
flowchart LR
    TRIGGER["Qualquer agente\nencerrado=True"]
    MEM_CHECK{memoria_salva?}
    SAVE_MEM["no_salvar_memoria()\nLLM gera resumo"]
    QDRANT[("Qdrant\nMemória semântica")]
    END_NODE([END])

    TRIGGER --> MEM_CHECK
    MEM_CHECK -- Não --> SAVE_MEM
    SAVE_MEM --> QDRANT
    QDRANT --> END_NODE
    MEM_CHECK -- Sim --> END_NODE
```

O resumo gerado inclui:
- O que o cliente solicitou
- Quais agentes atenderam
- O resultado final (aprovado, negado, informação fornecida)

Na **próxima sessão** deste cliente, os resumos são recuperados do Qdrant e injetados no contexto de cada agente, dando continuidade ao atendimento de forma inteligente.

---

## Guardrails de identidade única

Em todos os agentes, dois mecanismos previnem que o cliente perceba os handoffs:

### 1. Regra no prompt (`prompt.md` de cada agente)
```
Identidade — regra absoluta:
Você é UM ÚNICO assistente. NUNCA mencione transferências, outros agentes,
especialistas, setores ou sistemas internos.
Frases proibidas: "vou te redirecionar", "vou te encaminhar", "outro setor".
```

### 2. Filtro de runtime (`_RE_HANDOFF` em cada `agent.py`)
```python
_RE_HANDOFF = re.compile(
    r"(transferi|direcionar|especialista|setor|área de atendimento|encaminh)",
    re.IGNORECASE,
)

if _RE_HANDOFF.search(texto):
    logger.warning("[AGENTE] Handoff detectado — descartado")
    texto = fallback_seguro  # resposta neutra sem mencionar troca
```

Se o LLM violar a regra mesmo assim, o código intercepta e substitui antes de chegar ao cliente.
