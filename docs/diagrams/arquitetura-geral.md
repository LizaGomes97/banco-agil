# Diagrama de Arquitetura Geral — Banco Ágil

## Visão de Camadas

```mermaid
graph TB
    subgraph Frontend["Frontend — React 18 + TypeScript + Vite"]
        AuthCard["AuthCard\nCPF + Data de nascimento"]
        Chat["ChatMessage\nTypingIndicator"]
        Composer["MessageComposer"]
        ContactCard["ContactCard\nCanais pós-3 falhas"]
    end

    subgraph API["API Bridge — FastAPI  api/main.py"]
        ChatEndpoint["POST /api/chat"]
        ConvEndpoint["GET /api/conversations"]
        DebugEndpoint["GET /api/debug/logs"]
    end

    subgraph Grafo["LangGraph  src/graph.py"]
        Router["router()\ndeterminístico"]
        Triagem["agente_triagem\ntriagem/agent.py"]
        Credito["agente_credito\ncredito/agent.py"]
        Cambio["agente_cambio\ncambio/agent.py"]
        Entrevista["agente_entrevista\nentrevista/agent.py"]
        SaveMemoria["salvar_memoria"]
    end

    subgraph Infra["Infraestrutura  src/infrastructure/"]
        ModelProvider["model_provider.py\ninvocar_com_fallback\ntiers: fast / pro"]
        Contract["response_contract.py\nResponseContract\nCampoContrato"]
        LoggingCfg["logging_config.py\ntail_log()"]
        Checkpointer["checkpointer.py\nRedisSaver"]
        QdrantMem["qdrant_memory.py\nbuscar_memorias\nsalvar_interacao"]
        Cache["cache.py\nCacheComTTL"]
    end

    subgraph Tools["Tools  src/tools/"]
        IntentCls["intent_classifier.py\nclassificar_intencao"]
        CsvRepo["csv_repository.py\nbuscar_cliente\natualizar_score"]
        CreditTools["credit_tools.py\nverificar_elegibilidade\nregistrar_pedido"]
        ScoreCalc["score_calculator.py\ncalcular_score_credito"]
        ExchangeRate["exchange_rate.py\ncriar_tool_cambio (Tavily)"]
    end

    subgraph Storage["Armazenamento"]
        Redis[("Redis\nCheckpoints\ndo estado")]
        Qdrant[("Qdrant\nMemória\nsemântica")]
        CSV[("CSV\nClientes\nde teste")]
    end

    Frontend -->|HTTP via Vite proxy| API
    API -->|graph.invoke| Grafo
    Grafo --> Infra
    Grafo --> Tools
    Infra --> Storage
    Tools --> Storage
    LoggingCfg -.->|logs| DebugEndpoint
```

---

## Visão de Componentes por Agente

Cada agente é um módulo Python auto-contido:

```mermaid
graph LR
    subgraph Módulo["src/agents/credito/"]
        AgentPy["agent.py\nno_credito()"]
        ContractPy["contract.py\ncontrato_flash_direto()\ncontrato_sintese_pro()"]
        PromptMd["prompt.md\nSystem prompt Flash"]
        PromptPro["prompt_pro.md\nSystem prompt Pro"]
        Init["__init__.py\nexporta no_credito"]
    end

    subgraph Infra2["src/infrastructure/"]
        RC["response_contract.py\nResponseContract\nCampoContrato"]
        MP["model_provider.py\ninvocar_com_fallback"]
    end

    AgentPy --> ContractPy
    AgentPy --> PromptMd
    AgentPy --> PromptPro
    ContractPy --> RC
    AgentPy --> MP
    Init --> AgentPy
```

---

## Fluxo de uma requisição

```mermaid
sequenceDiagram
    participant U as Usuário
    participant FE as React Frontend
    participant API as FastAPI
    participant G as LangGraph
    participant LLM as Gemini
    participant DB as Redis

    U->>FE: Submete AuthCard (CPF + data)
    FE->>API: POST /api/chat {message}
    API->>G: graph.invoke({messages}, thread_id)
    G->>DB: Carrega checkpoint (state)
    G->>LLM: Triagem autentica
    LLM-->>G: cliente_autenticado
    G->>DB: Salva checkpoint
    G-->>API: {resposta_final, authenticated}
    API-->>FE: {reply, authenticated, encerrado}
    FE->>U: Exibe resposta (esconde AuthCard)
```

---

## Princípios arquiteturais

| Princípio | Implementação |
|---|---|
| **Identidade única** | Nenhum agente menciona transferências; filtro `_RE_HANDOFF` em todos |
| **Contrato explícito** | `resposta_final` sinaliza fim de turno; `contract.py` valida conteúdo |
| **Resiliência em camadas** | try/except em cada LLM call → fallback → correção programática |
| **Observabilidade** | Logging estruturado + `/api/debug/logs` + warnings de contrato |
| **Co-localização** | Código + prompt + contrato no mesmo módulo por agente |
| **Sem cálculos no LLM** | Score calculado em Python puro; valores injetados via contexto estruturado |
